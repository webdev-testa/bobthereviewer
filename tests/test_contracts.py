"""
Tests for bobreviewer.contracts — Slice 1.

These tests verify:
- All schema files are valid Draft 7
- Each validator accepts its representative fixture
- Each validator rejects known-invalid inputs with a human-readable ContractError
- The evidence validator rejects absolute filesystem paths
- The decision validator enforces the intended/rationale constraint
- fixture: true is allowed in probe and evidence; not required
"""

import json
from pathlib import Path

import pytest

from bobthereviewer.contracts import (
    ContractError,
    check_schemas,
    validate_config,
    validate_decision,
    validate_evidence,
    validate_probe,
    validate_progress_event,
    validate_run_metadata,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Schema self-validity
# ---------------------------------------------------------------------------

def test_all_schemas_are_valid_draft7():
    """Every canonical schema file must itself be valid JSON Schema Draft 7."""
    check_schemas()  # raises ContractError on failure


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def test_probe_fixture_is_valid():
    data = json.loads((FIXTURES_DIR / "probe_discount.json").read_text())
    validate_probe(data)


def test_probe_accepts_fixture_true():
    validate_probe({
        "schema_version": "1",
        "target": "pkg.mod.func",
        "fixture": True,
        "cases": [{"id": "c1", "args": [], "kwargs": {}}],
    })


def test_probe_accepts_without_fixture_field():
    validate_probe({
        "schema_version": "1",
        "target": "pkg.mod.func",
        "cases": [{"id": "c1", "args": [1, 2], "kwargs": {"x": 3}}],
    })


def test_probe_rejects_missing_schema_version():
    with pytest.raises(ContractError, match="schema_version"):
        validate_probe({"target": "a.b", "cases": [{"id": "x", "args": [], "kwargs": {}}]})


def test_probe_rejects_wrong_schema_version():
    with pytest.raises(ContractError, match="schema_version"):
        validate_probe({
            "schema_version": "2",
            "target": "a.b",
            "cases": [{"id": "x", "args": [], "kwargs": {}}],
        })


def test_probe_rejects_empty_target():
    with pytest.raises(ContractError, match="target"):
        validate_probe({
            "schema_version": "1",
            "target": "",
            "cases": [{"id": "x", "args": [], "kwargs": {}}],
        })


def test_probe_rejects_empty_cases():
    with pytest.raises(ContractError, match="cases"):
        validate_probe({"schema_version": "1", "target": "a.b", "cases": []})


def test_probe_rejects_case_missing_id():
    with pytest.raises(ContractError, match="id"):
        validate_probe({
            "schema_version": "1",
            "target": "a.b",
            "cases": [{"args": [], "kwargs": {}}],
        })


def test_probe_rejects_unknown_field():
    with pytest.raises(ContractError):
        validate_probe({
            "schema_version": "1",
            "target": "a.b",
            "cases": [{"id": "x", "args": [], "kwargs": {}}],
            "unexpected_key": True,
        })


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def test_evidence_fixture_is_valid():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    validate_evidence(data)


def test_evidence_accepts_fixture_true():
    """Evidence marked fixture: true must pass validation."""
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    assert data.get("fixture") is True


def test_evidence_analysis_only_nulls():
    """Analysis-only evidence has null for execution fields."""
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    data["frozen_suite_hash"] = None
    data["test_results"] = {"base": {}, "head": {}}
    data["probe_results"] = []
    validate_evidence(data)


def test_evidence_rejects_missing_run_id():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    del data["run_id"]
    with pytest.raises(ContractError, match="run_id"):
        validate_evidence(data)


def test_evidence_rejects_invalid_triage_category():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    data["triage"]["category"] = "not-a-category"
    with pytest.raises(ContractError, match="category"):
        validate_evidence(data)


def test_evidence_rejects_absolute_posix_path():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    data["changed_functions"][0]["file_path"] = "/home/user/project/discount.py"
    with pytest.raises(ContractError, match="Absolute filesystem path"):
        validate_evidence(data)


def test_evidence_rejects_absolute_windows_path():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    data["changed_functions"][0]["callers"][0]["file_path"] = "C:\\Users\\project\\invoice.py"
    with pytest.raises(ContractError, match="Absolute filesystem path"):
        validate_evidence(data)


def test_evidence_execution_status_separate_from_comparison():
    """execution_status and comparison_status must coexist correctly."""
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    case = data["probe_results"][0]["cases"][0]
    assert case["execution_status"] == "success"
    assert case["comparison_status"] == "differ"


def test_evidence_inconclusive_allows_null_comparison():
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    case = data["probe_results"][0]["cases"][0]
    case["execution_status"] = "inconclusive"
    case["comparison_status"] = None
    case["inconclusive_reason"] = "import_error"
    case["inconclusive_detail"] = "ModuleNotFoundError: No module named 'missing'"
    validate_evidence(data)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_decision_unintended_fixture_is_valid():
    data = json.loads((FIXTURES_DIR / "decision_unintended.json").read_text())
    validate_decision(data)


def test_decision_intended_fixture_is_valid():
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    validate_decision(data)


def test_decision_intended_rejects_empty_rationale():
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    data["rationale"] = ""
    with pytest.raises(ContractError, match="rationale"):
        validate_decision(data)


def test_decision_intended_rejects_whitespace_only_rationale():
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    data["rationale"] = "   "
    with pytest.raises(ContractError, match="rationale"):
        validate_decision(data)


def test_decision_unintended_allows_empty_rationale():
    data = json.loads((FIXTURES_DIR / "decision_unintended.json").read_text())
    data["rationale"] = ""
    validate_decision(data)  # no error expected


def test_decision_rejects_unknown_verdict():
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    data["verdict"] = "maybe"
    with pytest.raises(ContractError, match="verdict"):
        validate_decision(data)


def test_decision_includes_case_id():
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    assert "case_id" in data


def test_decision_history_match_fields_present():
    """Decisions must carry repository + file_path + symbol for history matching."""
    data = json.loads((FIXTURES_DIR / "decision_intended.json").read_text())
    for field in ("repository", "file_path", "symbol"):
        assert field in data, f"missing history-match field: {field}"


# ---------------------------------------------------------------------------
# Progress event
# ---------------------------------------------------------------------------

def test_progress_event_valid():
    validate_progress_event({
        "run_id": "00000000-0000-0000-0000-000000000001",
        "step": "analyze",
        "status": "started",
        "message": "Parsing ASTs",
        "timestamp": "2026-01-01T00:00:00Z",
    })


def test_progress_event_rejects_unknown_step():
    with pytest.raises(ContractError, match="step"):
        validate_progress_event({
            "run_id": "00000000-0000-0000-0000-000000000001",
            "step": "unknown_step",
            "status": "started",
            "message": "test",
            "timestamp": "2026-01-01T00:00:00Z",
        })


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_config_minimal_valid():
    validate_config({"schema_version": "1", "base_branch": "main"})


def test_config_full_valid():
    validate_config({
        "schema_version": "1",
        "base_branch": "main",
        "test_dir": "tests",
        "python_env": ".venv/bin/python",
        "probe_dir": ".bobreviewer/probes",
    })


def test_config_rejects_missing_base_branch():
    with pytest.raises(ContractError, match="base_branch"):
        validate_config({"schema_version": "1"})


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

def test_run_metadata_valid():
    validate_run_metadata({
        "run_id": "00000000-0000-0000-0000-000000000001",
        "generated_at": "2026-01-01T00:00:00Z",
        "base_ref": "demo-base",
        "head_ref": "demo-rounding-change",
        "base_commit": "a" * 40,
        "head_commit": "b" * 40,
        "triage_category": "code",
    })


def test_run_metadata_rejects_unknown_triage_category():
    with pytest.raises(ContractError, match="triage_category"):
        validate_run_metadata({
            "run_id": "00000000-0000-0000-0000-000000000001",
            "generated_at": "2026-01-01T00:00:00Z",
            "base_ref": "main",
            "head_ref": "HEAD",
            "base_commit": "a" * 40,
            "head_commit": "b" * 40,
            "triage_category": "unknown",
        })


# ---------------------------------------------------------------------------
# ContractError is human-readable
# ---------------------------------------------------------------------------

def test_contract_error_is_readable():
    """ContractError message must be plain text, no Python traceback noise."""
    try:
        validate_probe({"schema_version": "1", "target": "", "cases": []})
    except ContractError as exc:
        msg = str(exc)
        assert "Contract violation" in msg
        assert "Traceback" not in msg


def test_probe_case_that_raised_an_exception_is_valid_evidence():
    """An exception record is also a JSON object; oneOf rejected it for matching both (Act 4 crashed)."""
    data = json.loads((FIXTURES_DIR / "evidence_rounding_change.json").read_text())
    case = data["probe_results"][0]["cases"][0]
    case["base_output"] = {"exception": "ModuleNotFoundError", "message": "No module named 'tax_tables'"}
    case["head_output"] = {"exception": "ValueError", "message": "bad input"}
    validate_evidence(data)
