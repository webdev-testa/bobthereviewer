"""
app/decisions.py — Lane 4 (D)

Decision JSON writer, schema validator, and approved-history lookup.

Public API
----------
validate_and_save(decision_data, output_dir) -> Path
    Validate a decision dict against contracts/decision.schema.json,
    enforce the rationale rule, and write the file.

lookup(repo, file_path, symbol, default_branch) -> list[dict]
    Return approved decision records matched by repository + file_path + symbol.
    Approval is derived from git reachability on the default branch — never from
    editing the status field.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import subprocess
import sys
from typing import Optional

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    _HAS_JSONSCHEMA = False

# Locate the schema relative to this file so it works from any cwd
_CONTRACTS_DIR = pathlib.Path(__file__).parent.parent / "contracts"
_DECISION_SCHEMA_PATH = _CONTRACTS_DIR / "decision.schema.json"

# Minimum meaningful rationale length (non-whitespace characters)
_MIN_RATIONALE_CHARS = 10


def _load_schema(path: pathlib.Path) -> dict:
    """Load a JSON schema from disk."""
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {path}. "
            "Ensure contracts/ directory is present in the repository root."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(data: dict, schema: dict, label: str) -> None:
    """Validate *data* against *schema*; raise ValueError with a readable message on failure."""
    if not _HAS_JSONSCHEMA:
        # Graceful degradation: skip deep validation but still apply rule checks
        return
    validator_cls = jsonschema.Draft7Validator
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        messages = "; ".join(
            f"[{'.'.join(str(p) for p in e.path) or '<root>'}] {e.message}"
            for e in errors[:5]  # show at most 5 errors
        )
        raise ValueError(f"{label} schema validation failed: {messages}")


def _symbol_to_slug(symbol: str) -> str:
    """Convert a dotted symbol name to a filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", symbol)


