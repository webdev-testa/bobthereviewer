"""
bobthereviewer.decisions — Lane 4 (D)

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
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Optional

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    _HAS_JSONSCHEMA = False

# Package resources work in both editable and ordinary installations.
_DECISION_SCHEMA_PATH = files("bobthereviewer").joinpath("schemas", "decision.schema.json")

# Minimum meaningful rationale length (non-whitespace characters)
_MIN_RATIONALE_CHARS = 10


def _load_schema(path: Traversable) -> dict:
    """Load a JSON schema from disk."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Schema file not found: {path}. "
            "Reinstall bobthereviewer to restore its packaged schemas."
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

    # Build filename: <symbol_slug>[-<case_id_slug>]-<head_commit_short>.json. The case id keeps two
    # cases of one function apart; without it the second decision silently replaced the first.
    symbol = decision_data.get("symbol", "unknown")
    head_commit = decision_data.get("head_commit", "unknown")
    head_short = head_commit[:7] if len(head_commit) >= 7 else head_commit
    slug = _symbol_to_slug(symbol)
    case_id = decision_data.get("case_id")
    case_part = f"-{_symbol_to_slug(case_id)}" if case_id else ""
    filename = f"{slug}{case_part}-{head_short}.json"

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

    # Locate the file_path for the symbol. A probe often targets a caller rather than a
    # changed function (that is the whole point of probing an uncovered caller), so search
    # the callers as well before falling back. Storing the probe's own path here would make
    # the record unmatchable later: approval is keyed on the source file plus the symbol.
    file_path = ""
    for cf in evidence.get("changed_functions", []):
        if cf.get("symbol") == symbol:
            file_path = cf.get("file_path", "")
            break
        for caller in cf.get("callers", []):
            if caller.get("symbol") == symbol:
                file_path = caller.get("file_path", "")
                break
        if file_path:
            break
    if not file_path:
        # Last resort: the probe's target module, as a repo-relative source path.
        stem = actual_probe_file.rsplit("/", 1)[-1].removesuffix(".json")
        file_path = f"{stem}.py" if stem else actual_probe_file

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
    repo_root: Optional[pathlib.Path] = None,
) -> list[dict]:
    """Find earlier approved decision records matching repo + file_path + symbol.

    A decision is considered *approved* when its file is present in a commit reachable from
    HEAD on *default_branch* — determined by reading the file from git, not by the ``status``
    field value.

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
    repo_root:
        Repository root used to compute repo-relative paths for the reachability check.
        Pass this explicitly: deriving it from the current directory makes the answer depend
        on where the process happens to be started, which is how an unmerged decision can be
        reported as approved.

    Returns
    -------
    list[dict]
        Matching approved decision records, oldest first.
    """
    root = pathlib.Path(repo_root) if repo_root is not None else _git_toplevel()
    if decisions_dir is None:
        # Look for .bobreviewer/decisions/ at the repository root, not at the cwd.
        decisions_dir = root / ".bobreviewer" / "decisions"

    if decisions_dir is None or not decisions_dir.exists():
        return []

    results: list[dict] = []
    for json_file in sorted(decisions_dir.glob("*.json")):
        # Only a decision reachable on the default branch counts as approved. A decision
        # merely present on a feature branch was proposed and never reviewed.
        try:
            repo_relative = json_file.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            # Outside the repository (tests use tmp dirs): no git history to check, so the
            # reachability rule cannot apply and records are returned for rule testing.
            repo_relative = None
        if repo_relative is not None and not is_file_reachable_on_branch(
            default_branch, repo_relative, cwd=root
        ):
            continue

        try:
            record = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # skip malformed files

        if (
            same_repository(record.get("repository"), repo)
            and record.get("file_path") == file_path
            and record.get("symbol") == symbol
        ):
            results.append(record)

    return results


def _branch_ref(branch: str, cwd: Optional[pathlib.Path]) -> str:
    """The ref that names *branch* here: the local branch, else its origin copy.

    CI checks out a pull request without a local ``main``; only ``origin/main`` exists there, so
    reading ``main:<path>`` found no approved decisions at all.
    """
    for ref in (branch, f"origin/{branch}"):
        try:
            found = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                capture_output=True, text=True, timeout=10, cwd=str(cwd) if cwd is not None else None,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return branch
        if found.returncode == 0:
            return ref
    return branch


def load_branch_decisions(
    default_branch: str = "main",
    repo_root: Optional[pathlib.Path] = None,
) -> list[dict]:
    """Every decision record present on *default_branch*, read from git.

    Approval is a question about history, not about the current checkout: a decision is
    approved when it is reachable on the default branch, even if the working tree happens to
    be on a branch that does not contain it. Enumerating the branch's tree (rather than the
    filesystem) is what makes that true.
    """
    root = pathlib.Path(repo_root) if repo_root is not None else _git_toplevel()
    branch_ref = _branch_ref(default_branch, root)
    try:
        listed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", branch_ref, "--", ".bobreviewer/decisions"],
            capture_output=True, text=True, timeout=10, cwd=str(root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if listed.returncode != 0:
        return []

    records: list[dict] = []
    for relative in listed.stdout.splitlines():
        relative = relative.strip()
        if not relative.endswith(".json"):
            continue
        try:
            blob = subprocess.run(
                ["git", "show", f"{branch_ref}:{relative}"],
                capture_output=True, text=True, timeout=10, cwd=str(root),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
        if blob.returncode != 0:
            continue
        try:
            record = json.loads(blob.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("symbol"):
            records.append(record)
    return records


def same_repository(a: str | None, b: str | None) -> bool:
    """Whether two remote URLs name the same repository.

    A decision recorded locally stores the remote as `git remote` prints it (often with `.git`),
    while the GitHub Action checks out without it; an exact match hid every approved decision.
    """
    def normal(url: str | None) -> str:
        return (url or "").strip().rstrip("/").removesuffix(".git").lower()
    return normal(a) == normal(b)


def approved_for_symbols(
    repo: str,
    symbols: dict[str, str],
    default_branch: str = "main",
    repo_root: Optional[pathlib.Path] = None,
) -> list[dict]:
    """Approved decisions for a mapping of ``symbol -> file_path``.

    Uses :func:`load_branch_decisions`, so the answer depends on the default branch's history
    and never on which branch happens to be checked out. Matches on repository + file_path +
    symbol, which keeps two same-named functions in different files apart.
    """
    wanted = {(path, symbol) for symbol, path in symbols.items()}
    matched: list[dict] = []
    for record in load_branch_decisions(default_branch, repo_root):
        key = (record.get("file_path"), record.get("symbol"))
        if key in wanted and same_repository(record.get("repository", repo), repo):
            matched.append(record)
    return matched


def _git_toplevel() -> pathlib.Path:
    """The repository root for the current directory, or cwd when git cannot say."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return pathlib.Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return pathlib.Path.cwd()


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
    cwd: Optional[pathlib.Path] = None,
) -> bool:
    """Check whether a specific file path exists in a commit reachable from *default_branch*.

    Uses ``git show <branch>:<path>``, run in the repository root so the answer does not
    depend on the caller's working directory. Returns False when the file is not there, which
    is what keeps an unmerged decision from being reported as approved.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{_branch_ref(default_branch, cwd)}:{repo_relative_file_path}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(cwd) if cwd is not None else None,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
