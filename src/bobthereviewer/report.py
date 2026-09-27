"""
Markdown report renderer for bobthereviewer.

render_markdown(evidence: dict) -> str

Produces a GitHub-flavoured Markdown string suitable for PR comments
and terminal output. Reads evidence.json as a plain dict — does not
import any other bobreviewer module.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_output(value: Any) -> str:
    """Format a probe output value for display."""
    if isinstance(value, dict) and "exception" in value:
        return f"`{value['exception']}: {value.get('message', '')}`"
    return f"`{value!r}`"


def _decision_for(case_id: str, target: str, probe_hash: str, decisions: list[dict]) -> dict | None:
    """The head-revision decision matching this case, if the author has made one.

    Matched on symbol, case id and probe hash so a decision for a different probe, or for a
    probe whose bytes changed since, is never shown as if it applied here.
    """
    for record in decisions or []:
        if record.get("case_id") != case_id:
            continue
        if record.get("symbol") != target:
            continue
        recorded_hash = record.get("probe_hash")
        if recorded_hash and probe_hash and recorded_hash != probe_hash:
            continue
        return record
    return None


def _decision_cell(case_id: str, target: str, probe_hash: str, decisions: list[dict]) -> str:
    """The decision column for one differing case: the verdict, or a prompt for one."""
    record = _decision_for(case_id, target, probe_hash, decisions)
    if record is None:
        return "⚠️ No decision yet"
    verdict = (record.get("verdict") or "unresolved").capitalize()
    rationale = (record.get("rationale") or "").strip()
    return f"**{verdict}** — {rationale} (proposed — approved when merged)" if rationale \
        else f"**{verdict}** (proposed — approved when merged)"


def _status_label(status: str) -> str:
    return {
        "match":        "✅ Same on tested cases",
        "differ":       "⚠️ Behavior differs",
        "inconclusive": "❓ Inconclusive",
    }.get(status, status)


def _test_label(status: str) -> str:
    return {"pass": "✅ Pass", "fail": "❌ Fail", "error": "⚠️ Error"}.get(status, status)


def _triage_label(category: str) -> str:
    return {
        "code":               "Code change",
        "tests-only":         "Tests only",
        "docs-only":          "Docs only",
        "config-deps":        "Config / deps",
        "no-semantic-change": "No semantic change",
    }.get(category, category)


# ── main renderer ─────────────────────────────────────────────────────────────

def render_markdown(evidence: dict) -> str:  # noqa: C901 (complexity acceptable here)
    lines: list[str] = []
    a = lines.append

    triage = evidence.get("triage", {})
    category = triage.get("category", "code")
    skipped = triage.get("skipped", False)
    skip_reason = triage.get("skip_reason") or "docs-only diff"

    # ── header ──
    a("## bobthereviewer report")
    a("")
    a(f"| | |")
    a(f"|---|---|")
    a(f"| **Run** | `{evidence.get('run_id', '')[:8]}` |")
    a(f"| **Base** | `{evidence.get('base_ref', '')}` → `{evidence.get('head_ref', '')}` |")
    a(f"| **Triage** | {_triage_label(category)} |")
    if evidence.get("ci_run_url"):
        a(f"| **CI** | [{evidence['ci_run_url']}]({evidence['ci_run_url']}) |")
    a("")

    if skipped:
        a(f"> ⏭️ **Execution skipped** — {skip_reason}  ")
        a(f"> Tests and probes were not run. Use `--full` to force execution.")
        a("")

    # ── changed functions ──
    changed = evidence.get("changed_functions", [])
    probe_results = evidence.get("probe_results", [])

    if changed:
        a("### Changed functions")
        a("")
        for fn in changed:
            a(f"#### `{fn['symbol']}` — `{fn['file_path']}`")
            a("")

            callers = fn.get("callers", [])
            if callers:
                a("**Callers**")
                a("")
                a("| Symbol | File | Line | In diff? | Note |")
                a("|---|---|---|---|---|")
                for c in callers:
                    in_diff = "Yes" if c.get("in_diff") else "**No — outside diff**"
                    note = "Needs a probe" if c.get("needs_probe") else ""
                    a(f"| `{c['symbol']}` | `{c['file_path']}` | {c['line']} | {in_diff} | {note} |")
                a("")

            unknown = fn.get("unknown_references", [])
            if unknown:
                a("**Unknown edges** (dynamic or unresolved references)")
                a("")
                a("| File | Line | Reason |")
                a("|---|---|---|")
                for r in unknown:
                    a(f"| `{r['file_path']}` | {r['line']} | {r['reason']} |")
                a("")

    else:
        a("### Changed functions")
        a("")
        a("No changed functions detected.")
        a("")

    # Include probes of unchanged callers as well as changed functions.
    if probe_results:
        a("### Probe results")
        a("")
        head_decisions = evidence.get("decisions", [])
        for pr in probe_results:
            a(f"**Probe:** `{pr['probe_file']}` — `{pr['target']}`")
            a("")
            a("| Case | Before | After | Status | Decision |")
            a("|---|---|---|---|---|")
            for c in pr.get("cases", []):
                reason = f" ({c['inconclusive_reason']})" if c.get("inconclusive_reason") else ""
                status = c.get("comparison_status") or c["execution_status"]
                prior_note = ""
                if pr.get("prior_difference_run_id"):
                    prior_note = f" (previously differed in run {pr['prior_difference_run_id']})"
                decision_cell = ""
                if status == "differ":
                    # Only a difference needs a human disposition; say so next to it.
                    decision_cell = _decision_cell(
                        c.get("id", ""), pr.get("target", ""), pr.get("probe_hash", ""),
                        head_decisions,
                    )
                a(f"| `{c['id']}` | {_fmt_output(c.get('base_output'))} "
                  f"| {_fmt_output(c.get('head_output'))} "
                  f"| {_status_label(status)}{reason}{prior_note} | {decision_cell} |")
            a("")
        if any(c.get("comparison_status") == "differ"
               for pr in probe_results for c in pr.get("cases", [])):
            a("> A difference with no decision yet is unresolved work, not an approval.")
            a("")

    notes = evidence.get("analysis_limits", {}).get("notes", [])
    if notes:
        a("### Analysis and execution notes")
        a("")
        for note in notes:
            a(f"- {note}")
        a("")

    # ── test results ──
    test_results = evidence.get("test_results", {})
    base_tests = test_results.get("base", {})
    head_tests = test_results.get("head", {})
    all_ids = sorted(set(list(base_tests) + list(head_tests)))

    a("### Test results")
    a("")
    if skipped:
        a(f"> Execution skipped — {skip_reason}")
    elif not all_ids:
        a("No test results recorded.")
    else:
        changed_tests = [
            nid for nid in all_ids
            if base_tests.get(nid, {}).get("status") != head_tests.get(nid, {}).get("status")
        ]
        if changed_tests:
            a(f"⚠️ **{len(changed_tests)} test(s) changed status between base and head.**")
            a("")
        a("| Test | Base | Head |")
        a("|---|---|---|")
        for nid in all_ids:
            b = _test_label(base_tests.get(nid, {}).get("status", "—"))
            h = _test_label(head_tests.get(nid, {}).get("status", "—"))
            a(f"| `{nid}` | {b} | {h} |")
    a("")

    # ── prior decisions ──
    # Only decisions approved on the default branch; `decisions` are this branch's own
    # proposals, already shown next to their cases above.
    decisions = evidence.get("prior_decisions", [])
    if decisions:
        a("### Prior decisions")
        a("")
        a("> ℹ️ This is prior context, not approval of the current change.")
        a("")
        for d in decisions:
            verdict = d.get("verdict", "unresolved").capitalize()
            a(f"- **{verdict}** — `{d.get('symbol', '')}` — {d.get('rationale', '(no rationale)')}")
        a("")

    return "\n".join(lines)
