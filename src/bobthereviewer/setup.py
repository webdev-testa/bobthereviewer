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

from bobthereviewer.contracts import ContractError, validate_config
from bobthereviewer.snapshots import SnapshotError, find_repo_root, _git


# ---------------------------------------------------------------------------
# Default detection helpers
# ---------------------------------------------------------------------------

_TEST_DIR_CANDIDATES = ["tests", "test", "src/tests"]
_PYTHON_ENV_CANDIDATES = [".venv/bin/python", ".venv/Scripts/python.exe", "python", "python3"]


def _detect_base_branch(repo_root: Path) -> str:
    """Return the default branch name, falling back to 'main'."""
    try:
        return _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo_root).removeprefix("origin/")
    except SnapshotError:
        pass
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
    return "python"


def _detect_remote_url(repo_root: Path) -> str | None:
    try:
        return _git(["remote", "get-url", "origin"], cwd=repo_root)
    except SnapshotError:
        return None


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def detect_config(repo_root: Path) -> dict[str, str]:
    """Detect portable setup defaults before asking questions or writing files."""
    return {
        "schema_version": "1",
        "base_branch": _detect_base_branch(repo_root),
        "test_dir": _detect_test_dir(repo_root) or "tests",
        "python_env": _detect_python_env(repo_root),
        "probe_dir": ".bobreviewer/probes",
    }

@dataclass
class SetupResult:
    config_path: Path
    created: list[str] = field(default_factory=list)    # things we wrote/created
    preserved: list[str] = field(default_factory=list)  # things we left unchanged
    skipped: list[str] = field(default_factory=list)    # things we did not do


def _load_template(name: str) -> str:
    """Load a bundled template from bobthereviewer.templates."""
    try:
        import importlib.resources
        ref = importlib.resources.files("bobthereviewer.templates") / name
        return ref.read_text(encoding="utf-8")
    except Exception:
        fallback = Path(__file__).resolve().parent / "templates" / name
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template {name} not found")


