"""Tests for bobreviewer.run_store (ST 12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bobreviewer.run_store import (
    RunNotFoundError,
    create_run_dir,
    get_run,
    list_runs,
    save_evidence,
)

RUN_ID = "00000000-0000-4000-8000-000000000001"
RUN_ID_2 = "00000000-0000-4000-8000-000000000002"

MINIMAL_EVIDENCE = {
    "schema_version": "1",
    "run_id": RUN_ID,
    "generated_at": "2025-01-01T00:00:00+00:00",
    "base_ref": "demo-base",
    "head_ref": "demo-rounding-change",
}


class TestCreateRunDir:
    def test_creates_directory(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        assert run_dir.is_dir()

    def test_writes_meta_json(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID, base_ref="main", head_ref="HEAD")
        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["run_id"] == RUN_ID
        assert meta["status"] == "running"
        assert meta["base_ref"] == "main"
        assert meta["head_ref"] == "HEAD"
        assert "started_at" in meta

    def test_creates_empty_events_jsonl(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        events_path = run_dir / "events.jsonl"
        assert events_path.exists()
        assert events_path.read_text() == ""

    def test_idempotent_on_existing_dir(self, tmp_path):
        create_run_dir(str(tmp_path), RUN_ID)
        # Should not raise
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        assert run_dir.is_dir()


class TestSaveEvidence:
    def test_writes_evidence_json(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        assert (run_dir / "evidence.json").exists()
        loaded = json.loads((run_dir / "evidence.json").read_text())
        assert loaded["run_id"] == RUN_ID

    def test_no_tmp_file_after_save(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        assert not (run_dir / "evidence.json.tmp").exists()

    def test_updates_meta_status_to_completed(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["status"] == "completed"

    def test_meta_gets_generated_at(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        evidence = {**MINIMAL_EVIDENCE, "generated_at": "2025-06-01T12:00:00+00:00"}
        save_evidence(run_dir, evidence)
        meta = json.loads((run_dir / "meta.json").read_text())
        assert meta["generated_at"] == "2025-06-01T12:00:00+00:00"


class TestListRuns:
    def test_returns_empty_for_no_runs(self, tmp_path):
        assert list_runs(str(tmp_path)) == []

    def test_completed_run_appears(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        runs = list_runs(str(tmp_path))
        assert len(runs) == 1
        assert runs[0]["run_id"] == RUN_ID
        assert runs[0]["status"] == "completed"

    def test_interrupted_run_detected(self, tmp_path):
        """A run with meta.json but no evidence.json → status: interrupted."""
        create_run_dir(str(tmp_path), RUN_ID)
        # Do NOT call save_evidence — simulates an interrupted run
        runs = list_runs(str(tmp_path))
        assert len(runs) == 1
        assert runs[0]["status"] == "interrupted"

    def test_multiple_runs_sorted_newest_first(self, tmp_path):
        run_dir_1 = create_run_dir(str(tmp_path), RUN_ID, base_ref="r1")
        save_evidence(run_dir_1, {**MINIMAL_EVIDENCE, "run_id": RUN_ID, "generated_at": "2025-01-01T00:00:00+00:00"})
        import time; time.sleep(0.01)  # ensure different started_at
        run_dir_2 = create_run_dir(str(tmp_path), RUN_ID_2, base_ref="r2")
        save_evidence(run_dir_2, {**MINIMAL_EVIDENCE, "run_id": RUN_ID_2})
        runs = list_runs(str(tmp_path))
        assert len(runs) == 2
        assert runs[0]["run_id"] == RUN_ID_2  # most recent first

    def test_list_is_idempotent(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        list_runs(str(tmp_path))
        list_runs(str(tmp_path))
        # Still only one run, not doubled
        assert len(list_runs(str(tmp_path))) == 1


class TestGetRun:
    def test_returns_evidence_dict(self, tmp_path):
        run_dir = create_run_dir(str(tmp_path), RUN_ID)
        save_evidence(run_dir, MINIMAL_EVIDENCE)
        result = get_run(str(tmp_path), RUN_ID)
        assert result["run_id"] == RUN_ID

    def test_raises_run_not_found_for_missing_run(self, tmp_path):
        with pytest.raises(RunNotFoundError):
            get_run(str(tmp_path), "nonexistent-run-id")

    def test_raises_run_not_found_for_interrupted_run(self, tmp_path):
        """An interrupted run has no evidence.json → should raise RunNotFoundError."""
        create_run_dir(str(tmp_path), RUN_ID)
        with pytest.raises(RunNotFoundError):
            get_run(str(tmp_path), RUN_ID)