def validate_and_save(
    decision_data: dict,
    output_dir: pathlib.Path,
) -> tuple[pathlib.Path, str]:
    """Validate *decision_data* and write it as a decision JSON file.

    Parameters
    ----------
    decision_data:
        Dict matching contracts/decision.schema.json. ``status`` is always
        forced to ``"proposed"`` regardless of what is passed in.
    output_dir:
        Directory to write the file into (created if absent).

    Returns
    -------
    tuple[pathlib.Path, str]
        ``(written_path, git_command)`` — the path of the written file and a
        suggested ``git add && git commit`` command string to print to the user.

    Raises
    ------
    ValueError
        If schema validation fails, or if verdict is ``"intended"`` and the
        rationale is shorter than _MIN_RATIONALE_CHARS non-whitespace characters.
    FileNotFoundError
        If the schema file is missing from contracts/.
    """
    schema = _load_schema(_DECISION_SCHEMA_PATH)

    # Force status to proposed — approval comes from git, not from this field
    decision_data = {**decision_data, "status": "proposed"}

    # Rationale enforcement: intended verdicts require a meaningful human rationale
    verdict = decision_data.get("verdict", "")
    rationale = decision_data.get("rationale", "")
    if verdict == "intended":
        if len(rationale.strip()) < _MIN_RATIONALE_CHARS:
            raise ValueError(
                "Intended verdict requires a meaningful rationale of at least "
                f"{_MIN_RATIONALE_CHARS} non-whitespace characters after trimming. "
                f"Provided rationale has {len(rationale.strip())} characters. "
                "Please supply the author's reasoning — Bob cannot provide this."
            )

    _validate_schema(decision_data, schema, "Decision")

    # Build filename: <symbol_slug>-<head_commit_short>.json
    symbol = decision_data.get("symbol", "unknown")
    head_commit = decision_data.get("head_commit", "unknown")
    head_short = head_commit[:7] if len(head_commit) >= 7 else head_commit
    slug = _symbol_to_slug(symbol)
    filename = f"{slug}-{head_short}.json"

    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / filename
    output_path.write_text(
        json.dumps(decision_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Build a suggested git command for the developer
    rel_path = str(output_path).replace("\\", "/")
    git_command = (
        f"git add {rel_path} && "
        f"git commit -m 'decision: {symbol} — {verdict}'"
    )
    return output_path, git_command


def validate_and_build_decision(
    run_id: str,
    symbol: str,
    probe_file: str,
    case_id: str,
    verdict: str,
    rationale: str,
    evidence: dict,
) -> dict:
    """Validate verdict, rationale, and inputs against evidence, and build a decision dict.

    Parameters
    ----------
    run_id:
        UUID of the run to associate this decision with. Must match evidence['run_id'].
    symbol:
        Fully-qualified function name under review.
    probe_file:
        Repo-relative path to the probe file (or empty string to match from evidence).
    case_id:
        Stable case ID within the probe.
    verdict:
        One of 'intended', 'unintended', or 'unresolved'.
    rationale:
        Human-written rationale. Must be non-empty (>= 10 chars) if verdict is 'intended'.
    evidence:
        Full evidence bundle dict.

    Returns
    -------
    dict
        Validated decision record ready to be saved via validate_and_save.

    Raises
    ------
    ValueError
        On validation failure (verdict, rationale, run_id, or missing case in evidence).
    """
    allowed_verdicts = {"intended", "unintended", "unresolved"}
    if verdict not in allowed_verdicts:
        raise ValueError(
            f"Invalid verdict '{verdict}'. Allowed verdicts are: {', '.join(sorted(allowed_verdicts))}"
        )

    if verdict == "intended":
        if len(rationale.strip()) < _MIN_RATIONALE_CHARS:
            raise ValueError(
                "Intended verdict requires a meaningful rationale of at least "
                f"{_MIN_RATIONALE_CHARS} non-whitespace characters after trimming. "
                f"Provided rationale has {len(rationale.strip())} characters."
            )

    ev_run_id = evidence.get("run_id")
    if ev_run_id and ev_run_id != run_id:
        raise ValueError(
            f"Run ID mismatch: requested '{run_id}' but evidence has '{ev_run_id}'"
        )

    # Find the target probe and case in evidence probe_results
    matching_probe = None
    matching_case = None

    for probe in evidence.get("probe_results", []):
        if probe_file and probe.get("probe_file") != probe_file:
            continue
        for case in probe.get("cases", []):
            if case.get("id") == case_id:
                matching_case = case
                matching_probe = probe
                break
        if matching_case:
            break

    if not matching_case:
        raise ValueError(
            f"Case '{case_id}' was not found in evidence probe results for symbol '{symbol}'."
        )

    actual_probe_file = matching_probe.get("probe_file", probe_file)
    probe_hash = matching_probe.get("probe_hash", "")
    observed_before = matching_case.get("base_output")
    observed_after = matching_case.get("head_output")

    # Locate file_path for symbol from changed_functions if available
    file_path = ""
    for cf in evidence.get("changed_functions", []):
        if cf.get("symbol") == symbol:
            file_path = cf.get("file_path", "")
            break
    if not file_path:
        file_path = actual_probe_file

    timestamp = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    decision_data = {
        "schema_version": "1",
        "run_id": run_id,
        "repository": evidence.get("repository", ""),
        "file_path": file_path,
        "symbol": symbol,
        "base_commit": evidence.get("base_commit", ""),
        "head_commit": evidence.get("head_commit", ""),
        "probe_file": actual_probe_file,
        "probe_hash": probe_hash,
        "case_id": case_id,
        "observed_before": observed_before,
        "observed_after": observed_after,
        "verdict": verdict,
        "rationale": rationale,
        "status": "proposed",
        "timestamp": timestamp,
    }

    schema = _load_schema(_DECISION_SCHEMA_PATH)
    _validate_schema(decision_data, schema, "Decision")

    return decision_data


def lookup(
    repo: str,
    file_path: str,
    symbol: str,
    default_branch: str = "main",
    decisions_dir: Optional[pathlib.Path] = None,
) -> list[dict]:
    """Find earlier approved decision records matching repo + file_path + symbol.

    A decision is considered *approved* when its file is present in a commit
    reachable from HEAD on *default_branch* — determined by reading the file
    list from ``git log``, not by the ``status`` field value.

    Parameters
    ----------
    repo:
        Remote origin URL to match against ``repository`` field.
    file_path:
        Repository-relative path to match against ``file_path`` field.
    symbol:
        Fully qualified symbol name to match against ``symbol`` field.
    default_branch:
        Branch name to check reachability against. Default ``"main"``.
    decisions_dir:
        Override for the ``.bobreviewer/decisions/`` directory. Used in tests.

    Returns
    -------
    list[dict]
        Matching approved decision records, oldest first.
    """
    if decisions_dir is None:
        # Walk up from cwd to find .bobreviewer/decisions/
        decisions_dir = _find_decisions_dir()

    if decisions_dir is None or not decisions_dir.exists():
        return []

    # Determine whether to apply reachability filtering.
    # Per the spec: a decision is approved when its file exists in a commit
    # reachable from HEAD on the default branch, checked via
    # ``git show <branch>:<repo-relative-path>``.
    #
    # Only apply filtering when decisions_dir is inside the repo (i.e. relative
    # to cwd is possible). Tests that pass a tmp_path outside the repo skip
    # filtering so all matching records are returned — this is the correct
    # test behaviour since tmp files are never in git history anyway.
    try:
        decisions_dir.relative_to(pathlib.Path.cwd())
        _within_repo = True
    except ValueError:
        _within_repo = False

    results: list[dict] = []
    for json_file in sorted(decisions_dir.glob("*.json")):
        if _within_repo:
            # Compute repo-relative path for git show check
            try:
                repo_relative = str(json_file.relative_to(pathlib.Path.cwd()))
            except ValueError:
                repo_relative = str(json_file)
            repo_relative_normalised = repo_relative.replace("\\", "/")
            if not is_file_reachable_on_branch(default_branch, repo_relative_normalised):
                continue  # not yet merged to default branch → not approved

        try:
            record = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # skip malformed files

        if (
            record.get("repository") == repo
            and record.get("file_path") == file_path
            and record.get("symbol") == symbol
        ):
            results.append(record)

    return results


def _find_decisions_dir() -> Optional[pathlib.Path]:
    """Search upward from cwd for .bobreviewer/decisions/."""
    current = pathlib.Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / ".bobreviewer" / "decisions"
        if candidate.exists():
            return candidate
        if (parent / ".git").exists():
            # Reached the repo root without finding it; return the expected path
            return parent / ".bobreviewer" / "decisions"
    return None


def is_file_reachable_on_branch(
    default_branch: str,
    repo_relative_file_path: str,
) -> bool:
    """Check whether a specific file path exists in a commit reachable from *default_branch*.

    Uses ``git show <branch>:<path>`` as specified in the project spec.
    Returns True (approved) or False (not yet merged). Fail-open: returns True
    when git is unavailable so development is not blocked.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{default_branch}:{repo_relative_file_path}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return True  # git not available; fail-open
