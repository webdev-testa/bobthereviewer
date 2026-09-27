"""
bobthereviewer.executor
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
from pathlib import Path
from typing import Any, Callable


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
            [python_exe, "-m", "bobthereviewer._bootstrap"],
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


# ---------------------------------------------------------------------------
# Lane 1 pipeline integration — `pipeline._call_executor` calls `executor.run`
# ---------------------------------------------------------------------------

def _resolve_interpreter(config: dict | None) -> str:
    """The interpreter for the project under review, falling back to this process."""
    import configparser
    import os

    if isinstance(config, dict):
        configured = config.get("python_env") or config.get("python")
        if configured and Path(configured).exists():
            return str(configured)

    root = Path.cwd()
    for candidate in (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)

    # A configured interpreter may also be named by an env var or be this process.
    return os.environ.get("BOBREVIEWER_PYTHON") or sys.executable


def _triage_dict(triage: Any) -> dict:
    """Accept either a dict or a TriageResult dataclass from Lane 1."""
    if isinstance(triage, dict):
        return triage
    return {
        "category": getattr(triage, "category", ""),
        "skipped": bool(getattr(triage, "skipped", False)),
        "skip_reason": getattr(triage, "skip_reason", "") or "",
    }


def run(
    ctx: Any,
    analysis_result: Any = None,
    probe_spec: Any = None,
    triage: Any = None,
    run_id: str = "",
    callback: Callable[[str, str, str], None] | None = None,
    config: dict | None = None,
    prior_report: dict | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    src_layout: bool = False,
) -> Any:
    """Execute the frozen suite and the selected probes on both revisions.

    This is the integration point Lane 1's ``pipeline._call_executor`` expects: it returns an
    object with ``test_results``, ``probe_results``, ``frozen_suite_hash``,
    ``uncovered_callers`` and ``execution_notes``, which Lane 1 assigns onto its own
    ``ExecutionResult`` shape. Lane 2 owns the execution; Lane 1 owns the evidence assembly.

    Imported lazily to avoid a circular import with ``bobthereviewer.pipeline``.
    """
    from bobthereviewer.pipeline import ExecutionResult

    # Imported here, not at module level: probe_runner/test_runner import this module back
    # (`run_case_with_repeat_check`), so module-level imports create a cycle.
    from bobthereviewer.probe_runner import run_probes
    from bobthereviewer.test_runner import run_tests

    emit: Callable[[str, str, str], None] = callback or (lambda s, st, m: None)
    notes: list[str] = []

    triage_dict = _triage_dict(triage)
    base_path = str(ctx.base_path)
    head_path = str(ctx.head_path)
    python_exe = _resolve_interpreter(config)

    if triage_dict.get("skipped"):
        reason = triage_dict.get("skip_reason") or "docs-only diff"
        notes.append(f"Execution skipped by triage ({reason}); no behaviour was executed.")

    # Selected probe files: an explicit list wins, else every probe found by the selector.
    selected: list[str] = []
    if probe_spec is not None:
        selected = list(getattr(probe_spec, "probe_files", []) or [])
        if not selected and isinstance(probe_spec, dict):
            selected = list(probe_spec.get("probe_files", []) or [])

    test_results: dict = {"base": {}, "head": {}}
    frozen_suite_hash: str | None = None
    probe_results: list[dict] = []

    try:
        test_results, frozen_suite_hash = run_tests(
            base_path, head_path, python_exe, triage_dict, emit, timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 - execution failure is evidence, not a crash
        notes.append(f"Frozen test execution failed: {type(exc).__name__}: {exc}")

    try:
        if prior_report is not None:
            probe_results, _ = run_probes(
                base_path, head_path, python_exe, triage_dict, emit,
                timeout_seconds, src_layout, prior_report,
            )
        else:
            # `run_probes` accepts the report by keyword; omit it entirely when there is none so
            # the caller's default applies rather than an explicit None.
            probe_results, _ = run_probes(
                base_path, head_path, python_exe, triage_dict, emit, timeout_seconds, src_layout
            )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Probe execution failed: {type(exc).__name__}: {exc}")

    if selected:
        wanted = set(selected)
        kept = [p for p in probe_results if p.get("probe_file") in wanted]
        dropped = len(probe_results) - len(kept)
        if dropped:
            notes.append(f"Restricted to {len(kept)} requested probe file(s); {dropped} other(s) were not run.")
        probe_results = kept

    # Callers the impact analysis flagged that no executed probe covered.
    uncovered: list[str] = []
    try:
        probed_targets = {p.get("target") for p in probe_results if p.get("target")}
        for caller in (getattr(analysis_result, "uncovered_callers", None) or []):
            name = caller if isinstance(caller, str) else getattr(caller, "symbol", "")
            if name and name not in probed_targets:
                uncovered.append(name)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Could not compute uncovered callers: {type(exc).__name__}: {exc}")

    if not probe_results and not triage_dict.get("skipped"):
        notes.append("No probes were selected, so no behaviour claim is made from execution.")

    return ExecutionResult(
        test_results=test_results,
        probe_results=probe_results,
        frozen_suite_hash=frozen_suite_hash,
        uncovered_callers=uncovered,
        execution_notes=notes,
    )
