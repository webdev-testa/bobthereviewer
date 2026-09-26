"""
tests/test_decisions.py — Lane 4 (D)

Unit tests for app/decisions.py:
  - validate_and_save: valid intended, short rationale rejection, unintended without rationale
  - lookup: empty dir, matching record, decoy-rejection (same symbol different file_path)
"""
import json
import pathlib
import sys
import pytest

# Ensure the project root is importable when running from any directory
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from app.decisions import validate_and_save, lookup, _MIN_RATIONALE_CHARS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_BASE = {
    "schema_version": "1",
    "run_id": "00000000-0000-0000-0000-000000000001",
    "repository": "https://github.com/example/bobthereviewer",
    "file_path": "sample_project/pricing/discount.py",
    "symbol": "sample_project.pricing.discount.apply_discount",
    "base_commit": "a" * 40,
    "head_commit": "b" * 40,
    "probe_file": "probes/discount_basic.json",
    "probe_hash": "c" * 64,
    "observed_before": 100.0,
    "observed_after": 99.99,
    "verdict": "unintended",
    "rationale": "",
    "status": "proposed",
    "timestamp": "2025-01-01T00:00:00Z",
}


def make_decision(**overrides) -> dict:
    return {**VALID_BASE, **overrides}


# ---------------------------------------------------------------------------
# validate_and_save
# ---------------------------------------------------------------------------

