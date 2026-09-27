"""
Tests for bobthereviewer.setup and bobthereviewer.cli — Slice 5.

Setup tests use temporary Git repos.
CLI integration tests run the CLI via main() with argv lists.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bobthereviewer.setup import init, doctor, SetupResult, DoctorResult
from bobthereviewer.cli import main, build_parser


@pytest.mark.parametrize("answers,expected", [
    (["", "", ""], {"base_branch": "main", "test_dir": "tests", "python_env": ".venv/Scripts/python.exe"}),
    (["release", "specs", "python3"], {"base_branch": "release", "test_dir": "specs", "python_env": "python3"}),
])
def test_interactive_init_defaults_and_overrides(tmp_path, monkeypatch, capsys, answers, expected):
    repo = tmp_path / "repo"
    init_repo(repo)
    python = repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    replies = iter(answers)
    prompts = []
    def answer(prompt):
        prompts.append(prompt)
        return next(replies)
    monkeypatch.setattr("builtins.input", answer)
    assert main(["init", "--repo-dir", str(repo)]) == 0
    config = json.loads((repo / ".bobreviewer/config.json").read_text())
    assert all(config[key] == value for key, value in expected.items())
    assert len(prompts) == 3
    assert "[main]" in prompts[0]
    assert "Detected setup:" in capsys.readouterr().out


@pytest.mark.parametrize("tty,flags", [(True, ["--yes"]), (False, [])])
def test_init_without_prompts_and_rerun_keeps_bytes(tmp_path, monkeypatch, capsys, tty, flags):
    repo = tmp_path / "repo"
    init_repo(repo)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    assert main(["init", "--repo-dir", str(repo), *flags]) == 0
    path = repo / ".bobreviewer/config.json"
    config = json.loads(path.read_text())
    config.pop("test_dir")
    path.write_text(json.dumps(config, separators=(",", ":")) + "\n")
    before = {p: p.read_bytes() for p in (path, repo / ".gitignore")}
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["init", "--repo-dir", str(repo)]) == 0
    assert all(p.read_bytes() == data for p, data in before.items())
    output = capsys.readouterr().out
    assert "kept" in output
    assert "Next: bobreviewer run, then bobreviewer ui" in output


def test_init_preserves_invalid_config(tmp_path, capsys):
    repo = tmp_path / "repo"
    init_repo(repo)
    config = repo / ".bobreviewer/config.json"
    config.parent.mkdir()
    config.write_text("{broken")
    assert main(["init", "--yes", "--repo-dir", str(repo)]) == 1
    assert config.read_text() == "{broken"
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("tty,flags,answers,expected_base,exit_code", [
    (True, [], [""], "main", 0),
    (True, [], ["n"], None, 1),
    (True, [], ["other", "base"], "base", 0),
    (True, [], ["other", ""], None, 1),
    (True, ["--before", "base", "--after", "HEAD"], [], "base", 0),
    (True, ["--before", "base"], [], "base", 0),
    (True, ["--after", "HEAD"], [], "main", 0),
    (False, [], [], "main", 0),
])
def test_run_comparison_prompt(tmp_path, monkeypatch, tty, flags, answers, expected_base, exit_code):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f(): return 1\n"}, "base", tag="base")
    init(repo)
    _git(["add", ".bobreviewer/config.json", ".gitignore"], repo)
    _git(["commit", "-m", "setup"], repo)
    _git(["checkout", "-b", "pr/tax"], repo)
    commit_files(repo, {"mod.py": "def f(): return 2\n"}, "head")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    replies = iter(answers)
    prompts = []
    def answer(prompt):
        prompts.append(prompt)
        return next(replies)
    monkeypatch.setattr("builtins.input", answer)
    assert main(["run", "--repo-dir", str(repo), *flags]) == exit_code
    if answers:
        assert prompts[0] == "Compare pr/tax with main? [Y/n/other] "
    else:
        assert prompts == []
    reports = list((repo / ".bobreviewer/runs").glob("*/evidence.json"))
    if exit_code == 0:
        assert len(reports) == 1
        assert json.loads(reports[0].read_text())["base_ref"] == expected_base
    else:
        assert reports == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)


def commit_files(repo: Path, files: dict, message: str, tag: str | None = None) -> str:
    for rel_path, content in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        _git(["add", rel_path], cwd=repo)
    _git(["commit", "-m", message], cwd=repo)
    sha = _git(["rev-parse", "HEAD"], cwd=repo)
    if tag:
        _git(["tag", tag], cwd=repo)
    return sha


# ---------------------------------------------------------------------------
# init — idempotency and creation
# ---------------------------------------------------------------------------

def test_init_creates_config(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    result = init(repo)

    config_path = repo / ".bobreviewer" / "config.json"
    assert config_path.exists()
    data = json.loads(config_path.read_text())
    assert data["schema_version"] == "1"
    assert "base_branch" in data
    assert "probes/" in " ".join(result.created) or "probe_dir" in " ".join(result.created)


def test_init_creates_subdirectories(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)
    assert (repo / ".bobreviewer" / "probes").is_dir()
    assert (repo / ".bobreviewer" / "decisions").is_dir()


def test_init_preserves_existing_fields(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    # First init
    init(repo)
    config_path = repo / ".bobreviewer" / "config.json"
    data = json.loads(config_path.read_text())
    data["base_branch"] = "custom-branch"
    config_path.write_text(json.dumps(data))

    # Second init must preserve custom-branch
    result2 = init(repo)
    data2 = json.loads(config_path.read_text())
    assert data2["base_branch"] == "custom-branch", "init overwrote existing base_branch"
    assert "base_branch" in result2.preserved


def test_init_idempotent_no_duplicates(tmp_path):
    """Running init twice must not duplicate entries or fail."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)
    init(repo)  # second time must not raise


