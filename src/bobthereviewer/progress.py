"""
bobthereviewer.progress
====================
Progress event emitter shared by all runner modules and the local server.

CLI mode  → writes NDJSON to stdout only.
Server mode → writes NDJSON to stdout AND appends to an ``events.jsonl``
              file so late-connecting SSE clients can replay all past events.

Usage::

    from bobthereviewer.progress import make_emitter, replay_events

    emit = make_emitter(run_id="<uuid>", events_path="/path/to/events.jsonl", mode="cli")
    emit("triage", "started", "Classifying diff")
    emit("triage", "completed", "Category: code")

Progress event shape (matches contracts/local-server-api.md)::

    {
      "run_id":    "<uuid>",
      "step":      "triage | analyze | test_base | test_head | probe_base | probe_head | done | error",
      "status":    "started | completed | failed",
      "message":   "<human-readable string>",
      "timestamp": "<ISO-8601>"
    }
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional


_VALID_STEPS = frozenset({
    "triage", "analyze", "test_base", "test_head",
    "probe_base", "probe_head", "done", "error",
})
_VALID_STATUSES = frozenset({"started", "completed", "failed"})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def make_emitter(
    run_id: str,
    events_path: Optional[str] = None,
    mode: Literal["cli", "server"] = "cli",
) -> Callable[[str, str, str], None]:
    """
    Return an ``emit(step, status, message)`` callable.

    Parameters
    ----------
    run_id :
        The UUID for the current run, embedded in every event.
    events_path :
        Absolute path to the ``events.jsonl`` file for this run.
        Required when ``mode="server"``; ignored in CLI mode.
    mode :
        ``"cli"`` — write NDJSON to stdout only.
        ``"server"`` — write to stdout AND append to ``events_path`` under a lock.
    """
    _lock = threading.Lock()

    def emit(step: str, status: str, message: str) -> None:
        if step not in _VALID_STEPS:
            raise ValueError(f"invalid step: {step!r}; must be one of {sorted(_VALID_STEPS)}")
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}; must be one of {sorted(_VALID_STATUSES)}")

        event = {
            "run_id":    run_id,
            "step":      step,
            "status":    status,
            "message":   message,
            "timestamp": _now_iso(),
        }
        line = json.dumps(event, separators=(",", ":"))

        with _lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

            if mode == "server" and events_path:
                with open(events_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")

    return emit


def replay_events(events_path: str) -> list[dict]:
    """
    Read all events from ``events_path`` (NDJSON) and return them as a list.
    Malformed lines are silently skipped.
    """
    path = Path(events_path)
    if not path.exists():
        return []

    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # skip malformed lines

    return events
