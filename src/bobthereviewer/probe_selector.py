"""
bobthereviewer.probe_selector
==========================
Determines which probe files to run and which bytes to use on each side,
applying the frozen probe selection rule from the spec:

  - Probes in base only           → use base bytes on both sides
  - Probes in head only (new)     → use head bytes on both sides
  - Same path, same hash          → use base bytes (either is identical)
  - Same path, different hash     → use base bytes (edited probe; base wins)

Probes are scanned from the canonical location ``.bobreviewer/probes/``
first, then from the legacy location ``probes/`` at the worktree root.
Both directories are merged into the same namespace (repo-relative path
is the key).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class SelectedProbe:
    """A probe file selected for execution on both worktree sides."""

    # Repo-relative path, e.g. ".bobreviewer/probes/invoice_basic.json"
    probe_path: str
    # The actual bytes to send to both sides
    probe_bytes: bytes
    # SHA-256 hex of probe_bytes
    probe_hash: str
    # "base" — came from base (or was edited on head, so base wins)
    # "head_new" — only present on head branch
    source: Literal["base", "head_new"]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scan_probe_dirs(worktree_root: str) -> dict[str, bytes]:
    """
    Return ``{repo_relative_path: file_bytes}`` for all ``.json`` files found
    under ``<worktree_root>/.bobreviewer/probes/`` and ``<worktree_root>/probes/``.

    Later-found files do NOT override earlier ones (canonical location wins
    over legacy when the same repo-relative path appears in both, which
    should not happen in practice).
    """
    root = Path(worktree_root)
    result: dict[str, bytes] = {}

    # Canonical location first
    probe_dirs = [
        root / ".bobreviewer" / "probes",
        root / "probes",
    ]

    for probe_dir in probe_dirs:
        if not probe_dir.is_dir():
            continue
        for p in sorted(probe_dir.rglob("*.json")):
            rel = p.relative_to(root).as_posix()
            if rel not in result:  # canonical wins
                result[rel] = p.read_bytes()

    return result


def select_probes(base_worktree_path: str, head_worktree_path: str) -> list[SelectedProbe]:
    """
    Apply the frozen probe selection rule and return the ordered list of
    probes to run against both worktrees.

    The returned list is sorted by ``probe_path`` for stable ordering.
    """
    base_probes = _scan_probe_dirs(base_worktree_path)
    head_probes = _scan_probe_dirs(head_worktree_path)

    all_paths = sorted(set(base_probes) | set(head_probes))
    selected: list[SelectedProbe] = []

    for path in all_paths:
        in_base = path in base_probes
        in_head = path in head_probes

        if in_base and not in_head:
            # Present in base only — use base bytes
            data = base_probes[path]
            selected.append(SelectedProbe(
                probe_path=path,
                probe_bytes=data,
                probe_hash=_sha256(data),
                source="base",
            ))

        elif in_head and not in_base:
            # New probe added on head — use head bytes
            data = head_probes[path]
            selected.append(SelectedProbe(
                probe_path=path,
                probe_bytes=data,
                probe_hash=_sha256(data),
                source="head_new",
            ))

        else:
            # Present in both — always use base bytes
            # (covers: same hash → identical, different hash → edited, use base)
            data = base_probes[path]
            selected.append(SelectedProbe(
                probe_path=path,
                probe_bytes=data,
                probe_hash=_sha256(data),
                source="base",
            ))

    return selected
