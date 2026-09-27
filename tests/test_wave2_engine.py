"""Wave 2 P1 engine tests: H1 (user's python), H2 (interpreter & src/ layout), A5 (prior-report linking)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bobthereviewer.cli import main
from bobthereviewer.contracts import validate_evidence
from bobthereviewer.executor import (
    BOOTSTRAP_PATH,
    CaseExecutionResult,
    RepeatedRunResult,
    _display_interpreter,
    _has_src_package,
    resolve_interpreter,
    run_case,
)
from bobthereviewer.pipeline import ProbeSpec, run_analysis_pipeline
from bobthereviewer.probe_runner import _case_status
from bobthereviewer.report import render_markdown
from bobthereviewer.test_runner import _run_pytest, parse_junit_xml
from tests.test_setup_cli import commit_files, init_repo


# ===========================================================================
# Task H1: Tests and probes run in user's own Python
# ===========================================================================

def test_probe_command_uses_bootstrap_file_path(tmp_path):
    """The probe execution invokes _bootstrap.py by file path, not -m module."""
    called_cmd = []

    def mock_run(cmd, *args, **kwargs):
        called_cmd.extend(cmd)
        return subprocess_result(0, json.dumps({"ok": True, "value": 42}))

    class subprocess_result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout.encode()
            self.stderr = b""

    with patch("subprocess.run", side_effect=mock_run):
        res = run_case(str(tmp_path), sys.executable, "dummy.target", {"id": "c1", "args": [], "kwargs": {}})

    assert res.status_kind == "ok"
    assert res.output == 42
    assert len(called_cmd) >= 2
    assert called_cmd[0] == sys.executable
    assert called_cmd[1] == BOOTSTRAP_PATH
    assert Path(called_cmd[1]).is_file()
    assert "-m" not in called_cmd


def test_parse_junit_xml_all_statuses(tmp_path):
    """Sample JUnit XML with pass, fail, error, skipped is parsed into right statuses."""
    sample_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.100">
    <testcase classname="tests.test_sample" name="test_ok" file="tests/test_sample.py" line="5" time="0.001" />
    <testcase classname="tests.test_sample" name="test_failing" file="tests/test_sample.py" line="10" time="0.002">
      <failure message="assert 1 == 2">AssertionError: assert 1 == 2 in {tmp_path}</failure>
    </testcase>
    <testcase classname="tests.test_sample" name="test_erroring" file="tests/test_sample.py" line="15" time="0.003">
      <error message="fixture error">RuntimeError: boom in {tmp_path}</error>
    </testcase>
    <testcase classname="tests.test_sample" name="test_skipped" file="tests/test_sample.py" line="20" time="0.001">
      <skipped type="pytest.skip" message="feature not supported">skipping this test</skipped>
    </testcase>
  </testsuite>
</testsuites>
"""
    results = parse_junit_xml(sample_xml, worktree_path=str(tmp_path), test_files=["tests/test_sample.py"])

    assert results["tests/test_sample.py::test_ok"]["status"] == "pass"
    assert results["tests/test_sample.py::test_ok"]["message"] is None

    assert results["tests/test_sample.py::test_failing"]["status"] == "fail"
    assert "assert 1 == 2" in results["tests/test_sample.py::test_failing"]["message"]
    # Absolute paths must be sanitized
    assert str(tmp_path) not in results["tests/test_sample.py::test_failing"]["message"]

    assert results["tests/test_sample.py::test_erroring"]["status"] == "error"
    assert "fixture error" in results["tests/test_sample.py::test_erroring"]["message"]
    assert str(tmp_path) not in results["tests/test_sample.py::test_erroring"]["message"]

    assert results["tests/test_sample.py::test_skipped"]["status"] == "error"
    assert "skipped" in results["tests/test_sample.py::test_skipped"]["message"].lower()


def test_missing_pytest_produces_error_entry(tmp_path):
    """When interpreter does not have pytest, _run_pytest produces a clear <pytest> error entry."""
    # Use a dummy non-existent interpreter path
    fake_python = tmp_path / "bin" / "python_no_pytest"
    results = _run_pytest(str(tmp_path), str(fake_python), ["tests/test_a.py"], 10)

    assert "<pytest>" in results
    assert results["<pytest>"]["status"] == "error"
    assert "pytest is not installed in" in results["<pytest>"]["message"]
    # Must not contain absolute path
    assert str(tmp_path) not in results["<pytest>"]["message"]


def test_bootstrap_failure_is_inconclusive_bootstrap_error(tmp_path):
    """Bootstrap execution failure is reported as bootstrap_error, not timeout."""
    class DummyResult:
        first = CaseExecutionResult(
            output={"exception": "BootstrapError", "message": "exit non-zero"},
            status_kind="bootstrap_error",
        )
        second = first
        is_nondeterministic = False

    status, reason = _case_status(DummyResult(), DummyResult())
    assert status == "inconclusive"
    assert reason == "bootstrap_error"


# ===========================================================================
# Task H2: Interpreter resolution + src/ layout
# ===========================================================================