def test_init_adds_gitignore_entry(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)
    gitignore = (repo / ".gitignore").read_text()
    assert ".bobreviewer/runs/" in gitignore


def test_init_does_not_duplicate_gitignore_entry(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)
    init(repo)  # second time
    count = (repo / ".gitignore").read_text().count(".bobreviewer/runs/")
    assert count == 1


def test_init_from_subdirectory(tmp_path):
    """init should resolve the repo root even when called from a subdirectory."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    subdir = repo / "src"
    subdir.mkdir()
    result = init(subdir)
    assert (repo / ".bobreviewer" / "config.json").exists()


# ---------------------------------------------------------------------------
# doctor — checks without side effects
# ---------------------------------------------------------------------------

def test_doctor_passes_for_initialised_repo(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)

    result = doctor(repo)

    check_names = {c.name for c in result.checks}
    assert "git" in check_names
    assert "python" in check_names
    assert "config" in check_names

    config_check = next(c for c in result.checks if c.name == "config")
    assert config_check.status == "ok"


def test_doctor_does_not_write_anything(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    before = set(repo.rglob("*"))
    doctor(repo)
    after = set(repo.rglob("*"))
    assert before == after, "doctor wrote something it should not have"


def test_doctor_reports_missing_config(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    result = doctor(repo)
    config_check = next((c for c in result.checks if c.name == "config"), None)
    assert config_check is not None
    assert config_check.status == "missing"


# ---------------------------------------------------------------------------
# CLI — argument parser
# ---------------------------------------------------------------------------

def test_parser_no_command_returns_0():
    code = main([])
    assert code == 0


def test_parser_analyze_requires_before_and_after():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["analyze", "--before", "base"])  # missing --after


def test_parser_decide_choices():
    parser = build_parser()
    args = parser.parse_args([
        "decide", "--run-id", "abc", "--symbol", "x.y",
        "--case-id", "c1", "--verdict", "intended", "--rationale", "r"
    ])
    assert args.verdict == "intended"


# ---------------------------------------------------------------------------
# CLI — init integration
# ---------------------------------------------------------------------------

def test_cli_init_creates_config(tmp_path, capsys):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    code = main(["init", "--repo-dir", str(repo)])
    assert code == 0
    assert (repo / ".bobreviewer" / "config.json").exists()


def test_cli_init_idempotent(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")

    assert main(["init", "--repo-dir", str(repo)]) == 0
    assert main(["init", "--repo-dir", str(repo)]) == 0


# ---------------------------------------------------------------------------
# CLI — doctor integration
# ---------------------------------------------------------------------------

def test_cli_doctor_runs(tmp_path, capsys):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"README.md": "hello"}, "initial")
    init(repo)

    code = main(["doctor", "--repo-dir", str(repo)])
    out = capsys.readouterr().out
    assert "doctor" in out
    assert "config" in out


# ---------------------------------------------------------------------------
# CLI — analyze integration
# ---------------------------------------------------------------------------

def test_cli_analyze_produces_output(tmp_path, capsys):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return p - p * r\n",
         "invoice.py": "from discount import apply_discount\ndef calc(q, p):\n    return apply_discount(q * p, 0.1)\n"},
        "base", tag="base")
    commit_files(repo,
        {"discount.py": "def apply_discount(p, r):\n    return round(p - p * r, 2)\n"},
        "head", tag="head")

    code = main(["analyze",
                 "--before", "base", "--after", "head",
                 "--repo-dir", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert "apply_discount" in out
    assert "invoice.py" in out


def test_cli_analyze_writes_evidence_json(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    out_dir = tmp_path / "out"
    code = main(["analyze",
                 "--before", "base", "--after", "head",
                 "--output", str(out_dir),
                 "--repo-dir", str(repo)])
    assert code == 0
    evidence_path = out_dir / "evidence.json"
    assert evidence_path.exists()
    data = json.loads(evidence_path.read_text())
    assert data["schema_version"] == "1"


# ---------------------------------------------------------------------------
# CLI — run integration (dirty tree check)
# ---------------------------------------------------------------------------

def test_cli_run_rejects_dirty_working_tree(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    # Add an uncommitted file
    (repo / "uncommitted.py").write_text("x = 1")

    code = main(["run", "--before", "base", "--after", "head",
                 "--repo-dir", str(repo)])
    assert code == 1


def test_cli_run_uses_config_defaults(tmp_path):
    """When --before/--after omitted, run uses config.base_branch and HEAD."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n"}, "initial")
    init(repo)
    # Commit the .bobreviewer/ files so the tree is clean
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "add bobthereviewer config"], cwd=repo)

    # No uncommitted files — clean tree
    code = main(["run", "--repo-dir", str(repo)])
    # HEAD and main point to same commit → no changed files → valid run
    assert code == 0


