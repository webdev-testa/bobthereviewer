"""Tests for bobthereviewer.executor (ST 3 + ST 4)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from bobthereviewer.executor import (
    CaseExecutionResult,
    RepeatedRunResult,
    run_case,
    run_case_with_repeat_check,
)

PYTHON = sys.executable


def _make_module(tmpdir: Path, name: str, source: str) -> None:
    (tmpdir / f"{name}.py").write_text(textwrap.dedent(source))


# ---------------------------------------------------------------------------
# ST 3 — run_case
# ---------------------------------------------------------------------------

class TestRunCaseHappyPath:
    def test_simple_return(self, tmp_path):
        _make_module(tmp_path, "m", """
            def add(a, b): return a + b
        """)
        r = run_case(str(tmp_path), PYTHON, "m.add", {"args": [10, 5], "kwargs": {}})
        assert r.status_kind == "ok"
        assert r.output == 15

    def test_float_return(self, tmp_path):
        _make_module(tmp_path, "m", """
            def calc(x): return round(x * 0.9, 2)
        """)
        r = run_case(str(tmp_path), PYTHON, "m.calc", {"args": [100.0], "kwargs": {}})
        assert r.status_kind == "ok"
        assert r.output == 90.0

    def test_executed_at_is_set(self, tmp_path):
        _make_module(tmp_path, "m", """
            def f(): return 1
        """)
        r = run_case(str(tmp_path), PYTHON, "m.f", {"args": [], "kwargs": {}})
        assert r.executed_at  # non-empty ISO string


class TestRunCaseImportError:
    def test_missing_module(self, tmp_path):
        r = run_case(str(tmp_path), PYTHON, "no_such_module.func", {"args": [], "kwargs": {}})
        assert r.status_kind == "import_error"
        assert isinstance(r.output, dict)
        assert "exception" in r.output

    def test_broken_transitive_import(self, tmp_path):
        _make_module(tmp_path, "bad", "import _module_that_does_not_exist\ndef f(): pass")
        r = run_case(str(tmp_path), PYTHON, "bad.f", {"args": [], "kwargs": {}})
        assert r.status_kind == "import_error"


class TestRunCaseCallError:
    def test_exception_in_function(self, tmp_path):
        _make_module(tmp_path, "m", """
            def boom(): raise ValueError("test error")
        """)
        r = run_case(str(tmp_path), PYTHON, "m.boom", {"args": [], "kwargs": {}})
        assert r.status_kind == "call_error"
        assert r.output["exception"] == "ValueError"
        assert "test error" in r.output["message"]

    def test_non_serialisable_return(self, tmp_path):
        _make_module(tmp_path, "m", """
            def f(): return object()
        """)
        r = run_case(str(tmp_path), PYTHON, "m.f", {"args": [], "kwargs": {}})
        assert r.status_kind == "call_error"
        assert "JSON-serialisable" in r.output["message"]


class TestRunCaseTimeout:
    def test_timeout(self, tmp_path):
        _make_module(tmp_path, "m", """
            import time
            def slow(): time.sleep(60)
        """)
        r = run_case(str(tmp_path), PYTHON, "m.slow", {"args": [], "kwargs": {}}, timeout_seconds=1)
        assert r.status_kind == "timeout"
        assert r.output is None


# ---------------------------------------------------------------------------
# ST 4 — run_case_with_repeat_check
# ---------------------------------------------------------------------------

class TestRepeatCheck:
    def test_deterministic_function(self, tmp_path):
        _make_module(tmp_path, "m", """
            def f(): return 42
        """)
        result = run_case_with_repeat_check(str(tmp_path), PYTHON, "m.f", {"args": [], "kwargs": {}})
        assert isinstance(result, RepeatedRunResult)
        assert result.is_nondeterministic is False
        assert result.first.output == 42
        assert result.second.output == 42

    def test_nondeterministic_function(self, tmp_path):
        _make_module(tmp_path, "m", """
            import random
            def f(): return random.random()
        """)
        # Run many times if needed; random() almost never returns the same value twice
        # Run up to 10 attempts before failing the test
        detected = False
        for _ in range(10):
            result = run_case_with_repeat_check(str(tmp_path), PYTHON, "m.f", {"args": [], "kwargs": {}})
            if result.is_nondeterministic:
                detected = True
                break
        assert detected, "nondeterminism was never detected in 10 attempts"

    def test_import_error_skips_second_run(self, tmp_path):
        result = run_case_with_repeat_check(
            str(tmp_path), PYTHON, "no_such_module.f", {"args": [], "kwargs": {}}
        )
        # second should be the same object reference as first (skipped)
        assert result.first is result.second
        assert result.is_nondeterministic is False

    def test_timeout_skips_second_run(self, tmp_path):
        _make_module(tmp_path, "m", """
            import time
            def slow(): time.sleep(60)
        """)
        result = run_case_with_repeat_check(
            str(tmp_path), PYTHON, "m.slow", {"args": [], "kwargs": {}}, timeout_seconds=1
        )
        assert result.first.status_kind == "timeout"
        assert result.first is result.second
        assert result.is_nondeterministic is False


def test_configured_venv_python_is_not_resolved_through_its_symlink(tmp_path):
    """A venv's bin/python links to the base Python; resolving it hides the venv's packages."""
    import os
    from bobthereviewer.executor import resolve_interpreter

    link = tmp_path / ".venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(sys.executable, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this system")
    python_exe, _, _ = resolve_interpreter({"python_env": ".venv/bin/python"}, tmp_path)
    assert Path(python_exe) == tmp_path.resolve() / ".venv" / "bin" / "python"
