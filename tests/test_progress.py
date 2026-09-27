"""Tests for bobthereviewer.progress (ST 11)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from bobthereviewer.progress import make_emitter, replay_events


RUN_ID = "00000000-0000-4000-8000-000000000001"


class TestMakeEmitterCLIMode:
    def test_emits_ndjson_to_stdout(self, tmp_path, capsys):
        emit = make_emitter(run_id=RUN_ID, mode="cli")
        emit("triage", "started", "Classifying diff")
        captured = capsys.readouterr()
        event = json.loads(captured.out.strip())
        assert event["run_id"] == RUN_ID
        assert event["step"] == "triage"
        assert event["status"] == "started"
        assert event["message"] == "Classifying diff"
        assert "timestamp" in event

    def test_multiple_events_separate_lines(self, capsys):
        emit = make_emitter(run_id=RUN_ID, mode="cli")
        emit("triage", "started", "msg1")
        emit("triage", "completed", "msg2")
        captured = capsys.readouterr()
        lines = [l for l in captured.out.splitlines() if l.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["status"] == "started"
        assert json.loads(lines[1])["status"] == "completed"

    def test_does_not_write_to_file_in_cli_mode(self, tmp_path, capsys):
        events_file = str(tmp_path / "events.jsonl")
        emit = make_emitter(run_id=RUN_ID, events_path=events_file, mode="cli")
        emit("done", "completed", "finished")
        assert not Path(events_file).exists()

    def test_invalid_step_raises(self):
        emit = make_emitter(run_id=RUN_ID, mode="cli")
        with pytest.raises(ValueError, match="invalid step"):
            emit("bad_step", "started", "msg")

    def test_invalid_status_raises(self):
        emit = make_emitter(run_id=RUN_ID, mode="cli")
        with pytest.raises(ValueError, match="invalid status"):
            emit("triage", "bad_status", "msg")


class TestMakeEmitterServerMode:
    def test_writes_to_stdout_and_file(self, tmp_path, capsys):
        events_file = str(tmp_path / "events.jsonl")
        emit = make_emitter(run_id=RUN_ID, events_path=events_file, mode="server")
        emit("test_base", "started", "Running tests on base")

        captured = capsys.readouterr()
        # stdout
        event_stdout = json.loads(captured.out.strip())
        assert event_stdout["step"] == "test_base"

        # file
        lines = Path(events_file).read_text().splitlines()
        assert len(lines) == 1
        event_file = json.loads(lines[0])
        assert event_file["step"] == "test_base"

    def test_multiple_events_appended_to_file(self, tmp_path, capsys):
        events_file = str(tmp_path / "events.jsonl")
        emit = make_emitter(run_id=RUN_ID, events_path=events_file, mode="server")
        emit("triage", "started", "a")
        emit("triage", "completed", "b")
        emit("done", "completed", "c")

        lines = Path(events_file).read_text().splitlines()
        assert len(lines) == 3
        steps = [json.loads(l)["step"] for l in lines]
        assert steps == ["triage", "triage", "done"]


class TestReplayEvents:
    def test_replays_all_events(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            '{"run_id":"x","step":"triage","status":"started","message":"","timestamp":"t1"}\n'
            '{"run_id":"x","step":"done","status":"completed","message":"","timestamp":"t2"}\n'
        )
        events = replay_events(str(events_file))
        assert len(events) == 2
        assert events[0]["step"] == "triage"
        assert events[1]["step"] == "done"

    def test_skips_malformed_lines(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            'not json\n'
            '{"step":"done","status":"completed","message":"","timestamp":"t"}\n'
        )
        events = replay_events(str(events_file))
        assert len(events) == 1
        assert events[0]["step"] == "done"

    def test_returns_empty_for_missing_file(self, tmp_path):
        result = replay_events(str(tmp_path / "nonexistent.jsonl"))
        assert result == []

    def test_returns_empty_for_empty_file(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        result = replay_events(str(events_file))
        assert result == []
