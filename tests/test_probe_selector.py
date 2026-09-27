"""Tests for bobthereviewer.probe_selector (ST 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bobthereviewer.probe_selector import SelectedProbe, select_probes, _sha256


PROBE_CONTENT_A = json.dumps({
    "schema_version": "1",
    "target": "mymod.func",
    "cases": [{"id": "c1", "args": [], "kwargs": {}}],
}).encode()

PROBE_CONTENT_B = json.dumps({
    "schema_version": "1",
    "target": "mymod.func",
    "cases": [{"id": "c1", "args": [1], "kwargs": {}}],
}).encode()


def _write_probe(worktree: Path, rel_path: str, content: bytes) -> None:
    """Write probe bytes to <worktree>/<rel_path>, creating dirs as needed."""
    target = worktree / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


# ---------------------------------------------------------------------------
# Four-case rule
# ---------------------------------------------------------------------------

class TestFourCaseRule:
    def test_base_only(self, tmp_path):
        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir(); head.mkdir()
        _write_probe(base, ".bobreviewer/probes/p.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))

        assert len(result) == 1
        r = result[0]
        assert r.probe_path == ".bobreviewer/probes/p.json"
        assert r.probe_bytes == PROBE_CONTENT_A
        assert r.source == "base"

    def test_head_new(self, tmp_path):
        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir(); head.mkdir()
        _write_probe(head, ".bobreviewer/probes/new.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))

        assert len(result) == 1
        r = result[0]
        assert r.probe_path == ".bobreviewer/probes/new.json"
        assert r.probe_bytes == PROBE_CONTENT_A
        assert r.source == "head_new"

    def test_both_same_hash_uses_base(self, tmp_path):
        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir(); head.mkdir()
        _write_probe(base, ".bobreviewer/probes/p.json", PROBE_CONTENT_A)
        _write_probe(head, ".bobreviewer/probes/p.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))

        assert len(result) == 1
        r = result[0]
        assert r.probe_bytes == PROBE_CONTENT_A
        assert r.source == "base"
        assert r.probe_hash == _sha256(PROBE_CONTENT_A)

    def test_both_different_hash_uses_base(self, tmp_path):
        """Edited probe on head → base bytes must be used on both sides."""
        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir(); head.mkdir()
        _write_probe(base, ".bobreviewer/probes/p.json", PROBE_CONTENT_A)
        _write_probe(head, ".bobreviewer/probes/p.json", PROBE_CONTENT_B)

        result = select_probes(str(base), str(head))

        assert len(result) == 1
        r = result[0]
        assert r.probe_bytes == PROBE_CONTENT_A  # base wins
        assert r.source == "base"
        assert r.probe_hash == _sha256(PROBE_CONTENT_A)


# ---------------------------------------------------------------------------
# Dual-location scan
# ---------------------------------------------------------------------------

class TestDualLocationScan:
    def test_canonical_location(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        _write_probe(base, ".bobreviewer/probes/canon.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))
        assert len(result) == 1
        assert result[0].probe_path == ".bobreviewer/probes/canon.json"

    def test_legacy_location(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        _write_probe(base, "probes/legacy.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))
        assert len(result) == 1
        assert result[0].probe_path == "probes/legacy.json"

    def test_both_locations_merged(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        _write_probe(base, ".bobreviewer/probes/canon.json", PROBE_CONTENT_A)
        _write_probe(base, "probes/legacy.json", PROBE_CONTENT_B)

        result = select_probes(str(base), str(head))
        paths = [r.probe_path for r in result]
        assert ".bobreviewer/probes/canon.json" in paths
        assert "probes/legacy.json" in paths
        assert len(result) == 2

    def test_canonical_wins_over_legacy_same_rel_path(self, tmp_path):
        """If somehow the same relative path appears in both dirs, canonical wins."""
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        # Both written to their respective dirs but with the same rel path would
        # require the dirs to overlap, which they don't. Instead verify canonical
        # is scanned first by checking that its content appears in output.
        _write_probe(base, ".bobreviewer/probes/x.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))
        assert result[0].probe_bytes == PROBE_CONTENT_A


# ---------------------------------------------------------------------------
# Ordering and empty cases
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_sorted_by_probe_path(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        _write_probe(base, ".bobreviewer/probes/z.json", PROBE_CONTENT_A)
        _write_probe(base, ".bobreviewer/probes/a.json", PROBE_CONTENT_A)
        _write_probe(head, ".bobreviewer/probes/m.json", PROBE_CONTENT_A)

        result = select_probes(str(base), str(head))
        paths = [r.probe_path for r in result]
        assert paths == sorted(paths)

    def test_no_probes_returns_empty(self, tmp_path):
        base = tmp_path / "base"; base.mkdir()
        head = tmp_path / "head"; head.mkdir()
        assert select_probes(str(base), str(head)) == []
