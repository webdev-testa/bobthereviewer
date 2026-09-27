"""
bobthereviewer.probe_runner
========================
Ties together the probe selector, executor, and nondeterminism check to
produce the ``probe_results[]`` list that Lane 1 writes into ``evidence.json``.

Key rules (from spec):
  - If triage says skipped AND there are no new head-only probes → skip all.
  - Newly added probes are never grounds for skipping; they always run.
  - Exception equality is NOT a match (spec: matching exceptions on both
    sides are not treated as a match — they remain ``differ``).
  - Status precedence: nondeterminism > import_error > timeout > match/differ.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from bobthereviewer.executor import run_case_with_repeat_check
from bobthereviewer.probe_selector import SelectedProbe, select_probes


def _is_exception_record(value: Any) -> bool:
    """Return True if value is the structured exception output format."""
    return (
        isinstance(value, dict)
        and "exception" in value
        and "message" in value
    )


def _case_status(
    base_result,   # RepeatedRunResult
    head_result,   # RepeatedRunResult
) -> tuple[str, Optional[str]]:
    """
    Determine (status, inconclusive_reason) for one case.

    Precedence:
      1. nondeterminism on either side → inconclusive / nondeterminism_detected
      2. import_error on either side   → inconclusive / import_error
      3. timeout on either side        → inconclusive / timeout
      4. both ok, same output          → match
         (but matching exception records are differ, not match)
      5. otherwise                     → differ
    """
    base_first = base_result.first
    head_first = head_result.first

    if base_result.is_nondeterministic or head_result.is_nondeterministic:
        return "inconclusive", "nondeterminism_detected"

    if base_first.status_kind == "import_error" or head_first.status_kind == "import_error":
        return "inconclusive", "import_error"

    if base_first.status_kind == "timeout" or head_first.status_kind == "timeout":
        return "inconclusive", "timeout"

    base_out = base_first.output
    head_out = head_first.output

    # Matching exception records are explicitly NOT a match per spec
    if _is_exception_record(base_out) and _is_exception_record(head_out):
        return "differ", None

    if base_out == head_out:
        return "match", None

    return "differ", None


def run_probes(
    base_worktree_path: str,
    head_worktree_path: str,
    python_exe: str,
    triage: dict,
    emit: Callable[[str, str, str], None],
    timeout_seconds: int = 10,
    src_layout: bool = False,
    prior_report: Optional[dict] = None,
) -> tuple[list[dict], Optional[str]]:
    """
    Run all selected probes against both worktrees and return
    ``(probe_results_list, prior_run_id)``.

    Parameters
    ----------
    base_worktree_path, head_worktree_path :
        Absolute paths to worktree checkouts (supplied by Lane 1).
    python_exe :
        Resolved interpreter path from config.json.
    triage :
        The triage dict from Lane 1.  If ``triage["skipped"]`` is True AND
        there are no head-only new probes, execution is skipped entirely.
    emit :
        Progress event callable from ``progress.make_emitter``.
    prior_report :
        Optional earlier evidence.json dict for linking differ→match.
    """
    probes = select_probes(base_worktree_path, head_worktree_path)

    # Triage skip: skip only when no new probes exist on head
    triage_skipped = triage.get("skipped", False)
    has_new_head_probes = any(p.source == "head_new" for p in probes)

    if triage_skipped and not has_new_head_probes:
        skip_reason = triage.get("skip_reason") or "docs-only diff"
        emit("probe_base", "completed", f"skipped — {skip_reason}")
        emit("probe_head", "completed", f"skipped — {skip_reason}")
        return [], None

    # Build prior-report lookup: (probe_file, probe_hash) → prior case status
    prior_differ_lookup: dict[tuple[str, str], str] = {}  # key → prior run_id
    prior_run_id: Optional[str] = None
    if prior_report:
        prior_run_id = prior_report.get("run_id")
        for pr in prior_report.get("probe_results", []):
            key = (pr["probe_file"], pr["probe_hash"])
            # Any case with status "differ" marks this probe as having differed
            for c in pr.get("cases", []):
                if c.get("status") == "differ":
                    prior_differ_lookup[key] = prior_run_id
                    break

    probe_results: list[dict] = []

    for selected_probe in probes:
        probe_json = json.loads(selected_probe.probe_bytes)
        target: str = probe_json["target"]
        cases: list[dict] = probe_json["cases"]

        # Determine prior_difference_run_id for this probe
        lookup_key = (selected_probe.probe_path, selected_probe.probe_hash)
        this_prior_differ_run_id = prior_differ_lookup.get(lookup_key)

        case_results: list[dict] = []

        emit("probe_base", "started", f"{selected_probe.probe_path} — base side")
        for case in cases:
            base_rr = run_case_with_repeat_check(
                base_worktree_path, python_exe, target, case,
                timeout_seconds, src_layout,
            )
            head_rr = run_case_with_repeat_check(
                head_worktree_path, python_exe, target, case,
                timeout_seconds, src_layout,
            )

            status, inconclusive_reason = _case_status(base_rr, head_rr)

            case_results.append({
                "id":                  case["id"],
                "args":                case.get("args", []),
                "kwargs":              case.get("kwargs", {}),
                "base_output":         base_rr.first.output,
                "head_output":         head_rr.first.output,
                "status":              status,
                "inconclusive_reason": inconclusive_reason,
                "base_executed_at":    base_rr.first.executed_at,
                "head_executed_at":    head_rr.first.executed_at,
            })
        emit("probe_base", "completed", f"{selected_probe.probe_path} — base done")
        emit("probe_head", "completed", f"{selected_probe.probe_path} — head done")

        probe_results.append({
            "probe_file":              selected_probe.probe_path,
            "probe_hash":              selected_probe.probe_hash,
            "target":                  target,
            "prior_difference_run_id": this_prior_differ_run_id,
            "cases":                   case_results,
        })

    return probe_results, prior_run_id
