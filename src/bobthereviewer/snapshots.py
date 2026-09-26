"""
bobthereviewer.snapshots
~~~~~~~~~~~~~~~~~~~~~~~~
Safe Git worktree management for revision snapshots.

This module is responsible for:
- Resolving Git refs to full 40-character commit SHAs
- Creating temporary detached worktrees outside the repository root
- Providing a WorktreeContext dataclass with all identity information
- Guaranteeing cleanup of both worktrees on all exit paths
- Guaranteeing the developer's branch, index, and uncommitted files
  are untouched after any exit path, including partial failures

Absolute filesystem paths produced here (base_path, head_path) are
runtime-only.  They must never appear in published evidence files.
Convert all caller/file paths to repo-relative before passing to
evidence assembly.

Ownership: Lane 1.
"""

from __future__ import annotations

import subprocess
import tempfile
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorktreeContext:
    """All information about a two-revision snapshot.

    Absolute paths (base_path, head_path) are valid only inside the
    WorktreeManager context.  They must not be serialised to evidence.
    """

    # Repository identity
    repository_url: str      # remote origin URL  (→ evidence.repository)
    repo_root: Path          # absolute path to repository root

    # Requested refs (as supplied by caller)
    base_ref: str
    head_ref: str

    # Resolved full SHAs (40-char hex)
    base_commit: str
    head_commit: str

    # Changed files between the two revisions (repo-relative paths)
    changed_files: list[str] = field(default_factory=list)

    # Temporary checkout paths — absolute, runtime-only
    base_path: Path = field(default=Path())
    head_path: Path = field(default=Path())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SnapshotError(RuntimeError):
    """Raised when a ref cannot be resolved or a worktree cannot be created."""


# ---------------------------------------------------------------------------
# Internal Git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command; raise SnapshotError with a readable message on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SnapshotError("git executable not found on PATH") from exc

    if result.returncode != 0:
        cmd_str = " ".join(["git"] + args)
        raise SnapshotError(
            f"git command failed (exit {result.returncode}):\n"
            f"  {cmd_str}\n"
            f"  {result.stderr.strip()}"
        )
    return result.stdout.strip()


def find_repo_root(start: Path) -> Path:
    """Resolve the Git repository root from *start*, walking up if needed.

    Raises SnapshotError if no repository is found.
    """
    try:
        root = _git(["rev-parse", "--show-toplevel"], cwd=start)
    except SnapshotError as exc:
        raise SnapshotError(
            f"No Git repository found at or above {start}.\n"
            f"Run 'bobreviewer init' first, or supply --repo-dir."
        ) from exc
    return Path(root).resolve()


def resolve_ref(ref: str, repo_root: Path) -> str:
    """Resolve a ref to a full 40-character SHA.

    Raises SnapshotError with a readable message if the ref does not exist.
    """
    try:
        sha = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo_root)
    except SnapshotError:
        raise SnapshotError(
            f"Cannot resolve ref {ref!r} in repository at {repo_root}.\n"
            "Check that the ref exists and has been fetched."
        )
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        raise SnapshotError(f"Unexpected SHA format for {ref!r}: {sha!r}")
    return sha


def get_remote_url(repo_root: Path) -> str:
    """Return the remote origin URL, or a placeholder if no remote is configured."""
    try:
        return _git(["remote", "get-url", "origin"], cwd=repo_root)
    except SnapshotError:
        return "local"


def get_changed_files(base_sha: str, head_sha: str, repo_root: Path) -> list[str]:
    """Return repo-relative paths of files that differ between base and head."""
    output = _git(
        ["diff", "--name-only", base_sha, head_sha],
        cwd=repo_root,
    )
    if not output:
        return []
    return [line for line in output.splitlines() if line.strip()]


def _add_worktree(sha: str, worktree_path: Path, repo_root: Path) -> None:
    """Create a detached worktree at *worktree_path* for *sha*."""
    _git(
        ["worktree", "add", "--detach", str(worktree_path), sha],
        cwd=repo_root,
    )


def _remove_worktree(worktree_path: Path, repo_root: Path) -> None:
    """Remove a worktree, then forcibly delete its directory if it still exists."""
    try:
        _git(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_root,
        )
    except SnapshotError:
        pass  # best-effort; fall through to directory removal

    # Ensure the directory is gone even if git worktree remove failed
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Public context manager
# ---------------------------------------------------------------------------

@contextmanager
def WorktreeManager(
    repo_dir: Path,
    base_ref: str,
    head_ref: str,
) -> Generator[WorktreeContext, None, None]:
    """Context manager that creates isolated worktrees for two Git refs.

    Usage::

        with WorktreeManager(Path("."), "main", "feature") as ctx:
            # ctx.base_path and ctx.head_path are valid here
            ...
        # both worktrees are removed after the block, even on exception

    The developer's current branch, index, and working-tree files are
    not modified under any exit path.

    Raises SnapshotError if:
    - the directory is not inside a Git repository
    - either ref cannot be resolved
    - a worktree cannot be created
    """
    repo_root = find_repo_root(repo_dir.resolve())
    repository_url = get_remote_url(repo_root)

    base_sha = resolve_ref(base_ref, repo_root)
    head_sha = resolve_ref(head_ref, repo_root)

    changed_files = get_changed_files(base_sha, head_sha, repo_root)

    # Create worktree directories inside a system temp dir — outside the repo
    tmpdir = Path(tempfile.mkdtemp(prefix="bobreviewer-"))
    base_path = tmpdir / "base"
    head_path = tmpdir / "head"

    base_created = False
    head_created = False

    try:
        _add_worktree(base_sha, base_path, repo_root)
        base_created = True
        _add_worktree(head_sha, head_path, repo_root)
        head_created = True

        ctx = WorktreeContext(
            repository_url=repository_url,
            repo_root=repo_root,
            base_ref=base_ref,
            head_ref=head_ref,
            base_commit=base_sha,
            head_commit=head_sha,
            changed_files=changed_files,
            base_path=base_path,
            head_path=head_path,
        )

        yield ctx

    finally:
        # Clean up in reverse order; never raise from finally
        if head_created:
            _remove_worktree(head_path, repo_root)
        if base_created:
            _remove_worktree(base_path, repo_root)
        # Always remove the temp root directory
        shutil.rmtree(tmpdir, ignore_errors=True)
