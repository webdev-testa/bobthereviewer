"""
bobreviewer.contracts
~~~~~~~~~~~~~~~~~~~~~
Canonical contract definitions and validators for all shared data structures.

Usage::

    from bobreviewer.contracts import validate_probe, validate_evidence, ContractError

    try:
        validate_probe(data)
    except ContractError as exc:
        print(exc)   # human-readable message

All public functions accept a plain dict and return it unchanged on success.
They raise ContractError with a human-readable message on any schema violation.
They never mutate the supplied dict.

Absolute filesystem paths must never appear in published evidence or decision
records.  validate_evidence() enforces this as an additional check beyond the
JSON Schema.

Ownership note: Lane 1 maintains this module and the canonical schema files
under contracts/.  No other lane may modify either without Lane 1 review.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

try:
    import jsonschema
    from jsonschema import Draft7Validator
    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    _HAS_JSONSCHEMA = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_CONTRACTS_DIR = files("bobthereviewer").joinpath("schemas")

_SCHEMA_FILES = {
    "config":          _CONTRACTS_DIR / "config.schema.json",
    "probe":           _CONTRACTS_DIR / "probe.schema.json",
    "evidence":        _CONTRACTS_DIR / "evidence.schema.json",
    "decision":        _CONTRACTS_DIR / "decision.schema.json",
    "progress_event":  _CONTRACTS_DIR / "progress-event.schema.json",
    "run_metadata":    _CONTRACTS_DIR / "run-metadata.schema.json",
    "repo_map":        _CONTRACTS_DIR / "repo-map.schema.json",
}

_SCHEMA_CACHE: dict[str, Any] = {}


def _load_schema(name: str) -> Any:
    if name not in _SCHEMA_CACHE:
        path = _SCHEMA_FILES[name]
        with path.open(encoding="utf-8") as fh:
            _SCHEMA_CACHE[name] = json.load(fh)
    return _SCHEMA_CACHE[name]


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class ContractError(ValueError):
    """A data structure violates a bobreviewer contract schema.

    The string representation is human-readable and suitable for printing
    directly to a terminal without a Python traceback.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate(name: str, data: Any) -> Any:
    """Validate *data* against the named schema; raise ContractError on failure."""
    if not _HAS_JSONSCHEMA:
        raise RuntimeError(
            "jsonschema is required for contract validation. "
            "Install it with: pip install jsonschema"
        )
    schema = _load_schema(name)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"Contract violation in '{name}':"]
        for err in errors:
            path = " -> ".join(str(p) for p in err.absolute_path) or "<root>"
            lines.append(f"  [{path}] {err.message}")
        raise ContractError("\n".join(lines))
    return data


_ABS_PATH_RE = re.compile(
    r"(?:"
    r"^[A-Za-z]:[/\\]"   # Windows absolute: C:\...
    r"|"
    r"^/(?!/)(?!\s)"      # POSIX absolute: /usr/...  (not // protocol)
    r")"
)


def _check_no_absolute_paths(data: Any, path: str = "") -> None:
    """Recursively verify no string value looks like an absolute filesystem path."""
    if isinstance(data, str):
        if _ABS_PATH_RE.match(data):
            raise ContractError(
                f"Absolute filesystem path found at '{path}': {data!r}\n"
                "Published evidence must use repo-relative paths only."
            )
    elif isinstance(data, dict):
        for k, v in data.items():
            _check_no_absolute_paths(v, f"{path}.{k}" if path else k)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            _check_no_absolute_paths(item, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Public validators
# ---------------------------------------------------------------------------

def validate_config(data: Any) -> Any:
    """Validate a project config dict. Returns *data* unchanged."""
    return _validate("config", data)


def validate_probe(data: Any) -> Any:
    """Validate a probe dict. Returns *data* unchanged."""
    return _validate("probe", data)


def validate_evidence(data: Any) -> Any:
    """Validate an evidence bundle dict.

    Also checks that no string value is an absolute filesystem path, since
    the spec prohibits absolute paths in published evidence.
    """
    _validate("evidence", data)
    _check_no_absolute_paths(data)
    return data


def validate_decision(data: Any) -> Any:
    """Validate a decision dict.

    Enforces the conditional constraint: verdict=intended requires non-empty
    rationale.  This constraint is expressed in the JSON Schema via if/then
    but is also checked here for a clearer error message.
    """
    _validate("decision", data)
    if data.get("verdict") == "intended" and not data.get("rationale", "").strip():
        raise ContractError(
            "Contract violation in 'decision':\n"
            "  [rationale] must not be empty when verdict is 'intended'"
        )
    return data


def validate_progress_event(data: Any) -> Any:
    """Validate a progress event dict. Returns *data* unchanged."""
    return _validate("progress_event", data)


def validate_run_metadata(data: Any) -> Any:
    """Validate a run-metadata dict. Returns *data* unchanged."""
    return _validate("run_metadata", data)


# ---------------------------------------------------------------------------
# Schema self-check (used by tests and CI)
# ---------------------------------------------------------------------------

def check_schemas() -> None:
    """Verify all canonical schema files are themselves valid JSON Schema Draft 7.

    Raises ContractError if any schema file is missing or malformed.
    """
    if not _HAS_JSONSCHEMA:
        raise RuntimeError("jsonschema required")
    meta = Draft7Validator.META_SCHEMA
    for name, path in _SCHEMA_FILES.items():
        if not path.exists():
            raise ContractError(f"Schema file missing: {path}")
        schema = _load_schema(name)
        try:
            Draft7Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise ContractError(
                f"Schema '{name}' is not valid Draft 7: {exc.message}"
            ) from exc
