"""Unit tests for bobreviewer._bootstrap (invoked as a subprocess)."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


PYTHON = sys.executable


def _run_bootstrap(payload: dict) -> dict:
    """Invoke the bootstrap as a subprocess; return the parsed stdout JSON."""
    result = subprocess.run(
        [PYTHON, "-m", "bobreviewer._bootstrap"],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, f"bootstrap exited non-zero:\n{result.stderr.decode()}"
    return json.loads(result.stdout.decode().strip())


def _make_fixture_module(tmpdir: Path, name: str, source: str) -> None:
    (tmpdir / f"{name}.py").write_text(textwrap.dedent(source))


class TestBootstrapHappyPath:
    def test_returns_value(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def add(a, b):
                return a + b
        """)
        out = _run_bootstrap({
            "target": "mymod.add",
            "args": [1, 2],
            "kwargs": {},
            "worktree_root": str(tmp_path),
            "src_layout": False,
        })
        assert out == {"ok": True, "value": 3}

    def test_returns_float(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def identity(x):
                return x
        """)
        out = _run_bootstrap({
            "target": "mymod.identity",
            "args": [99.99],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out == {"ok": True, "value": 99.99}

    def test_returns_null(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def noop():
                return None
        """)
        out = _run_bootstrap({
            "target": "mymod.noop",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out == {"ok": True, "value": None}

    def test_kwargs(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def greet(name="world"):
                return f"hello {name}"
        """)
        out = _run_bootstrap({
            "target": "mymod.greet",
            "args": [],
            "kwargs": {"name": "bob"},
            "worktree_root": str(tmp_path),
        })
        assert out == {"ok": True, "value": "hello bob"}

    def test_src_layout(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        _make_fixture_module(src_dir, "mymod", """
            def answer():
                return 42
        """)
        out = _run_bootstrap({
            "target": "mymod.answer",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
            "src_layout": True,
        })
        assert out == {"ok": True, "value": 42}


class TestBootstrapImportError:
    def test_missing_module(self, tmp_path):
        out = _run_bootstrap({
            "target": "nonexistent_module_xyz.func",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out["ok"] is False
        assert out["kind"] == "import_error"
        assert "exception" in out
        assert "message" in out

    def test_module_with_broken_import(self, tmp_path):
        _make_fixture_module(tmp_path, "broken", """
            import this_does_not_exist_xyz
            def func():
                return 1
        """)
        out = _run_bootstrap({
            "target": "broken.func",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out["ok"] is False
        assert out["kind"] == "import_error"

    def test_no_dot_in_target(self, tmp_path):
        out = _run_bootstrap({
            "target": "nodothere",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out["ok"] is False
        assert out["kind"] == "import_error"


class TestBootstrapCallError:
    def test_runtime_exception(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def boom():
                raise ValueError("oops")
        """)
        out = _run_bootstrap({
            "target": "mymod.boom",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out["ok"] is False
        assert out["kind"] == "call_error"
        assert out["exception"] == "ValueError"
        assert "oops" in out["message"]

    def test_non_serialisable_return(self, tmp_path):
        _make_fixture_module(tmp_path, "mymod", """
            def func():
                return object()
        """)
        out = _run_bootstrap({
            "target": "mymod.func",
            "args": [],
            "kwargs": {},
            "worktree_root": str(tmp_path),
        })
        assert out["ok"] is False
        assert out["kind"] == "call_error"
        assert "JSON-serialisable" in out["message"]


class TestBootstrapInfraFailure:
    def test_bad_stdin_exits_nonzero(self):
        result = subprocess.run(
            [PYTHON, "-m", "bobreviewer._bootstrap"],
            input=b"not json at all",
            capture_output=True,
            timeout=10,
        )
        assert result.returncode != 0
