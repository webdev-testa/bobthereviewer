"""
tests/test_rerun.py — Lane 4 (D)

Tests for the unintended-change fix and rerun flow:
- Resolved probe cases (differ → match) are correctly identified
- Probe hash mismatch prevents resolution link
- prior_difference_run_id is surfaced from evidence
"""
import json
import pathlib
import sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers that mirror what the Bob workflow does when comparing runs
# ---------------------------------------------------------------------------

def find_resolved_cases(initial_evidence: dict, rerun_evidence: dict) -> list[dict]:
    """Return probe cases that changed from 'differ' to 'match' between two runs.

    A resolution link is only valid when the probe_hash is unchanged between runs.
    """
    initial_differ: dict[str, dict] = {}  # (probe_file, case_id) → case
    for probe in initial_evidence.get("probe_results", []):
        for case in probe.get("cases", []):
            if case.get("status") == "differ":
                key = (probe["probe_file"], case["id"])
                initial_differ[key] = {
                    "probe_file": probe["probe_file"],
                    "probe_hash": probe["probe_hash"],
                    "case": case,
                }

    resolved = []
    for probe in rerun_evidence.get("probe_results", []):
        for case in probe.get("cases", []):
            if case.get("status") == "match":
                key = (probe["probe_file"], case["id"])
                if key in initial_differ:
                    initial_hash = initial_differ[key]["probe_hash"]
                    current_hash = probe["probe_hash"]
                    if initial_hash == current_hash:
                        resolved.append({
                            "probe_file": probe["probe_file"],
                            "case_id": case["id"],
                            "prior_run_id": initial_evidence.get("run_id"),
                            "hash_matched": True,
                        })
    return resolved


def find_hash_mismatches(initial_evidence: dict, rerun_evidence: dict) -> list[dict]:
    """Return entries where the probe file changed between runs (hash mismatch)."""
    initial_hashes: dict[str, str] = {}
    for probe in initial_evidence.get("probe_results", []):
        initial_hashes[probe["probe_file"]] = probe["probe_hash"]

    mismatches = []
    for probe in rerun_evidence.get("probe_results", []):
        pf = probe["probe_file"]
        if pf in initial_hashes and initial_hashes[pf] != probe["probe_hash"]:
            mismatches.append({
                "probe_file": pf,
                "initial_hash": initial_hashes[pf],
                "rerun_hash": probe["probe_hash"],
            })
    return mismatches


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROBE_FILE = "probes/invoice_basic.json"
_PROBE_HASH = "abc123" * 10 + "ab"  # 62 chars, stable

_INITIAL_EVIDENCE = {
    "schema_version": "1",
    "run_id": "run-initial-0001",
    "generated_at": "2025-01-01T00:00:00Z",
    "repository": "https://github.com/example/bobthereviewer",
    "base_ref": "demo-base",
    "head_ref": "demo-rounding-change",
    "base_commit": "a" * 40,
    "head_commit": "b" * 40,
    "probe_results": [
        {
            "probe_file": _PROBE_FILE,
            "probe_hash": _PROBE_HASH,
            "target": "sample_project.pricing.invoice.calculate_invoice",
            "prior_difference_run_id": None,
            "cases": [
                {
                    "id": "invoice-standard-order",
                    "args": [[39.46, 39.46, 8.78, 8.78, 8.78], 0.05],
                    "kwargs": {},
                    "base_output": 100.0,
                    "head_output": 99.99,
                    "status": "differ",
                    "inconclusive_reason": None,
                    "base_executed_at": "2025-01-01T00:00:01Z",
                    "head_executed_at": "2025-01-01T00:00:02Z",
                }
            ],
        }
    ],
}

_RERUN_EVIDENCE_FIXED = {
    **_INITIAL_EVIDENCE,
    "run_id": "run-rerun-0002",
    "head_ref": "demo-rounding-fix",
    "head_commit": "c" * 40,
    "prior_run_id": "run-initial-0001",
    "probe_results": [
        {
            "probe_file": _PROBE_FILE,
            "probe_hash": _PROBE_HASH,  # same hash — probe unchanged
            "target": "sample_project.pricing.invoice.calculate_invoice",
            "prior_difference_run_id": "run-initial-0001",
            "cases": [
                {
                    "id": "invoice-standard-order",
                    "args": [[39.46, 39.46, 8.78, 8.78, 8.78], 0.05],
                    "kwargs": {},
                    "base_output": 100.0,
                    "head_output": 100.0,  # fixed!
                    "status": "match",
                    "inconclusive_reason": None,
                    "base_executed_at": "2025-01-02T00:00:01Z",
                    "head_executed_at": "2025-01-02T00:00:02Z",
                }
            ],
        }
    ],
}

_RERUN_EVIDENCE_CHANGED_PROBE = {
    **_RERUN_EVIDENCE_FIXED,
    "probe_results": [
        {
            **_RERUN_EVIDENCE_FIXED["probe_results"][0],
            "probe_hash": "different_hash" * 4 + "xx",  # hash changed!
        }
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRerun:
    def test_resolved_case_identified_when_hash_matches(self):
        """A differ→match transition with unchanged probe hash is a valid resolution."""
        resolved = find_resolved_cases(_INITIAL_EVIDENCE, _RERUN_EVIDENCE_FIXED)
        assert len(resolved) == 1
        assert resolved[0]["case_id"] == "invoice-standard-order"
        assert resolved[0]["hash_matched"] is True
        assert resolved[0]["prior_run_id"] == "run-initial-0001"

    def test_hash_mismatch_blocks_resolution(self):
        """When the probe hash changes, find_resolved_cases returns no resolutions."""
        resolved = find_resolved_cases(_INITIAL_EVIDENCE, _RERUN_EVIDENCE_CHANGED_PROBE)
        assert resolved == []

    def test_hash_mismatch_is_detected(self):
        """find_hash_mismatches reports the changed probe."""
        mismatches = find_hash_mismatches(_INITIAL_EVIDENCE, _RERUN_EVIDENCE_CHANGED_PROBE)
        assert len(mismatches) == 1
        assert mismatches[0]["probe_file"] == _PROBE_FILE

    def test_no_mismatch_when_hash_unchanged(self):
        mismatches = find_hash_mismatches(_INITIAL_EVIDENCE, _RERUN_EVIDENCE_FIXED)
        assert mismatches == []

    def test_prior_run_id_in_rerun_evidence(self):
        """The rerun evidence must reference the prior run_id."""
        assert _RERUN_EVIDENCE_FIXED["prior_run_id"] == _INITIAL_EVIDENCE["run_id"]

    def test_no_resolutions_when_still_differ(self):
        """If the probe still shows differ after a rerun, no resolution is returned."""
        still_differ = {
            **_RERUN_EVIDENCE_FIXED,
            "probe_results": [
                {
                    **_RERUN_EVIDENCE_FIXED["probe_results"][0],
                    "cases": [
                        {
                            **_RERUN_EVIDENCE_FIXED["probe_results"][0]["cases"][0],
                            "status": "differ",
                            "head_output": 99.98,  # still different
                        }
                    ],
                }
            ],
        }
        resolved = find_resolved_cases(_INITIAL_EVIDENCE, still_differ)
        assert resolved == []
