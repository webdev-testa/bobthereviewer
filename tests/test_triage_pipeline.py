"""
Tests for bobthereviewer.triage and bobthereviewer.pipeline — Slice 4.

Triage tests use lightweight directory mocks (no git).
Pipeline tests use temporary git repos.
"""

import json
import subprocess
from pathlib import Path

import pytest

from bobthereviewer.triage import TriageResult, classify
from bobthereviewer.pipeline import (
    PipelineResult,
    ProbeSpec,
    run_analysis_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)


def commit_files(repo: Path, files: dict[str, str], message: str, tag: str | None = None) -> str:
    for rel_path, content in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        _git(["add", rel_path], cwd=repo)
    _git(["commit", "-m", message], cwd=repo)
    sha = _git(["rev-parse", "HEAD"], cwd=repo)
    if tag:
        _git(["tag", tag], cwd=repo)
    return sha


def make_worktrees(tmp_path: Path, base: dict, head: dict):
    """Lightweight worktree pair (plain dirs, no git) for triage unit tests."""
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    for files, root in ((base, base_dir), (head, head_dir)):
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return base_dir, head_dir


# ---------------------------------------------------------------------------
# Triage — docs-only
# ---------------------------------------------------------------------------

def test_triage_docs_only(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify(["README.md", "CHANGELOG.rst"], base, head)
    assert result.category == "docs-only"
    assert result.skipped is True
    assert result.skip_reason is not None


def test_triage_docs_only_force_run(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify(["README.md"], base, head, force_run=True)
    assert result.category == "docs-only"
    assert result.skipped is False


def test_triage_docs_with_python_is_code(tmp_path):
    """A diff containing any Python file must not be docs-only."""
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n"},
        {"mod.py": "def f():\n    return 2\n"},
    )
    result = classify(["README.md", "mod.py"], base, head)
    assert result.category == "code"
    assert result.skipped is False


def test_triage_unknown_extension_is_code(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify(["data.csv"], base, head)
    assert result.category == "code"


# ---------------------------------------------------------------------------
# Triage — config-deps
# ---------------------------------------------------------------------------

def test_triage_config_deps_pyproject(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify(["pyproject.toml"], base, head)
    assert result.category == "config-deps"
    assert result.skipped is False


def test_triage_config_deps_requirements(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify(["requirements.txt", "requirements-dev.txt"], base, head)
    assert result.category == "config-deps"


def test_triage_config_deps_with_python_is_code(tmp_path):
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n"},
        {"mod.py": "def f():\n    return 2\n"},
    )
    result = classify(["pyproject.toml", "mod.py"], base, head)
    assert result.category == "code"


# ---------------------------------------------------------------------------
# Triage — tests-only
# ---------------------------------------------------------------------------

def test_triage_tests_only(tmp_path):
    base, head = make_worktrees(tmp_path,
        {"tests/test_foo.py": "def test_x():\n    pass\n"},
        {"tests/test_foo.py": "def test_x():\n    assert True\n"},
    )
    result = classify(["tests/test_foo.py"], base, head)
    assert result.category == "tests-only"
    assert result.skipped is False


def test_triage_tests_with_production_code_is_code(tmp_path):
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n",
         "tests/test_foo.py": "def test_x():\n    pass\n"},
        {"mod.py": "def f():\n    return 2\n",
         "tests/test_foo.py": "def test_x():\n    assert True\n"},
    )
    result = classify(["mod.py", "tests/test_foo.py"], base, head)
    assert result.category == "code"


# ---------------------------------------------------------------------------
# Triage — no-semantic-change
# ---------------------------------------------------------------------------

def test_triage_no_semantic_change_comment_only(tmp_path):
    """Comment-only Python change must classify as no-semantic-change."""
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    # old\n    return 1\n"},
        {"mod.py": "def f():\n    # new\n    return 1\n"},
    )
    result = classify(["mod.py"], base, head)
    assert result.category == "no-semantic-change"
    assert result.skipped is False


def test_triage_no_semantic_change_whitespace_only(tmp_path):
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n"},
        {"mod.py": "def f():\n    return 1\n\n\n"},
    )
    result = classify(["mod.py"], base, head)
    assert result.category == "no-semantic-change"


def test_triage_parse_failure_is_code(tmp_path):
    """A file that fails to parse must not become proof of no-semantic-change."""
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n"},
        {"mod.py": "def f(:\n    syntax error\n"},
    )
    result = classify(["mod.py"], base, head)
    assert result.category == "code"


def test_triage_no_semantic_change_with_unknown_file_is_code(tmp_path):
    """Unknown non-doc non-cfg file must prevent no-semantic-change classification."""
    base, head = make_worktrees(tmp_path,
        {"mod.py": "def f():\n    return 1\n"},
        {"mod.py": "def f():\n    return 1\n"},
    )
    result = classify(["mod.py", "data.csv"], base, head)
    assert result.category == "code"


# ---------------------------------------------------------------------------
# Triage — code
# ---------------------------------------------------------------------------

