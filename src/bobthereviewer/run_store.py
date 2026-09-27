"""
bobthereviewer.run_store
=====================
Manages the saved-run directory under ``.bobreviewer/runs/<run_id>/``.

Each run directory contains:
  meta.json       — written at run start; updated to "completed" after atomic replace
  evidence.json   — written atomically after the run finishes
  report.md       — Markdown rendering of the evidence
  events.jsonl    — progress events, appended during the run

A run directory that has ``meta.json`` but no ``evidence.json`` is treated as
"interrupted" in ``list_runs``.

The ``.bobreviewer/runs/`` directory is git-ignored (never committed).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class RunNotFoundError(Exception):
    """Raised by ``get_run`` when the requested run_id does not exist."""


def _runs_dir(repo_dir: str) -> Path:
    return Path(repo_dir) / ".bobreviewer" / "runs"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def create_run_dir(
    repo_dir: str,
    run_id: str,
    base_ref: str = "",
    head_ref: str = "",
    triage_category: str = "code",
) -> Path:
    """
    Create ``.bobreviewer/runs/<run_id>/`` and write the initial ``meta.json``
    with ``status: "running"``.  Also creates an empty ``events.jsonl``.

    Returns the run directory Path.
    """
    run_dir = _runs_dir(repo_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id":          run_id,
        "started_at":      _now_iso(),
        "status":          "running",
        "base_ref":        base_ref,
        "head_ref":        head_ref,
        "triage_category": triage_category,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Create empty events file so the SSE endpoint can open it immediately
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        events_path.write_text("", encoding="utf-8")

    return run_dir


def save_evidence(run_dir: Path, evidence_dict: dict) -> None:
    """
    Write ``evidence.json`` atomically to the run directory.

    Writes to ``evidence.json.tmp`` first, then ``os.replace()`` to
    ``evidence.json``.  Updates ``meta.json`` to ``status: "completed"`` and
    records ``generated_at`` from the evidence dict.
    """
    from bobthereviewer.report import render_markdown

    report_tmp = run_dir / "report.md.tmp"
    report_tmp.write_text(render_markdown(evidence_dict), encoding="utf-8")
    report_tmp.replace(run_dir / "report.md")
    tmp_path = run_dir / "evidence.json.tmp"
    final_path = run_dir / "evidence.json"

    tmp_path.write_text(json.dumps(evidence_dict, indent=2), encoding="utf-8")
    os.replace(str(tmp_path), str(final_path))

    # Update meta.json
    meta_path = run_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        meta = {}

    meta["status"] = "completed"
    meta["triage_category"] = evidence_dict.get("triage", {}).get("category", "code")
    meta["generated_at"] = evidence_dict.get("generated_at", _now_iso())
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def fail_run(run_dir: Path) -> None:
    """Keep a failed run discoverable without claiming completed evidence."""
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["status"] = "failed"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def list_runs(repo_dir: str) -> list[dict]:
    """
    Return metadata for all saved runs, sorted by ``started_at`` descending
    (most recent first).

    Each entry has the shape::

        {
          "run_id":          "<uuid>",
          "started_at":      "<ISO-8601>",
          "generated_at":    "<ISO-8601 or None>",
          "status":          "running | completed | interrupted",
          "base_ref":        "<ref>",
          "head_ref":        "<ref>",
          "triage_category": "<category>",
        }

    A run directory with ``meta.json`` but no ``evidence.json`` is reported as
    ``status: "interrupted"``.
    """
    base = _runs_dir(repo_dir)
    if not base.is_dir():
        return []

    results: list[dict] = []
    for meta_path in base.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        run_dir = meta_path.parent
        evidence_path = run_dir / "evidence.json"

        # Override status for interrupted runs
        if meta.get("status") == "running" and not evidence_path.exists():
            meta = dict(meta)
            meta["status"] = "interrupted"

        results.append(meta)

    return sorted(results, key=lambda m: m.get("started_at", ""), reverse=True)


def get_run(repo_dir: str, run_id: str) -> dict:
    """
    Return the parsed ``evidence.json`` for the given ``run_id``.

    Raises ``RunNotFoundError`` if the run directory or evidence file is absent.
    """
    evidence_path = _runs_dir(repo_dir) / run_id / "evidence.json"
    if not evidence_path.exists():
        raise RunNotFoundError(f"no evidence.json for run_id={run_id!r}")
    return json.loads(evidence_path.read_text(encoding="utf-8"))