class TestValidateAndSave:
    def test_unintended_empty_rationale_writes_file(self, tmp_path):
        """unintended verdict with empty rationale should write successfully."""
        record = make_decision(verdict="unintended", rationale="")
        path = validate_and_save(record, tmp_path)
        assert path.exists()
        written = json.loads(path.read_text())
        assert written["verdict"] == "unintended"
        assert written["status"] == "proposed"

    def test_unresolved_writes_file(self, tmp_path):
        """unresolved verdict should write successfully."""
        record = make_decision(verdict="unresolved", rationale="")
        path = validate_and_save(record, tmp_path)
        assert path.exists()

    def test_intended_with_good_rationale_writes_file(self, tmp_path):
        """intended with a sufficiently long rationale writes successfully."""
        rationale = "Updated tax rate per new government regulation effective Q1."
        record = make_decision(verdict="intended", rationale=rationale)
        path = validate_and_save(record, tmp_path)
        assert path.exists()
        written = json.loads(path.read_text())
        assert written["rationale"] == rationale

    def test_intended_empty_rationale_raises(self, tmp_path):
        """intended with empty rationale raises ValueError."""
        record = make_decision(verdict="intended", rationale="")
        with pytest.raises(ValueError, match="meaningful rationale"):
            validate_and_save(record, tmp_path)

    def test_intended_short_rationale_raises(self, tmp_path):
        """intended with fewer than _MIN_RATIONALE_CHARS non-whitespace chars raises."""
        short = "ok"  # 2 chars
        assert len(short.strip()) < _MIN_RATIONALE_CHARS
        record = make_decision(verdict="intended", rationale=short)
        with pytest.raises(ValueError, match="meaningful rationale"):
            validate_and_save(record, tmp_path)

    def test_intended_whitespace_only_rationale_raises(self, tmp_path):
        """Rationale that is only whitespace counts as empty."""
        record = make_decision(verdict="intended", rationale="   \n\t  ")
        with pytest.raises(ValueError, match="meaningful rationale"):
            validate_and_save(record, tmp_path)

    def test_status_always_forced_to_proposed(self, tmp_path):
        """status field is always written as proposed even if caller passes something else."""
        record = make_decision(verdict="unintended", status="approved")
        path = validate_and_save(record, tmp_path)
        written = json.loads(path.read_text())
        assert written["status"] == "proposed"

    def test_filename_contains_symbol_slug_and_short_sha(self, tmp_path):
        """Filename follows <symbol_slug>-<head_commit_short>.json pattern."""
        record = make_decision(
            symbol="sample_project.pricing.discount.apply_discount",
            head_commit="bbbbbbb" + "b" * 33,
        )
        path = validate_and_save(record, tmp_path)
        assert "apply_discount" in path.name
        assert "bbbbbbb" in path.name
        assert path.suffix == ".json"

    def test_output_dir_created_if_absent(self, tmp_path):
        """output_dir is created when it does not already exist."""
        deep = tmp_path / "new" / "nested" / "dir"
        assert not deep.exists()
        validate_and_save(make_decision(), deep)
        assert deep.exists()


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def _write_decision(self, directory: pathlib.Path, record: dict) -> pathlib.Path:
        directory.mkdir(parents=True, exist_ok=True)
        slug = record["symbol"].replace(".", "_")
        p = directory / f"{slug}.json"
        p.write_text(json.dumps(record), encoding="utf-8")
        return p

    def test_empty_dir_returns_empty_list(self, tmp_path):
        results = lookup(
            "https://github.com/example/repo",
            "some/file.py",
            "some.symbol",
            decisions_dir=tmp_path / "nonexistent",
        )
        assert results == []

    def test_matching_record_returned(self, tmp_path):
        record = make_decision(
            repository="https://github.com/example/repo",
            file_path="pricing/discount.py",
            symbol="pricing.discount.apply_discount",
        )
        self._write_decision(tmp_path, record)
        # Pass decisions_dir directly so git reachability check is skipped
        # (reachable_paths returns None on fail-open, meaning all local files pass)
        results = lookup(
            "https://github.com/example/repo",
            "pricing/discount.py",
            "pricing.discount.apply_discount",
            decisions_dir=tmp_path,
        )
        assert len(results) == 1
        assert results[0]["symbol"] == "pricing.discount.apply_discount"

    def test_decoy_different_file_path_not_returned(self, tmp_path):
        """Same symbol but different file_path must NOT match."""
        real_record = make_decision(
            repository="https://github.com/example/repo",
            file_path="pricing/discount.py",
            symbol="pricing.discount.apply_discount",
        )
        decoy_record = make_decision(
            repository="https://github.com/example/repo",
            file_path="billing/discount.py",       # different file!
            symbol="pricing.discount.apply_discount",
        )
        # Write both with distinct filenames
        (tmp_path / "real.json").write_text(json.dumps(real_record), encoding="utf-8")
        (tmp_path / "decoy.json").write_text(json.dumps(decoy_record), encoding="utf-8")

        results = lookup(
            "https://github.com/example/repo",
            "pricing/discount.py",
            "pricing.discount.apply_discount",
            decisions_dir=tmp_path,
        )
        assert len(results) == 1
        assert results[0]["file_path"] == "pricing/discount.py"

    def test_different_repository_not_returned(self, tmp_path):
        """Same file_path and symbol but different repo must NOT match."""
        record = make_decision(
            repository="https://github.com/other/repo",
            file_path="pricing/discount.py",
            symbol="pricing.discount.apply_discount",
        )
        (tmp_path / "other.json").write_text(json.dumps(record), encoding="utf-8")
        results = lookup(
            "https://github.com/example/repo",
            "pricing/discount.py",
            "pricing.discount.apply_discount",
            decisions_dir=tmp_path,
        )
        assert results == []

    def test_nonexistent_decisions_dir_returns_empty(self, tmp_path):
        results = lookup(
            "https://github.com/example/repo",
            "pricing/discount.py",
            "pricing.discount.apply_discount",
            decisions_dir=tmp_path / "missing",
        )
        assert results == []

    def test_malformed_json_skipped(self, tmp_path):
        """A malformed JSON file is skipped without crashing."""
        (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
        results = lookup(
            "https://github.com/example/repo",
            "pricing/discount.py",
            "pricing.discount.apply_discount",
            decisions_dir=tmp_path,
        )
        assert results == []