def init(
    repo_dir: Path,
    update_gitignore: bool = True,
    config: dict[str, str] | None = None,
    install_bob_mode: bool = False,
    install_github_action: bool = False,
) -> SetupResult:
    """Initialise .bobreviewer/ for a repository.

    Safe to run multiple times: existing config fields are preserved.
    """
    repo_root = find_repo_root(repo_dir.resolve())
    br_dir = repo_root / ".bobreviewer"
    br_dir.mkdir(exist_ok=True)

    config_path = br_dir / "config.json"

    result = SetupResult(config_path=config_path)
    if config_path.exists():
        # Keep even formatting and optional fields; invalid files need a manual fix.
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        validate_config(existing)
        result.preserved.extend(["config.json", *existing])
    else:
        new_config = detect_config(repo_root) if config is None else config
        validate_config(new_config)
        config_path.write_text(
            json.dumps(new_config, indent=2, ensure_ascii=False), encoding="utf-8",
        )
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

    # Install Bob custom mode
    if install_bob_mode:
        bob_dir = repo_root / ".bob"
        bob_modes_path = bob_dir / "custom_modes.yaml"
        if not bob_modes_path.exists():
            bob_dir.mkdir(parents=True, exist_ok=True)
            mode_content = _load_template("custom_modes.yaml")
            bob_modes_path.write_text(mode_content, encoding="utf-8")
            result.created.append(".bob/custom_modes.yaml")
        else:
            existing = bob_modes_path.read_text(encoding="utf-8")
            if "slug: behavior-review" in existing:
                result.preserved.append(".bob/custom_modes.yaml")
            else:
                snippet_path = br_dir / "bob-mode.yaml"
                mode_content = _load_template("custom_modes.yaml")
                snippet_path.write_text(mode_content, encoding="utf-8")
                result.created.append(".bobreviewer/bob-mode.yaml (paste into .bob/custom_modes.yaml)")
                result.preserved.append(".bob/custom_modes.yaml")
    else:
        result.skipped.append(".bob/custom_modes.yaml")

    # Install GitHub Action workflow
    if install_github_action:
        workflows_dir = repo_root / ".github" / "workflows"
        workflow_path = workflows_dir / "bobreviewer.yml"
        if not workflow_path.exists():
            workflows_dir.mkdir(parents=True, exist_ok=True)
            workflow_content = _load_template("bobreviewer.yml")
            workflow_path.write_text(workflow_content, encoding="utf-8")
            result.created.append(".github/workflows/bobreviewer.yml")
        else:
            result.preserved.append(".github/workflows/bobreviewer.yml")
    else:
        result.skipped.append(".github/workflows/bobreviewer.yml")

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

    # ---- Config ----
    config_path = repo_root / ".bobreviewer" / "config.json"
    config_data: dict | None = None
    if config_path.exists():
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            validate_config(config_data)
            _add("config", "ok", str(config_path.relative_to(repo_root)))
        except (json.JSONDecodeError, ContractError) as e:
            _add("config", "warning",
                 f"config.json exists but is invalid: {e}\n"
                 "Run 'bobreviewer init' to recreate it.")
    else:
        _add("config", "missing",
             "No .bobreviewer/config.json — run 'bobreviewer init' first")

    # ---- Python ----
    from bobthereviewer.executor import resolve_interpreter

    python_exe, py_display, fallback_note = resolve_interpreter(config_data, repo_root)
    if Path(python_exe).exists():
        if fallback_note:
            _add("python", "ok", f"{py_display} ({fallback_note})")
        else:
            _add("python", "ok", py_display)
    else:
        _add("python", "missing", f"interpreter not found: {py_display}")

    # ---- pytest ----
    try:
        proc = subprocess.run(
            [python_exe, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            ver = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
            _add("pytest", "ok", ver)
        else:
            raise subprocess.CalledProcessError(proc.returncode, [python_exe, "-m", "pytest"])
    except Exception:
        env_disp = py_display
        for venv_name in (".venv", "venv"):
            if venv_name in Path(py_display).parts:
                env_disp = venv_name
                break
        pip_name = "pip.exe" if sys.platform == "win32" else "pip"
        candidate_pip = Path(python_exe).parent / pip_name
        if candidate_pip.exists():
            try:
                pip_cmd = str(candidate_pip.relative_to(repo_root))
            except ValueError:
                pip_cmd = str(candidate_pip)
        else:
            sep = "\\" if sys.platform == "win32" else "/"
            pip_cmd = f"{env_disp}{sep}Scripts{sep}pip" if sys.platform == "win32" else f"{env_disp}/bin/pip"
        _add("pytest", "missing", f"pytest is not installed in {env_disp} — run {pip_cmd} install pytest")

    # ---- .gitignore ----
    gitignore_path = repo_root / ".gitignore"
    if gitignore_path.exists():
        gi_content = gitignore_path.read_text(encoding="utf-8")
        if ".bobreviewer/runs/" in gi_content or ".bobreviewer/runs" in gi_content:
            _add("gitignore", "ok", ".bobreviewer/runs/ is ignored")
        else:
            _add("gitignore", "warning", ".bobreviewer/runs/ is not in .gitignore — run 'bobreviewer init' to add it")
    else:
        _add("gitignore", "warning", ".gitignore does not exist — run 'bobreviewer init' to create it")

    # ---- Probe directory and files ----
    probe_dir = repo_root / ".bobreviewer" / "probes"
    if probe_dir.exists():
        probe_files = sorted(list(probe_dir.glob("*.json")))
        if not probe_files:
            _add("probes", "ok", f"0 probe file(s) in {probe_dir.relative_to(repo_root)}")
        else:
            from bobthereviewer.contracts import validate_probe

            invalid_probes = []
            for pf in probe_files:
                rel_pf = pf.relative_to(repo_root)
                try:
                    pdata = json.loads(pf.read_text(encoding="utf-8"))
                    validate_probe(pdata)
                except Exception as e:
                    err_msg = str(e)
                    if "\n" in err_msg:
                        last_line = err_msg.strip().splitlines()[-1].strip()
                        if last_line.startswith("[<root>] "):
                            err_msg = last_line[len("[<root>] "):]
                        elif "]" in last_line:
                            err_msg = last_line.split("]", 1)[1].strip()
                    err_msg = err_msg.replace("is a required property", "is required")
                    invalid_probes.append(f"{rel_pf}: {err_msg}")
            if invalid_probes:
                for inv in invalid_probes:
                    _add("probes", "missing", inv)
            else:
                _add("probes", "ok", f"{len(probe_files)} probe file(s) valid in {probe_dir.relative_to(repo_root)}")
    else:
        _add("probes", "warning", "No .bobreviewer/probes/ directory — create probes or run 'bobreviewer init'")

    # ---- Web bundle ----
    bundle_path = Path(__file__).resolve().parent / "frontend" / "index.html"
    if bundle_path.is_file():
        _add("web_bundle", "ok", "packaged web bundle present")
    else:
        _add("web_bundle", "missing", "packaged web bundle missing (build with npm run build in web/)")

    return result
