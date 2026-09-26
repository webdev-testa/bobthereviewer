"""
bobreviewer._bootstrap
======================
Runs inside a worktree subprocess.  Receives a JSON payload on stdin,
inserts the worktree root (and optionally src/) onto sys.path, imports the
target function, calls it, and writes a JSON result to stdout.

Input (stdin, one JSON object):
  {
    "target":       "<module.path.function_name>",
    "args":         [...],
    "kwargs":       {...},
    "worktree_root": "<absolute path>",
    "src_layout":    true | false
  }

Output (stdout, one JSON object):
  {"ok": true,  "value": <any JSON value>}
  {"ok": false, "kind": "import_error", "exception": "<type>", "message": "<str>"}
  {"ok": false, "kind": "call_error",   "exception": "<type>", "message": "<str>"}

Exit code 0 in all three cases above.
Exit code 1 only on infrastructure failure (bad stdin JSON, missing keys).

This module intentionally uses only the Python standard library so that it
can run inside a worktree subprocess that has not installed bobreviewer.
"""

import importlib
import json
import sys


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    # --- read and parse the payload -------------------------------------------
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        target: str = payload["target"]
        args: list = payload["args"]
        kwargs: dict = payload["kwargs"]
        worktree_root: str = payload["worktree_root"]
        src_layout: bool = payload.get("src_layout", False)
    except Exception as exc:
        # Infrastructure failure — cannot proceed.
        sys.stderr.write(f"bootstrap: bad input: {exc}\n")
        sys.exit(1)

    # --- configure sys.path ---------------------------------------------------
    sys.path.insert(0, worktree_root)
    if src_layout:
        import os
        sys.path.insert(1, os.path.join(worktree_root, "src"))

    # --- split target into module path and function name ---------------------
    if "." not in target:
        _write({
            "ok": False,
            "kind": "import_error",
            "exception": "ValueError",
            "message": f"target must be a dotted path, got: {target!r}",
        })
        return

    module_path, function_name = target.rsplit(".", 1)

    # --- import ---------------------------------------------------------------
    try:
        module = importlib.import_module(module_path)
    except (ImportError, ModuleNotFoundError) as exc:
        _write({
            "ok": False,
            "kind": "import_error",
            "exception": type(exc).__name__,
            "message": str(exc),
        })
        return

    # --- call -----------------------------------------------------------------
    try:
        func = getattr(module, function_name)
        result = func(*args, **kwargs)
    except Exception as exc:
        _write({
            "ok": False,
            "kind": "call_error",
            "exception": type(exc).__name__,
            "message": str(exc),
        })
        return

    # --- serialise return value -----------------------------------------------
    try:
        json.dumps(result)  # check serialisability without allocating output yet
    except (TypeError, ValueError):
        _write({
            "ok": False,
            "kind": "call_error",
            "exception": "TypeError",
            "message": "return value is not JSON-serialisable",
        })
        return

    _write({"ok": True, "value": result})


if __name__ == "__main__":
    main()