# ---------------------------------------------------------------------------
# CLI — decide and ui pending integration
# ---------------------------------------------------------------------------

def test_cli_decide_missing_evidence_returns_1(tmp_path, capsys):
    """decide command returns 1 when evidence bundle is not found."""
    repo = tmp_path / "repo"
    init_repo(repo)
    code = main([
        "decide",
        "--run-id", "00000000-0000-0000-0000-000000000001",
        "--symbol", "x.y",
        "--case-id", "c1",
        "--verdict", "unresolved",
        "--rationale", "Need more info",
        "--repo-dir", str(repo),
    ])
    assert code == 1
    err = capsys.readouterr().err
    assert "not found" in err.lower() or "could not find" in err.lower()


def test_cli_decide_success_writes_decision_and_prints_git_command(tmp_path, capsys):
    """decide command writes a valid decision file and prints the suggested git command."""
    repo = tmp_path / "repo"
    init_repo(repo)
    run_id = "00000000-0000-0000-0000-000000000001"
    evidence_dir = repo / ".bobreviewer" / "runs" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = evidence_dir / "evidence.json"

    evidence_data = {
        "schema_version": "1",
        "run_id": run_id,
        "generated_at": "2026-01-01T00:00:00Z",
        "repository": "https://github.com/example/bobthereviewer",
        "base_ref": "main",
        "head_ref": "feature",
        "base_commit": "a" * 40,
        "head_commit": "b" * 40,
        "changed_functions": [
            {
                "symbol": "pricing.discount.apply_discount",
                "file_path": "pricing/discount.py",
                "callers": [],
                "unknown_references": [],
            }
        ],
        "probe_results": [
            {
                "probe_file": "probes/discount.json",
                "probe_hash": "c" * 64,
                "target": "pricing.discount.apply_discount",
                "cases": [
                    {
                        "id": "case-1",
                        "args": [100.0, 0.1],
                        "kwargs": {},
                        "base_output": 90.0,
                        "head_output": 89.99,
                        "status": "differ",
                    }
                ],
            }
        ],
    }
    evidence_file.write_text(json.dumps(evidence_data), encoding="utf-8")

    code = main([
        "decide",
        "--run-id", run_id,
        "--symbol", "pricing.discount.apply_discount",
        "--case-id", "case-1",
        "--verdict", "intended",
        "--rationale", "Updated rounding precision per new policy guidelines.",
        "--repo-dir", str(repo),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "decision written to:" in out.lower()
    assert "git add" in out
    assert "git commit" in out

    # Verify decision JSON was written
    decisions_dir = repo / ".bobreviewer" / "decisions"
    assert decisions_dir.exists()
    decision_files = list(decisions_dir.glob("*.json"))
    assert len(decision_files) == 1
    written_data = json.loads(decision_files[0].read_text(encoding="utf-8"))
    assert written_data["case_id"] == "case-1"
    assert written_data["verdict"] == "intended"
    assert written_data["status"] == "proposed"



def test_cli_ui_hands_off_to_lane2_server(tmp_path, capsys, monkeypatch):
    """`ui` delegates to Lane 2's server.start and never blocks the test run.

    Lane 2 now ships the local server, so this asserts the handoff rather than a pending
    message. `start` is stubbed: the real one binds a socket and serves forever.
    """
    import bobthereviewer.server as server_module

    called: dict[str, object] = {}

    def fake_start(args):
        called["args"] = args
        return 0

    monkeypatch.setattr(server_module, "start", fake_start, raising=False)
    code = main(["ui"])
    assert code == 0
    assert "args" in called, "cli did not call server.start"
