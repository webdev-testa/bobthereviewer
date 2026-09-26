"""
bobreviewer.executor
====================
Host-side wrapper that spawns the bootstrap subprocess for a single probe
case and interprets the result.  Also provides the repeated-run nondeterminism
check (ST 4).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_DEFAULT_TIMEOUT = 10  # seconds per case execution


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class CaseExecutionResult:
    """Result of a single probe case execution in one worktree."""

    # Any JSON value, or {"exception": ..., "message": ...}, or None on timeout
    output: Any
    # "ok" | "import_error" | "call_error" | "timeout"
    status_kind: str
    executed_at: str = field(default_factory=_now_iso)


@dataclass
class RepeatedRunResult:
    """Two consecutive executions of the same case on the same worktree."""

    first: CaseExecutionResult
    second: CaseExecutionResult
    is_nondeterministic: bool


def run_case(
    worktree_path: str,
    python_exe: str,
    target: str,
    case: dict,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    src_layout: bool = False,
) -> CaseExecutionResult:
    """
    Run one probe case inside a subprocess and return a CaseExecutionResult.

    Parameters
    ----------
    worktree_path : str
        Absolute path to the worktree checkout.
    python_exe : str
        Absolute path to the Python interpreter to use (from config.json
        ``python_env``, resolved by Lane 1).
    target : str
        Dotted function name, e.g. ``invoice.calculate_invoice``.
    case : dict
        A probe case dict with keys ``id``, ``args``, ``kwargs``.
    timeout_seconds : int
        Wall-clock timeout for the subprocess.
    src_layout : bool
        If True, also insert ``<worktree_path>/src`` onto sys.path.
    """
    payload = {
        "target": target,
        "args": case.get("args", []),
        "kwargs": case.get("kwargs", {}),
        "worktree_root": worktree_path,
        "src_layout": src_layout,
    }

    executed_at = _now_iso()

    try:
        proc = subprocess.run(
            [python_exe, "-m", "bobreviewer._bootstrap"],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return CaseExecutionResult(
            output=None,
            status_kind="timeout",
            executed_at=executed_at,
        )
    except Exception as exc:
        # Any other subprocess-level error (e.g. executable not found)
        return CaseExecutionResult(
            output={"exception": type(exc).__name__, "message": str(exc)},
            status_kind="timeout",
            executed_at=executed_at,
        )

    # Parse bootstrap stdout
    stdout = proc.stdout.decode(errors="replace").strip()
    if proc.returncode != 0 or not stdout:
        stderr = proc.stderr.decode(errors="replace").strip()
        return CaseExecutionResult(
            output={"exception": "BootstrapError", "message": stderr or "bootstrap exited non-zero"},
            status_kind="timeout",
            executed_at=executed_at,
        )

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return CaseExecutionResult(
            output={"exception": "BootstrapError", "message": f"unparseable stdout: {stdout[:200]}"},
            status_kind="timeout",
            executed_at=executed_at,
        )

    if result.get("ok") is True:
        return CaseExecutionResult(
            output=result["value"],
            status_kind="ok",
            executed_at=executed_at,
        )

    kind = result.get("kind", "call_error")
    exc_record = {
        "exception": result.get("exception", "UnknownError"),
        "message": result.get("message", ""),
    }
    return CaseExecutionResult(
        output=exc_record,
        status_kind=kind,  # "import_error" or "call_error"
        executed_at=executed_at,
    )


# ---------------------------------------------------------------------------
# ST 4 — nondeterminism check
# ---------------------------------------------------------------------------

def run_case_with_repeat_check(
    worktree_path: str,
    python_exe: str,
    target: str,
    case: dict,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    src_layout: bool = False,
) -> RepeatedRunResult:
    """
    Run the case twice on the same worktree.  If the outputs differ,
    ``is_nondeterministic`` is set to True.

    Structural failures (timeout, import_error) are not repeated — they are
    returned as-is with ``is_nondeterministic=False``.
    """
    first = run_case(worktree_path, python_exe, target, case, timeout_seconds, src_layout)

    # Structural errors: no point repeating
    if first.status_kind in ("timeout", "import_error"):
        return RepeatedRunResult(first=first, second=first, is_nondeterministic=False)

    second = run_case(worktree_path, python_exe, target, case, timeout_seconds, src_layout)

    is_nondeterministic = first.output != second.output
    return RepeatedRunResult(first=first, second=second, is_nondeterministic=is_nondeterministic)
