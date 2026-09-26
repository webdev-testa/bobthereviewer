"""
Tests for bobreviewer.snapshots — Slice 2.

All tests use temporary Git repositories created from scratch.
The developer's actual checkout is never modified.

Checks:
- WorktreeManager creates two worktrees outside the repo root
- Both worktrees contain the correct committed content for their refs
- Worktrees are cleaned up on normal exit
- Worktrees are cleaned up when an exception is raised inside the block
- Developer's branch, index, and uncommitted files are unchanged after (normal + exception)
- WorktreeContext.base_commit and head_commit are full 40-char SHAs
- WorktreeContext.changed_files contains repo-relative paths
- An unresolvable ref raises SnapshotError before any worktree is created
- find_repo_root resolves correctly from a subdirectory
- resolve_ref returns a 40-char hex SHA
- get_changed_files returns repo-relative paths
"""

import os
import subprocess
from pathlib import Path

import pytest

from bobthereviewer.snapshots import (
    SnapshotError,
    WorktreeContext,
    WorktreeManager,
    find_repo_root,
    get_changed_files,
    resolve_ref,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    """Create a minimal Git repository with two commits and return its root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)

    # Commit 1 — base: only helper.py
    (repo / "helper.py").write_text("def add(a, b):\n    return a + b\n")
    _git(["add", "helper.py"], cwd=repo)
    _git(["commit", "-m", "base: add helper"], cwd=repo)
    _git(["tag", "base"], cwd=repo)

    # Commit 2 — head: change helper.py, add caller.py
    (repo / "helper.py").write_text("def add(a, b):\n    return a + b + 1\n")
    (repo / "caller.py").write_text("from helper import add\nresult = add(1, 2)\n")
    _git(["add", "helper.py", "caller.py"], cwd=repo)
    _git(["commit", "-m", "head: change helper, add caller"], cwd=repo)
    _git(["tag", "head"], cwd=repo)

    return repo


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

def test_find_repo_root_from_root(tmp_path):
    repo = make_repo(tmp_path)
    assert find_repo_root(repo) == repo.resolve()


def test_find_repo_root_from_subdirectory(tmp_path):
    repo = make_repo(tmp_path)
    subdir = repo / "subdir"
    subdir.mkdir()
    assert find_repo_root(subdir) == repo.resolve()


def test_find_repo_root_outside_repo(tmp_path):
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    with pytest.raises(SnapshotError, match="No Git repository"):
        find_repo_root(non_repo)


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------

def test_resolve_ref_returns_40char_sha(tmp_path):
    repo = make_repo(tmp_path)
    sha = resolve_ref("base", repo)
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_resolve_ref_raises_on_unknown_ref(tmp_path):
    repo = make_repo(tmp_path)
    with pytest.raises(SnapshotError, match="Cannot resolve ref"):
        resolve_ref("nonexistent-ref-xyz", repo)


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------

def test_get_changed_files_returns_repo_relative_paths(tmp_path):
    repo = make_repo(tmp_path)
    base_sha = resolve_ref("base", repo)
    head_sha = resolve_ref("head", repo)
    changed = get_changed_files(base_sha, head_sha, repo)
    assert "helper.py" in changed
    assert "caller.py" in changed
    # All paths must be repo-relative (no leading slash, no absolute prefix)
    for p in changed:
        assert not Path(p).is_absolute(), f"absolute path leaked: {p}"


def test_get_changed_files_no_changes_returns_empty(tmp_path):
    repo = make_repo(tmp_path)
    sha = resolve_ref("base", repo)
    assert get_changed_files(sha, sha, repo) == []


# ---------------------------------------------------------------------------
# WorktreeManager — success path
# ---------------------------------------------------------------------------

def test_worktree_manager_creates_two_checkouts(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        assert ctx.base_path.exists()
        assert ctx.head_path.exists()
        # Worktrees must be outside the repository root
        assert not str(ctx.base_path).startswith(str(repo))
        assert not str(ctx.head_path).startswith(str(repo))


def test_worktree_manager_base_has_correct_content(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        base_helper = (ctx.base_path / "helper.py").read_text()
        assert "return a + b\n" in base_helper
        assert "return a + b + 1" not in base_helper
        assert not (ctx.base_path / "caller.py").exists()


def test_worktree_manager_head_has_correct_content(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        head_helper = (ctx.head_path / "helper.py").read_text()
        assert "return a + b + 1" in head_helper
        assert (ctx.head_path / "caller.py").exists()


def test_worktree_manager_context_has_full_shas(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        assert len(ctx.base_commit) == 40
        assert len(ctx.head_commit) == 40
        assert all(c in "0123456789abcdef" for c in ctx.base_commit)
        assert all(c in "0123456789abcdef" for c in ctx.head_commit)


def test_worktree_manager_context_changed_files_are_relative(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        for p in ctx.changed_files:
            assert not Path(p).is_absolute(), f"absolute path leaked: {p}"


def test_worktree_manager_context_refs_match_input(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        assert ctx.base_ref == "base"
        assert ctx.head_ref == "head"


# ---------------------------------------------------------------------------
# WorktreeManager — cleanup
# ---------------------------------------------------------------------------

def test_worktrees_removed_after_context_exit(tmp_path):
    repo = make_repo(tmp_path)
    with WorktreeManager(repo, "base", "head") as ctx:
        base_path = ctx.base_path
        head_path = ctx.head_path

    assert not base_path.exists(), "base worktree not cleaned up"
    assert not head_path.exists(), "head worktree not cleaned up"


def test_worktrees_removed_on_exception_inside_block(tmp_path):
    repo = make_repo(tmp_path)
    base_path = head_path = None
    try:
        with WorktreeManager(repo, "base", "head") as ctx:
            base_path = ctx.base_path
            head_path = ctx.head_path
            raise RuntimeError("simulated failure inside context")
    except RuntimeError:
        pass

    assert base_path is not None
    assert not base_path.exists(), "base worktree not cleaned up after exception"
    assert not head_path.exists(), "head worktree not cleaned up after exception"


def test_developer_checkout_unchanged_after_normal_exit(tmp_path):
    """The developer's branch, index, and files must not be modified."""
    repo = make_repo(tmp_path)

    # Record state before
    branch_before = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    head_sha_before = _git(["rev-parse", "HEAD"], cwd=repo)
    # Add an uncommitted file to check it survives
    (repo / "uncommitted.txt").write_text("pending work")

    with WorktreeManager(repo, "base", "head"):
        pass

    branch_after = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    head_sha_after = _git(["rev-parse", "HEAD"], cwd=repo)

    assert branch_before == branch_after, "branch changed"
    assert head_sha_before == head_sha_after, "HEAD moved"
    assert (repo / "uncommitted.txt").exists(), "uncommitted file was removed"
    assert (repo / "uncommitted.txt").read_text() == "pending work"


def test_developer_checkout_unchanged_after_exception(tmp_path):
    """Developer environment preserved even when an exception occurs."""
    repo = make_repo(tmp_path)
    branch_before = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    (repo / "staged.txt").write_text("staged change")
    _git(["add", "staged.txt"], cwd=repo)

    try:
        with WorktreeManager(repo, "base", "head"):
            raise ValueError("boom")
    except ValueError:
        pass

    branch_after = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    assert branch_before == branch_after, "branch changed after exception"

    # Staged file must still be staged
    status = _git(["status", "--porcelain"], cwd=repo)
    assert "staged.txt" in status


# ---------------------------------------------------------------------------
# WorktreeManager — error cases
# ---------------------------------------------------------------------------

def test_unresolvable_base_ref_raises_before_worktree_creation(tmp_path):
    repo = make_repo(tmp_path)
    with pytest.raises(SnapshotError, match="Cannot resolve ref"):
        with WorktreeManager(repo, "no-such-tag", "head"):
            pass  # should not reach here


def test_unresolvable_head_ref_raises_before_second_worktree(tmp_path):
    repo = make_repo(tmp_path)
    with pytest.raises(SnapshotError, match="Cannot resolve ref"):
        with WorktreeManager(repo, "base", "no-such-tag"):
            pass


def test_worktree_manager_from_subdirectory(tmp_path):
    """find_repo_root must work when launched from a subdirectory."""
    repo = make_repo(tmp_path)
    subdir = repo / "subdir"
    subdir.mkdir()
    with WorktreeManager(subdir, "base", "head") as ctx:
        assert ctx.repo_root == repo.resolve()
        assert ctx.base_path.exists()
