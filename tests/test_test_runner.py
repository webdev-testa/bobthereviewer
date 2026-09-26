"""Tests for bobreviewer.test_runner (ST 8)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from bobreviewer.test_runner import (
    _compute_frozen_suite_hash,
    _discover_test_files,
    run_tests,
)

PYTHON = sys.executable


def _noop_emit(step, status, message):
    pass


def _make_triage(skipped=False):
    return {"category": "code", "skipped": skipped, "skip_reason": None}


def _write(path: Path, src: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(src))


# ---------------------------------------------------------------------------
# Frozen-suite hash
# ---------------------------------------------------------------------------

class TestFrozenSuiteHash:
    def test_empty_is_deterministic(self):
        h1 = _compute_frozen_suite_hash([])
        h2 = _compute_frozen_suite_hash([])
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = _compute_frozen_suite_hash([("tests/a.py", b"content1")])
        h2 = _compute_frozen_suite_hash([("tests/a.py", b"content2")])
        assert h1 != h2

    def test_order_independent(self):
        pair_a = ("tests/a.py", b"aaa")
        pair_b = ("tests/b.py", b"bbb")
        h1 = _compute_frozen_suite_hash([pair_a, pair_b])
        h2 = _compute_frozen_suite_hash([pair_b, pair_a])
        assert h1 == h2  # sorted internally

    def test_hash_changes_when_file_content_changes(self):
        h1 = _compute_frozen_suite_hash([("tests/a.py", b"original")])
        h2 = _compute_frozen_suite_hash([("tests/a.py", b"modified")])
        assert h1 != h2


# ---------------------------------------------------------------------------
# Test file discovery
# ---------------------------------------------------------------------------

class TestDiscoverTestFiles:
    def test_finds_test_prefixed_files(self, tmp_path):
        _write(tmp_path / "tests" / "test_foo.py", "def test_it(): pass")
        files = _discover_test_files(str(tmp_path))
        paths = [p for p, _ in files]
        assert "tests/test_foo.py" in paths

    def test_finds_test_suffixed_files(self, tmp_path):
        _write(tmp_path / "tests" / "foo_test.py", "def test_it(): pass")
        files = _discover_test_files(str(tmp_path))
        paths = [p for p, _ in files]
        assert "tests/foo_test.py" in paths

    def test_does_not_find_non_test_files(self, tmp_path):
        _write(tmp_path / "mymod.py", "def f(): pass")
        files = _discover_test_files(str(tmp_path))
        assert files == []

    def test_no_duplicates(self, tmp_path):
        _write(tmp_path / "tests" / "test_a.py", "def test_it(): pass")
        files = _discover_test_files(str(tmp_path))
        paths = [p for p, _ in files]
        assert len(paths) == len(set(paths))


# ---------------------------------------------------------------------------
# Triage skip
# ---------------------------------------------------------------------------

class TestTriageSkip:
    def test_skipped_triage_returns_empty(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        _write(base / "tests" / "test_it.py", "def test_x(): assert True")

        results, suite_hash = run_tests(
            str(base), str(head), PYTHON,
            {"category": "docs-only", "skipped": True, "skip_reason": "docs-only"},
            _noop_emit,
        )
        assert results == {"base": {}, "head": {}}
        assert suite_hash is None


# ---------------------------------------------------------------------------
# Integration test against demo sample project
# ---------------------------------------------------------------------------

def _checkout_tag(repo_root: Path, tag: str, dest: Path) -> None:
    import subprocess
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(dest), tag],
        cwd=str(repo_root), check=True, capture_output=True,
    )


def _remove_worktree(repo_root: Path, dest: Path) -> None:
    import subprocess
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(dest)],
        cwd=str(repo_root), capture_output=True,
    )


@pytest.mark.integration
def test_frozen_suite_passes_on_both_tags(tmp_path):
    """All demo sample project tests should pass on both demo-base and demo-rounding-change."""
    repo_root = Path(__file__).parent.parent
    base_wt = tmp_path / "base_wt"
    head_wt = tmp_path / "head_wt"

    _checkout_tag(repo_root, "demo-base", base_wt)
    try:
        _checkout_tag(repo_root, "demo-rounding-change", head_wt)
        try:
            base_proj = str(base_wt / "demo" / "sample_project")
            head_proj = str(head_wt / "demo" / "sample_project")

            results, suite_hash = run_tests(
                base_proj, head_proj, PYTHON, _make_triage(), _noop_emit,
            )

            assert suite_hash is not None
            assert len(suite_hash) == 64  # SHA-256 hex

            for side, side_results in [("base", results["base"]), ("head", results["head"])]:
                assert side_results, f"{side} side has no test results"
                for node_id, r in side_results.items():
                    assert r["status"] == "pass", (
                        f"{side}/{node_id} expected pass, got {r['status']}: {r['message']}"
                    )

            # Both sides should have the same node IDs (same frozen suite)
            assert set(results["base"]) == set(results["head"])

        finally:
            _remove_worktree(repo_root, head_wt)
    finally:
        _remove_worktree(repo_root, base_wt)
