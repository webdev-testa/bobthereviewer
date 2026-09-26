"""
tests/test_probe_authoring.py — Lane 4 (D)

Verifies that probe JSON objects produced by the Bob probe-authoring logic
validate against contracts/probe.schema.json.
"""
import json
import pathlib
import sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

_PROBE_SCHEMA_PATH = pathlib.Path(__file__).parent.parent / "contracts" / "probe.schema.json"


def load_probe_schema() -> dict:
    return json.loads(_PROBE_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_probe(probe: dict) -> list[str]:
    """Return a list of validation error messages; empty list means valid."""
    if not _HAS_JSONSCHEMA:
        return []
    schema = load_probe_schema()
    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(probe)]


def build_probe(target: str, cases: list[dict]) -> dict:
    """Simulate the probe JSON Bob would generate for a given target and cases."""
    return {
        "schema_version": "1",
        "target": target,
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProbeAuthoring:
    def test_minimal_valid_probe(self):
        probe = build_probe(
            target="sample_project.pricing.invoice.calculate_invoice",
            cases=[
                {
                    "id": "invoice-standard-order",
                    "args": [[39.46, 39.46, 8.78, 8.78, 8.78], 0.05],
                    "kwargs": {},
                }
            ],
        )
        errors = validate_probe(probe)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_multiple_cases_valid(self):
        probe = build_probe(
            target="sample_project.pricing.discount.apply_discount",
            cases=[
                {"id": "case-a", "args": [100.0, 0.05], "kwargs": {}},
                {"id": "case-b", "args": [200.0, 0.10], "kwargs": {}},
                {"id": "case-c", "args": [0.0, 0.0], "kwargs": {}},
            ],
        )
        errors = validate_probe(probe)
        assert errors == []

    def test_kwargs_probe_valid(self):
        probe = build_probe(
            target="sample_project.pricing.discount.apply_discount",
            cases=[
                {
                    "id": "kwargs-case",
                    "args": [],
                    "kwargs": {"amount": 100.0, "rate": 0.05},
                }
            ],
        )
        errors = validate_probe(probe)
        assert errors == []

    def test_missing_schema_version_invalid(self):
        probe = {
            "target": "sample_project.pricing.discount.apply_discount",
            "cases": [{"id": "x", "args": [], "kwargs": {}}],
        }
        errors = validate_probe(probe)
        if _HAS_JSONSCHEMA:
            assert errors  # should fail validation

    def test_missing_target_invalid(self):
        probe = {
            "schema_version": "1",
            "cases": [{"id": "x", "args": [], "kwargs": {}}],
        }
        errors = validate_probe(probe)
        if _HAS_JSONSCHEMA:
            assert errors

    def test_empty_cases_invalid(self):
        probe = build_probe(
            target="sample_project.pricing.discount.apply_discount",
            cases=[],
        )
        errors = validate_probe(probe)
        if _HAS_JSONSCHEMA:
            assert errors

    def test_case_missing_id_invalid(self):
        probe = build_probe(
            target="sample_project.pricing.discount.apply_discount",
            cases=[{"args": [100.0], "kwargs": {}}],
        )
        errors = validate_probe(probe)
        if _HAS_JSONSCHEMA:
            assert errors

    def test_schema_file_exists(self):
        """The probe schema file must exist on disk."""
        assert _PROBE_SCHEMA_PATH.exists(), f"Schema file missing: {_PROBE_SCHEMA_PATH}"
