"""
Tests for bobreviewer.probe_runner (ST 6).

Unit tests use temp directories with minimal fixture functions.
The integration test (marked with pytest.mark.integration) uses the
demo sample project tags and verifies the 100.0 → 99.99 scenario.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Callable

import pytest

from bobreviewer.probe_runner import run_probes
from bobreviewer.progress import make_emitter

PYTHON = sys.executable


def _noop_emit(step: str, status: str, message: str) -> None:
    pass


def _make_triage(skipped: bool = False, category: str = "code") -> dict:
    return {
        "category": category,
        "skipped": skipped,
        "skip_reason": "docs-only diff" if skipped else None,
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


def _write_probe(worktree: Path, rel_path: str, probe: dict) -> None:
    target = worktree / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(probe))


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestTriageSkip:
    def test_skipped_triage_returns_empty(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        # Add a base probe but mark triage as skipped
        _write_probe(base, ".bobreviewer/probes/p.json", {
            "schema_version": "1",
            "target": "m.f",
            "cases": [{"id": "c1", "args": [], "kwargs": {}}],
        })

        results, prior_run_id = run_probes(
            str(base), str(head), PYTHON,
            _make_triage(skipped=True),
            _noop_emit,
        )
        assert results == []
        assert prior_run_id is None

    def test_new_head_probe_runs_even_when_triage_skipped(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        # Head has a NEW probe — must run even when triage says skipped
        _write(head / "m.py", """
            def f(): return 42
        """)
        _write_probe(head, ".bobreviewer/probes/new.json", {
            "schema_version": "1",
            "target": "m.f",
            "cases": [{"id": "c1", "args": [], "kwargs": {}}],
        })

        results, _ = run_probes(
            str(base), str(head), PYTHON,
            _make_triage(skipped=True),
            _noop_emit,
        )
        assert len(results) == 1


class TestStatusAssignment:
    def _setup_probe(self, base: Path, head: Path, base_func: str, head_func: str) -> None:
        _write(base / "m.py", base_func)
        _write(head / "m.py", head_func)
        for wt in (base, head):
            _write_probe(wt, ".bobreviewer/probes/p.json", {
                "schema_version": "1",
                "target": "m.f",
                "cases": [{"id": "c1", "args": [], "kwargs": {}}],
            })

    def test_match(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        self._setup_probe(base, head, "def f(): return 42", "def f(): return 42")
        results, _ = run_probes(str(base), str(head), PYTHON, _make_triage(), _noop_emit)
        assert results[0]["cases"][0]["status"] == "match"

    def test_differ(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        self._setup_probe(base, head, "def f(): return 1", "def f(): return 2")
        results, _ = run_probes(str(base), str(head), PYTHON, _make_triage(), _noop_emit)
        assert results[0]["cases"][0]["status"] == "differ"
        assert results[0]["cases"][0]["base_output"] == 1
        assert results[0]["cases"][0]["head_output"] == 2

    def test_exception_both_sides_is_differ_not_match(self, tmp_path):
        """Matching exceptions on both sides must NOT produce status=match."""
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        func = "def f(): raise ValueError('same error')"
        self._setup_probe(base, head, func, func)
        results, _ = run_probes(str(base), str(head), PYTHON, _make_triage(), _noop_emit)
        assert results[0]["cases"][0]["status"] == "differ"

    def test_import_error_is_inconclusive(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        # No m.py in base — import_error on base side
        _write(head / "m.py", "def f(): return 1")
        for wt in (base, head):
            _write_probe(wt, ".bobreviewer/probes/p.json", {
                "schema_version": "1",
                "target": "m.f",
                "cases": [{"id": "c1", "args": [], "kwargs": {}}],
            })
        results, _ = run_probes(str(base), str(head), PYTHON, _make_triage(), _noop_emit)
        c = results[0]["cases"][0]
        assert c["status"] == "inconclusive"
        assert c["inconclusive_reason"] == "import_error"

    def test_required_evidence_fields_present(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        self._setup_probe(base, head, "def f(): return 1", "def f(): return 1")
        results, _ = run_probes(str(base), str(head), PYTHON, _make_triage(), _noop_emit)
        r = results[0]
        assert "probe_file" in r
        assert "probe_hash" in r
        assert "target" in r
        assert "prior_difference_run_id" in r
        c = r["cases"][0]
        for field in ("id", "args", "kwargs", "base_output", "head_output",
                      "status", "inconclusive_reason", "base_executed_at", "head_executed_at"):
            assert field in c, f"missing field: {field}"


class TestPriorReportLinking:
    def _make_prior_report(self, probe_file: str, probe_hash: str, run_id: str) -> dict:
        return {
            "run_id": run_id,
            "probe_results": [{
                "probe_file": probe_file,
                "probe_hash": probe_hash,
                "target": "m.f",
                "prior_difference_run_id": None,
                "cases": [{"id": "c1", "status": "differ"}],
            }],
        }

    def test_links_to_prior_differ(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        probe_content = json.dumps({
            "schema_version": "1", "target": "m.f",
            "cases": [{"id": "c1", "args": [], "kwargs": {}}],
        }).encode()
        probe_hash = __import__("hashlib").sha256(probe_content).hexdigest()

        for wt in (base, head):
            p = wt / ".bobreviewer" / "probes" / "p.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(probe_content)
            (wt / "m.py").write_text("def f(): return 42")

        prior = self._make_prior_report(".bobreviewer/probes/p.json", probe_hash, "prior-run-001")
        results, prior_run_id = run_probes(
            str(base), str(head), PYTHON, _make_triage(), _noop_emit,
            prior_report=prior,
        )
        assert prior_run_id == "prior-run-001"
        assert results[0]["prior_difference_run_id"] == "prior-run-001"

    def test_no_link_when_prior_was_match(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        probe_content = json.dumps({
            "schema_version": "1", "target": "m.f",
            "cases": [{"id": "c1", "args": [], "kwargs": {}}],
        }).encode()
        probe_hash = __import__("hashlib").sha256(probe_content).hexdigest()

        for wt in (base, head):
            p = wt / ".bobreviewer" / "probes" / "p.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(probe_content)
            (wt / "m.py").write_text("def f(): return 42")

        prior = {
            "run_id": "prior-run-002",
            "probe_results": [{
                "probe_file": ".bobreviewer/probes/p.json",
                "probe_hash": probe_hash,
                "target": "m.f",
                "prior_difference_run_id": None,
                "cases": [{"id": "c1", "status": "match"}],
            }],
        }
        results, _ = run_probes(
            str(base), str(head), PYTHON, _make_triage(), _noop_emit,
            prior_report=prior,
        )
        assert results[0]["prior_difference_run_id"] is None


# ---------------------------------------------------------------------------
# Integration test — requires demo Git tags
# ---------------------------------------------------------------------------

def _checkout_tag(repo_root: Path, tag: str, dest: Path) -> None:
    """Check out a specific tag into dest using git worktree."""
    import subprocess
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(dest), tag],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )


def _remove_worktree(repo_root: Path, dest: Path) -> None:
    import subprocess
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(dest)],
        cwd=str(repo_root),
        capture_output=True,
    )


@pytest.mark.integration
def test_rounding_scenario_end_to_end(tmp_path):
    """
    Run the demo-base vs demo-rounding-change probe and confirm:
      - base_output == 100.0
      - head_output == 99.99
      - status == "differ"
    """
    repo_root = Path(__file__).parent.parent
    base_wt = tmp_path / "base_wt"
    head_wt = tmp_path / "head_wt"

    _checkout_tag(repo_root, "demo-base", base_wt)
    try:
        _checkout_tag(repo_root, "demo-rounding-change", head_wt)
        try:
            base_worktree = str(base_wt / "demo" / "sample_project")
            head_worktree = str(head_wt / "demo" / "sample_project")

            results, prior_run_id = run_probes(
                base_worktree, head_worktree, PYTHON,
                _make_triage(),
                _noop_emit,
            )

            assert len(results) == 1, f"Expected 1 probe result, got {len(results)}"
            cases = results[0]["cases"]
            assert len(cases) == 1

            c = cases[0]
            assert c["id"] == "invoice-small-discount"
            assert c["base_output"] == 100.0, f"Expected base=100.0, got {c['base_output']}"
            assert c["head_output"] == 99.99, f"Expected head=99.99, got {c['head_output']}"
            assert c["status"] == "differ", f"Expected status=differ, got {c['status']}"
            assert c["inconclusive_reason"] is None
            assert prior_run_id is None

        finally:
            _remove_worktree(repo_root, head_wt)
    finally:
        _remove_worktree(repo_root, base_wt)
