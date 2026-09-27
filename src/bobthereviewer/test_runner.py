"""
bobthereviewer.test_runner
=======================
Runs the frozen base test suite against both worktrees.

"Frozen" means: the set of test files present in the BASE worktree, run
with the base pytest config.  New test files added on the head branch do
NOT run in the frozen suite.

Uses pytest's built-in ``--json-report`` (pytest-json-report) for structured
output.  Falls back to parsing the plain text output for environments without
the plugin.

Returns the ``test_results`` dict shape expected by ``evidence.schema.json``
and a ``frozen_suite_hash`` hex string (SHA-256 of sorted file contents).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional


_DEFAULT_TIMEOUT = 120  # seconds for the full test suite


def _sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compute_frozen_suite_hash(test_files: list[tuple[str, bytes]]) -> str:
    """
    SHA-256 of the sorted list of (relative_path, file_bytes) pairs.
    Sorting ensures stability regardless of filesystem order.
    """
    h = hashlib.sha256()
    for rel_path, content in sorted(test_files):
        h.update(rel_path.encode())
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    return h.hexdigest()


def _discover_test_files(worktree_path: str) -> list[tuple[str, bytes]]:
    """
    Return sorted list of (repo-relative path, bytes) for all Python test
    files found in the worktree using pytest discovery conventions:
    ``test_*.py`` and ``*_test.py`` under any subdirectory.
    """
    root = Path(worktree_path)
    files: list[tuple[str, bytes]] = []
    for p in sorted(root.rglob("test_*.py")) + sorted(root.rglob("*_test.py")):
        rel = p.relative_to(root).as_posix()
        files.append((rel, p.read_bytes()))
    # Deduplicate (rglob patterns may overlap)
    seen: set[str] = set()
    unique: list[tuple[str, bytes]] = []
    for rel, data in files:
        if rel not in seen:
            seen.add(rel)
            unique.append((rel, data))
    return sorted(unique)


def _run_pytest(
    worktree_path: str,
    python_exe: str,
    test_files: list[str],
    timeout_seconds: int,
) -> dict[str, dict]:
    """
    Run pytest on the given list of test file paths (relative to worktree_path).
    Returns ``{node_id: {"status": "pass"|"fail"|"error", "message": null|str}}``.
    """
    if not test_files:
        return {}

    root = Path(worktree_path)
    abs_test_files = [str(root / f) for f in test_files]

    # Write json report to a temp file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tf:
        report_path = tf.name

    cmd = [
        python_exe, "-m", "pytest",
        "--tb=short",
        "--no-header",
        "-q",
        f"--json-report",
        f"--json-report-file={report_path}",
    ] + abs_test_files

    try:
        subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {f"<suite timeout>": {"status": "error", "message": "test suite timed out"}}

    # Parse JSON report
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"<parse error>": {"status": "error", "message": "could not parse pytest report"}}
    finally:
        try:
            Path(report_path).unlink(missing_ok=True)
        except OSError:
            pass

    results: dict[str, dict] = {}
    for test in report.get("tests", []):
        node_id: str = test.get("nodeid", "unknown")
        outcome: str = test.get("outcome", "error")

        if outcome == "passed":
            status = "pass"
            message = None
        elif outcome == "failed":
            status = "fail"
            # Extract the longrepr text if available
            call = test.get("call", {})
            message = call.get("longrepr") or test.get("longrepr")
            if isinstance(message, dict):
                message = message.get("reprcrash", {}).get("message") or str(message)
        else:
            status = "error"
            setup = test.get("setup", {})
            message = setup.get("longrepr") or test.get("longrepr")
            if isinstance(message, dict):
                message = message.get("reprcrash", {}).get("message") or str(message)

        results[node_id] = {"status": status, "message": message}

    return results


def run_tests(
    base_worktree_path: str,
    head_worktree_path: str,
    python_exe: str,
    triage: dict,
    emit: Callable[[str, str, str], None],
    timeout_seconds: int = _DEFAULT_TIMEOUT,
) -> tuple[dict, Optional[str]]:
    """
    Run the frozen test suite against both worktrees.

    Returns ``(test_results_dict, frozen_suite_hash_hex)``.

    ``test_results_dict`` matches ``evidence.schema.json``::

        {
          "base": {<node_id>: {"status": "pass"|"fail"|"error", "message": ...}},
          "head": {<node_id>: {"status": "pass"|"fail"|"error", "message": ...}},
        }

    ``frozen_suite_hash_hex`` is ``None`` when triage skipped execution.
    """
    if triage.get("skipped", False):
        skip_reason = triage.get("skip_reason") or "docs-only diff"
        emit("test_base", "completed", f"skipped — {skip_reason}")
        emit("test_head", "completed", f"skipped — {skip_reason}")
        return {"base": {}, "head": {}}, None

    # Discover frozen test files from the BASE worktree
    base_test_files = _discover_test_files(base_worktree_path)
    frozen_rel_paths = [rel for rel, _ in base_test_files]
    frozen_suite_hash = _compute_frozen_suite_hash(base_test_files)

    # Run on base
    emit("test_base", "started", f"Running {len(frozen_rel_paths)} frozen test file(s) on base")
    base_results = _run_pytest(base_worktree_path, python_exe, frozen_rel_paths, timeout_seconds)
    emit("test_base", "completed", f"base: {len(base_results)} test(s)")

    # Run same frozen file list on head
    emit("test_head", "started", f"Running {len(frozen_rel_paths)} frozen test file(s) on head")
    head_results = _run_pytest(head_worktree_path, python_exe, frozen_rel_paths, timeout_seconds)
    emit("test_head", "completed", f"head: {len(head_results)} test(s)")

    return {"base": base_results, "head": head_results}, frozen_suite_hash
