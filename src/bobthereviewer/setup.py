"""
bobthereviewer.setup
~~~~~~~~~~~~~~~~~~~~
Init and doctor commands for first-time project setup.

init
  - Resolves repository root
  - Detects base branch, test directory, Python environment
  - Writes .bobreviewer/config.json (idempotent: preserves existing fields)
  - Optionally updates .gitignore with .bobreviewer/runs/ entry
  - Returns a structured SetupResult (never prints; caller formats output)

doctor
  - Checks git, Python, pytest, config file, probe file validity
  - Returns a structured DoctorResult (never prints; caller formats output)
  - Does NOT install, run, or write anything

Ownership: Lane 1.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bobthereviewer.contracts import ContractError, validate_config
from bobthereviewer.snapshots import SnapshotError, find_repo_root, _git


# ---------------------------------------------------------------------------
# Default detection helpers
# ---------------------------------------------------------------------------

_TEST_DIR_CANDIDATES = ["tests", "test", "src/tests"]
_PYTHON_ENV_CANDIDATES = [".venv/bin/python", ".venv/Scripts/python.exe", "python", "python3"]


def _detect_base_branch(repo_root: Path) -> str:
    """Return the default branch name, falling back to 'main'."""
    for name in ("main", "master", "trunk", "develop"):
        try:
            _git(["rev-parse", "--verify", name], cwd=repo_root)
            return name
        except SnapshotError:
            pass
    return "main"


def _detect_test_dir(repo_root: Path) -> str | None:
    for candidate in _TEST_DIR_CANDIDATES:
        if (repo_root / candidate).is_dir():
            return candidate
    return None


def _detect_python_env(repo_root: Path) -> str:
    for candidate in _PYTHON_ENV_CANDIDATES:
        path = repo_root / candidate
        if path.exists():
            return str(path.relative_to(repo_root)).replace("\\", "/")
    return sys.executable or "python"


def _detect_remote_url(repo_root: Path) -> str | None:
    try:
        return _git(["remote", "get-url", "origin"], cwd=repo_root)
    except SnapshotError:
        return None


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

@dataclass
class SetupResult:
    config_path: Path
    created: list[str] = field(default_factory=list)    # things we wrote/created
    preserved: list[str] = field(default_factory=list)  # things we left unchanged
    skipped: list[str] = field(default_factory=list)    # things we did not do


def init(
    repo_dir: Path,
    update_gitignore: bool = True,
) -> SetupResult:
    """Initialise .bobreviewer/ for a repository.

    Safe to run multiple times: existing config fields are preserved.
    """
    repo_root = find_repo_root(repo_dir.resolve())
    br_dir = repo_root / ".bobreviewer"
    br_dir.mkdir(exist_ok=True)

    config_path = br_dir / "config.json"

    # Load existing config (if any)
    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    result = SetupResult(config_path=config_path)

    # Build the new config, preserving existing values
    new_config: dict[str, Any] = {"schema_version": "1"}

    def _set(key: str, detected: Any) -> None:
        if key in existing:
            new_config[key] = existing[key]
            result.preserved.append(key)
        else:
            new_config[key] = detected
            result.created.append(key)

    _set("base_branch", _detect_base_branch(repo_root))
    test_dir = _detect_test_dir(repo_root)
    if test_dir:
        _set("test_dir", test_dir)
    _set("python_env", _detect_python_env(repo_root))
    _set("probe_dir", ".bobreviewer/probes")

    # Validate before writing
    try:
        validate_config(new_config)
    except ContractError:
        # Detected values are always valid by construction; this guards
        # against a corrupted existing config
        new_config = {k: new_config[k] for k in new_config if k in {"schema_version", "base_branch", "python_env", "probe_dir"}}
        validate_config(new_config)

    config_path.write_text(
        json.dumps(new_config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if config_path.name not in result.created:
        result.created.append("config.json")

    # Create subdirectories
    for subdir in ("probes", "decisions"):
        d = br_dir / subdir
        if not d.exists():
            d.mkdir(exist_ok=True)
            result.created.append(f".bobreviewer/{subdir}/")
        else:
            result.preserved.append(f".bobreviewer/{subdir}/")

    # Update .gitignore
    if update_gitignore:
        gitignore_path = repo_root / ".gitignore"
        run_entry = ".bobreviewer/runs/"
        if gitignore_path.exists():
            content = gitignore_path.read_text(encoding="utf-8")
            if run_entry not in content:
                with gitignore_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n# bobthereviewer local run history\n{run_entry}\n")
                result.created.append(".gitignore (added run entry)")
            else:
                result.preserved.append(".gitignore (run entry already present)")
        else:
            gitignore_path.write_text(
                f"# bobthereviewer local run history\n{run_entry}\n",
                encoding="utf-8",
            )
            result.created.append(".gitignore")

    return result


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

@dataclass
class CheckItem:
    name: str
    status: str     # "ok" | "missing" | "warning"
    detail: str


@dataclass
class DoctorResult:
    checks: list[CheckItem] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(c.status == "ok" for c in self.checks)


def doctor(repo_dir: Path) -> DoctorResult:
    """Check project readiness without installing, running, or writing anything."""
    result = DoctorResult()

    def _add(name: str, status: str, detail: str) -> None:
        result.checks.append(CheckItem(name=name, status=status, detail=detail))

    # ---- Git ----
    git_path = shutil.which("git")
    if git_path:
        try:
            ver = _git(["--version"], cwd=repo_dir)
            _add("git", "ok", ver)
        except SnapshotError as e:
            _add("git", "warning", str(e))
    else:
        _add("git", "missing", "git not found on PATH — install git and retry")

    # ---- Repository ----
    try:
        repo_root = find_repo_root(repo_dir.resolve())
        _add("repository", "ok", f"root at {repo_root}")
    except SnapshotError as e:
        _add("repository", "missing", str(e))
        return result  # can't check anything else without a repo

    # ---- Python ----
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        _add("python", "ok", f"Python {py_ver}")
    else:
        _add("python", "warning", f"Python {py_ver} found; 3.11+ required")

    # ---- pytest ----
    pytest_path = shutil.which("pytest")
    if pytest_path:
        _add("pytest", "ok", pytest_path)
    else:
        # Try via python -m pytest
        try:
            subprocess.run(
                [sys.executable, "-m", "pytest", "--version"],
                capture_output=True, check=True,
            )
            _add("pytest", "ok", "available as python -m pytest")
        except (subprocess.CalledProcessError, FileNotFoundError):
            _add("pytest", "missing",
                 "pytest not found — install with: pip install pytest")

    # ---- Config ----
    config_path = repo_root / ".bobreviewer" / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            validate_config(data)
            _add("config", "ok", str(config_path.relative_to(repo_root)))
        except (json.JSONDecodeError, ContractError) as e:
            _add("config", "warning",
                 f"config.json exists but is invalid: {e}\n"
                 "Run 'bobreviewer init' to recreate it.")
    else:
        _add("config", "missing",
             "No .bobreviewer/config.json — run 'bobreviewer init' first")

    # ---- Probe directory ----
    probe_dir = repo_root / ".bobreviewer" / "probes"
    if probe_dir.exists():
        probe_files = list(probe_dir.glob("*.json"))
        _add("probes", "ok",
             f"{len(probe_files)} probe file(s) in {probe_dir.relative_to(repo_root)}")
    else:
        _add("probes", "warning",
             "No .bobreviewer/probes/ directory — create probes or run 'bobreviewer init'")

    return result
