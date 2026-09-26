"""
tests/test_history.py — Lane 4 (D)

Tests for the decision history lookup scenario (Act 5):
- Approved decision is found for matching repo + file_path + symbol
- Decoy with same symbol but different file_path is NOT returned
- Required disclaimer text is present in the surfaced context message
"""
import json
import pathlib
import sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from app.decisions import lookup


# ---------------------------------------------------------------------------
# Helper: build the context disclaimer message (mirrors Bob workflow logic)
# ---------------------------------------------------------------------------

def format_prior_context(decision: dict) -> str:
    """Format the required disclaimer text for a prior approved decision."""
    verdict = decision.get("verdict", "unknown")
    rationale = decision.get("rationale", "")
    return (
        f"Prior decision found: {verdict} — {rationale}. "
        "This is prior context, not approval of the current change."
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_decision(
    repo: str = "https://github.com/example/bobthereviewer",
    file_path: str = "sample_project/pricing/pricing.py",
    symbol: str = "sample_project.pricing.pricing.calculate_price",
    verdict: str = "intended",
    rationale: str = "Tax rate updated per Q1 government regulation.",
) -> dict:
    return {
        "schema_version": "1",
        "run_id": "00000000-0000-0000-0000-000000000002",
        "repository": repo,
        "file_path": file_path,
        "symbol": symbol,
        "base_commit": "a" * 40,
        "head_commit": "c" * 40,
        "probe_file": "probes/pricing_basic.json",
        "probe_hash": "d" * 64,
        "case_id": "case-1",
        "observed_before": 60.0,
        "observed_after": {"exception": "ValidationError", "message": "Discount exceeds maximum"},
        "verdict": verdict,
        "rationale": rationale,
        "status": "proposed",
        "timestamp": "2025-01-02T00:00:00Z",
    }


class TestHistoryLookup:
    def test_matching_decision_returned(self, tmp_path):
        """An approved decision matching all three keys is returned."""
        record = make_decision()
        (tmp_path / "matching.json").write_text(json.dumps(record), encoding="utf-8")

        results = lookup(
            repo=record["repository"],
            file_path=record["file_path"],
            symbol=record["symbol"],
            decisions_dir=tmp_path,
        )
        assert len(results) == 1
        assert results[0]["symbol"] == record["symbol"]

    def test_decoy_same_symbol_different_file_not_returned(self, tmp_path):
        """Same function name in a different file must NOT match — no symbol-only borrowing."""
        real = make_decision(file_path="sample_project/pricing/pricing.py")
        decoy = make_decision(file_path="sample_project/billing/pricing.py")  # different file!

        (tmp_path / "real.json").write_text(json.dumps(real), encoding="utf-8")
        (tmp_path / "decoy.json").write_text(json.dumps(decoy), encoding="utf-8")

        results = lookup(
            repo=real["repository"],
            file_path="sample_project/pricing/pricing.py",
            symbol=real["symbol"],
            decisions_dir=tmp_path,
        )
        assert len(results) == 1
        assert results[0]["file_path"] == "sample_project/pricing/pricing.py"

    def test_no_decisions_returns_empty(self, tmp_path):
        results = lookup(
            repo="https://github.com/example/bobthereviewer",
            file_path="sample_project/pricing/pricing.py",
            symbol="sample_project.pricing.pricing.calculate_price",
            decisions_dir=tmp_path / "nonexistent",
        )
        assert results == []

    def test_disclaimer_text_contains_required_phrase(self, tmp_path):
        """The formatted context message must contain the required disclaimer."""
        record = make_decision(
            verdict="intended",
            rationale="Tax rate updated per Q1 government regulation.",
        )
        (tmp_path / "act2.json").write_text(json.dumps(record), encoding="utf-8")

        results = lookup(
            repo=record["repository"],
            file_path=record["file_path"],
            symbol=record["symbol"],
            decisions_dir=tmp_path,
        )
        assert len(results) == 1
        context_msg = format_prior_context(results[0])
        assert "This is prior context, not approval of the current change." in context_msg
        assert "intended" in context_msg
        assert record["rationale"] in context_msg

    def test_multiple_matching_records_all_returned(self, tmp_path):
        """Multiple decisions for the same target should all surface."""
        record_a = make_decision(rationale="First policy change — Q1 regulation.")
        record_b = {**record_a, "rationale": "Second policy change — Q3 update.", "run_id": "00000000-0000-0000-0000-000000000099"}

        (tmp_path / "a.json").write_text(json.dumps(record_a), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(record_b), encoding="utf-8")

        results = lookup(
            repo=record_a["repository"],
            file_path=record_a["file_path"],
            symbol=record_a["symbol"],
            decisions_dir=tmp_path,
        )
        assert len(results) == 2
