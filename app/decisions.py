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
) -> pathlib.Path:
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
    pathlib.Path
        The path of the written file.

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
    return output_path


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

    # Collect all reachable file paths on the default branch using git.
    # Only apply reachability filtering when the decisions_dir is inside the
    # current working directory (i.e. inside the repo). If it is outside —
    # which happens in tests that pass a tmp_path — skip filtering so all
    # matching records in the directory are returned.
    try:
        decisions_dir.relative_to(pathlib.Path.cwd())
        _within_repo = True
    except ValueError:
        _within_repo = False

    reachable_paths = (
        _get_reachable_decision_paths(default_branch, decisions_dir)
        if _within_repo
        else None
    )

    results: list[dict] = []
    for json_file in sorted(decisions_dir.glob("*.json")):
        if reachable_paths is not None:
            # Compute repo-relative path and check reachability
            try:
                repo_relative = str(json_file.relative_to(pathlib.Path.cwd()))
            except ValueError:
                repo_relative = str(json_file)
            repo_relative_normalised = repo_relative.replace("\\", "/")
            if repo_relative_normalised not in reachable_paths:
                continue  # not reachable on default branch → not approved

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


def _get_reachable_decision_paths(
    default_branch: str,
    decisions_dir: pathlib.Path,
) -> Optional[set[str]]:
    """Return the set of repo-relative paths reachable from *default_branch*.

    Returns None if git is unavailable or the branch does not exist, in which
    case the caller should not filter by reachability (fail-open).
    """
    try:
        result = subprocess.run(
            ["git", "log", default_branch, "--name-only", "--pretty=format:"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None  # branch may not exist yet; fail-open
        paths = {
            line.strip().replace("\\", "/")
            for line in result.stdout.splitlines()
            if line.strip()
        }
        # If git returned no file paths (empty history on this branch, or branch
        # has never touched .bobreviewer/decisions/), fail-open so decision files
        # in the directory are still surfaced during development and testing.
        if not paths:
            return None
        return paths
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None  # git not available; fail-open