def test_resolve_interpreter_steps(tmp_path, monkeypatch):
    """Test resolution order: config python_env -> .venv at repo_root -> $VIRTUAL_ENV -> tool's own Python."""
    repo = tmp_path / "myrepo"
    repo.mkdir()

    # Step 1: config python_env
    config_py = repo / "custom" / "bin" / "python"
    config_py.parent.mkdir(parents=True)
    config_py.touch()
    exe, disp, note = resolve_interpreter({"python_env": "custom/bin/python"}, repo_root=repo)
    assert Path(exe) == config_py.resolve()
    assert note is None

    # Step 2: .venv at repo root, even when current working directory is a subfolder
    subfolder = repo / "tests" / "nested"
    subfolder.mkdir(parents=True)
    monkeypatch.chdir(subfolder)

    venv_py = repo / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()

    exe, disp, note = resolve_interpreter({}, repo_root=repo)
    assert Path(exe) == venv_py.resolve()
    assert ".venv" in disp
    assert str(repo) not in disp  # Must be repo-relative
    assert note is None

    # Step 3: $VIRTUAL_ENV when .venv at repo root does not exist
    venv_py.unlink()
    env_dir = tmp_path / "external_venv"
    env_py = env_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
    env_py.parent.mkdir(parents=True)
    env_py.touch()
    monkeypatch.setenv("VIRTUAL_ENV", str(env_dir))

    exe, disp, note = resolve_interpreter({}, repo_root=repo)
    assert Path(exe) == env_py.resolve()
    assert note is None

    # Step 4: Fallback to tool's own interpreter with required note
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("BOBREVIEWER_PYTHON", raising=False)

    exe, disp, note = resolve_interpreter({}, repo_root=repo)
    assert Path(exe) == Path(sys.executable).resolve()
    assert note == "Ran with bobreviewer's own Python; install the project's dependencies there or create .venv"
    assert str(repo) not in disp


def test_src_layout_detection_and_probe_execution(tmp_path):
    """Probes can import packages located inside src/ layout."""
    repo = tmp_path / "shop_repo"
    init_repo(repo)
    commit_files(repo, {
        ".gitignore": ".bobreviewer/runs/\n",
        "src/shop/__init__.py": "",
        "src/shop/discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
        "src/shop/invoice.py": "from shop.discount import apply_discount\ndef total(p, r):\n    return apply_discount(p, r)\n",
    }, "base", tag="base")

    assert _has_src_package(repo) is True

    commit_files(repo, {
        "src/shop/discount.py": "import math\ndef apply_discount(p, r):\n    return math.floor(p * (1 - r) * 100) / 100\n",
        ".bobreviewer/probes/invoice.json": json.dumps({
            "schema_version": "1",
            "target": "shop.invoice.total",
            "cases": [{"id": "total-test", "args": [100.0, 0.00001], "kwargs": {}}],
        }),
    }, "differ", tag="differ")

    result = run_analysis_pipeline(repo, "base", "differ", execute=True)
    validate_evidence(result.evidence)

    case = result.evidence["probe_results"][0]["cases"][0]
    assert case["execution_status"] == "success"
    assert case["comparison_status"] == "differ"
    assert case["base_output"] == 100.0
    assert case["head_output"] == 99.99

    # Verify interpreter note in analysis limits
    notes = result.evidence["analysis_limits"]["notes"]
    assert any("Python interpreter:" in n for n in notes)
    for n in notes:
        assert str(repo) not in n


# ===========================================================================
# Task A5: --prior-report links differ -> match
# ===========================================================================

def test_prior_report_links_differ_to_match(tmp_path):
    """A rerun with --prior-report links probe results back to earlier differing run."""
    repo = tmp_path / "calc_repo"
    init_repo(repo)
    commit_files(repo, {
        ".gitignore": ".bobreviewer/runs/\n",
        "discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
    }, "base", tag="base")

    # Run 1: change to floor version, differing from base
    commit_files(repo, {
        "discount.py": "import math\ndef apply_discount(p, r):\n    return math.floor(p * (1 - r) * 100) / 100\n",
        ".bobreviewer/probes/discount.json": json.dumps({
            "schema_version": "1",
            "target": "discount.apply_discount",
            "cases": [{"id": "d-1", "args": [100.0, 0.00001], "kwargs": {}}],
        }),
    }, "floor_change", tag="differ_ref")

    out1 = tmp_path / "run1"
    res1 = run_analysis_pipeline(repo, "base", "differ_ref", execute=True, output_dir=out1)
    validate_evidence(res1.evidence)
    assert res1.evidence["probe_results"][0]["cases"][0]["comparison_status"] == "differ"

    # Run 2: restore fix (round version) and provide prior report
    commit_files(repo, {
        "discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
    }, "fix_change", tag="fix_ref")

    probe_spec = ProbeSpec(
        probe_files=[".bobreviewer/probes/discount.json"],
        prior_report_path=out1 / "evidence.json",
    )

    out2 = tmp_path / "run2"
    res2 = run_analysis_pipeline(repo, "base", "fix_ref", probe_spec=probe_spec, execute=True, output_dir=out2)
    validate_evidence(res2.evidence)

    assert res2.evidence["prior_run_id"] == res1.run_id
    probe_res = res2.evidence["probe_results"][0]
    assert probe_res["prior_difference_run_id"] == res1.run_id
    assert probe_res["cases"][0]["comparison_status"] == "match"

    # Report markdown mentions prior run
    md = render_markdown(res2.evidence)
    assert "previously differed in run" in md
    assert res1.run_id in md