def test_triage_code_changed_python(tmp_path):
    base, head = make_worktrees(tmp_path,
        {"discount.py": "def apply_discount(p, r):\n    return p - p * r\n"},
        {"discount.py": "def apply_discount(p, r):\n    return round(p - p * r, 2)\n"},
    )
    result = classify(["discount.py"], base, head)
    assert result.category == "code"
    assert result.skipped is False


def test_triage_empty_changed_files(tmp_path):
    base, head = make_worktrees(tmp_path, {}, {})
    result = classify([], base, head)
    assert result.category == "no-semantic-change"


# ---------------------------------------------------------------------------
# Pipeline — analysis-only (execute=False)
# ---------------------------------------------------------------------------

def test_pipeline_analysis_only(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return p - p * r\n",
         "invoice.py": "from discount import apply_discount\ndef calc(q, p):\n    return apply_discount(q * p, 0.1)\n"},
        "base", tag="base")
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return round(p - p * r, 2)\n"},
        "head", tag="head")

    result = run_analysis_pipeline(
        repo_dir=repo,
        base_ref="base",
        head_ref="head",
        execute=False,
    )

    ev = result.evidence
    assert ev["schema_version"] == "1"
    assert ev["triage"]["category"] == "code"
    assert ev["triage"]["skipped"] is False
    assert len(ev["changed_functions"]) == 1
    assert ev["changed_functions"][0]["symbol"] == "discount.apply_discount"
    # Analysis-only: execution fields empty
    assert ev["probe_results"] == []
    assert ev["test_results"] == {"base": {}, "head": {}}


def test_pipeline_analysis_only_caller_outside_diff(tmp_path):
    """The core milestone: caller outside diff appears with file and line."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return p - p * r\n",
         "invoice.py": "from discount import apply_discount\ndef calc(q, p):\n    return apply_discount(q * p, 0.1)\n"},
        "base", tag="base")
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return round(p - p * r, 2)\n"},
        "head", tag="head")

    result = run_analysis_pipeline(repo_dir=repo, base_ref="base", head_ref="head", execute=False)

    cf = result.evidence["changed_functions"][0]
    outside_callers = [c for c in cf["callers"] if not c["in_diff"]]
    assert outside_callers, "no caller outside the diff found"
    c = outside_callers[0]
    assert c["file_path"] == "invoice.py"
    assert c["line"] > 0
    assert c["resolution"] == "resolved"


def test_pipeline_run_id_stable(tmp_path):
    """A pre-allocated run_id must appear in the evidence unchanged."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    fixed_id = "12345678-0000-0000-0000-000000000000"
    result = run_analysis_pipeline(
        repo_dir=repo, base_ref="base", head_ref="head",
        run_id=fixed_id, execute=False,
    )
    assert result.evidence["run_id"] == fixed_id
    assert result.run_id == fixed_id


def test_pipeline_docs_only_skips_execution(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "old docs", "mod.py": "def f():\n    pass\n"}, "base", tag="base")
    commit_files(repo, {"README.md": "new docs"}, "head", tag="head")

    result = run_analysis_pipeline(repo_dir=repo, base_ref="base", head_ref="head")
    ev = result.evidence
    assert ev["triage"]["category"] == "docs-only"
    assert ev["triage"]["skipped"] is True
    assert ev["triage"]["skip_reason"] is not None


def test_pipeline_docs_only_force_run(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "old"}, "base", tag="base")
    commit_files(repo, {"README.md": "new"}, "head", tag="head")

    result = run_analysis_pipeline(
        repo_dir=repo, base_ref="base", head_ref="head",
        force_run=True,
    )
    assert result.evidence["triage"]["skipped"] is False


def test_pipeline_writes_evidence_json(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    out_dir = tmp_path / "out"
    result = run_analysis_pipeline(
        repo_dir=repo, base_ref="base", head_ref="head",
        execute=False, output_dir=out_dir,
    )
    assert result.output_path is not None
    assert result.output_path.exists()
    written = json.loads(result.output_path.read_text())
    assert written["run_id"] == result.run_id


def test_pipeline_evidence_validates_against_schema(tmp_path):
    """Pipeline output must pass validate_evidence without raising."""
    from bobthereviewer.contracts import validate_evidence
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    result = run_analysis_pipeline(repo_dir=repo, base_ref="base", head_ref="head", execute=False)
    validate_evidence(result.evidence)  # must not raise


def test_pipeline_progress_callback_receives_events(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    events = []
    def cb(step, status, message):
        events.append((step, status))

    run_analysis_pipeline(
        repo_dir=repo, base_ref="base", head_ref="head",
        execute=False, callback=cb,
    )

    steps_seen = [s for s, _ in events]
    assert "triage" in steps_seen
    assert "analyze" in steps_seen
    assert "done" in steps_seen


def test_pipeline_no_absolute_paths_in_evidence(tmp_path):
    """Evidence produced by the pipeline must contain no absolute paths."""
    from bobthereviewer.contracts import ContractError, validate_evidence
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo,
        {"mod.py": "def f():\n    return 1\n",
         "caller.py": "from mod import f\ndef g():\n    return f()\n"},
        "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    result = run_analysis_pipeline(repo_dir=repo, base_ref="base", head_ref="head", execute=False)
    # validate_evidence already rejects absolute paths — if this passes, we're good
    validate_evidence(result.evidence)
