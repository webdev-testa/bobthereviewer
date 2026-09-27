"""Wave 1 acceptance checks using real commits and paired execution."""
import json
import sys

import pytest

from bobthereviewer.cli import main
from bobthereviewer.contracts import validate_evidence
from bobthereviewer.pipeline import run_analysis_pipeline
from bobthereviewer.snapshots import uncommitted_files
from bobthereviewer.test_runner import _run_pytest
from tests.test_setup_cli import _git, commit_files, init_repo


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    init_repo(root)
    commit_files(root, {
        ".gitignore": ".bobreviewer/runs/\n__pycache__/\n",
        "discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
        "invoice.py": "from discount import apply_discount\ndef calculate_invoice(p, r):\n    return apply_discount(p, r)\n",
    }, "base", tag="base")
    commit_files(root, {
        "discount.py": "import math\ndef apply_discount(p, r):\n    return math.floor(p * (1 - r) * 100) / 100\n",
    }, "rounding", tag="head")
    return root


def run_cli(repo, *extra):
    return main(["run", "--repo-dir", str(repo), "--before", "base", "--after", "HEAD", *extra])


def test_paired_probe_pipeline_and_saved_cli_runs(repo, tmp_path, capsys):
    commit_files(repo, {".bobreviewer/probes/invoice.json": json.dumps({
        "schema_version": "1", "target": "invoice.calculate_invoice",
        "cases": [{"id": "invoice-small-discount", "args": [100.0, 0.00001], "kwargs": {}}],
    })}, "probe")
    result = run_analysis_pipeline(repo, "base", "HEAD", execute=True)
    validate_evidence(result.evidence)
    case = result.evidence["probe_results"][0]["cases"][0]
    assert case["execution_status"] == "success"
    assert case["comparison_status"] == "differ"
    assert (case["base_output"], case["head_output"]) == (100.0, 99.99)
    out = tmp_path / "export"
    assert run_cli(repo, "--output", str(out)) == 0
    assert run_cli(repo) == 0
    runs = list((repo / ".bobreviewer/runs").iterdir())
    assert len(runs) == 2
    for saved in runs:
        meta = json.loads((saved / "meta.json").read_text())
        evidence = json.loads((saved / "evidence.json").read_text())
        assert meta["status"] == "completed"
        assert meta["run_id"] == evidence["run_id"] == saved.name
        report = (saved / "report.md").read_text(encoding="utf-8")
        assert "invoice.calculate_invoice" in report
        assert "100.0" in report and "99.99" in report
    for name in ("meta.json", "evidence.json", "report.md"):
        assert (out / name).exists()
    assert _git(["status", "--porcelain"], repo) == ""
    output = capsys.readouterr().out
    assert "[differ] invoice.calculate_invoice" in output
    assert all(saved.name in output for saved in runs)


def test_no_probes_note_saved_in_evidence_and_report(repo):
    assert run_cli(repo) == 0
    saved = next((repo / ".bobreviewer/runs").iterdir())
    note = "No probes were selected, so no behaviour claim is made from execution."
    evidence = json.loads((saved / "evidence.json").read_text())
    assert note in evidence["analysis_limits"]["notes"]
    assert note in (saved / "report.md").read_text(encoding="utf-8")


def test_failed_run_retains_failed_metadata(repo):
    assert run_cli(repo, "--after", "missing-ref") == 1
    saved = next((repo / ".bobreviewer/runs").iterdir())
    assert json.loads((saved / "meta.json").read_text())["status"] == "failed"
    assert not (saved / "evidence.json").exists()


def test_collection_error_survives_pipeline_validation(repo):
    commit_files(repo, {"test_broken.py": "def test_bad(:\n"}, "broken test", tag="broken")
    result = run_analysis_pipeline(repo, "broken", "HEAD", execute=True)
    validate_evidence(result.evidence)
    for side in ("base", "head"):
        error = result.evidence["test_results"][side]["<collection>"]
        assert error["status"] == "error"
        assert "SyntaxError" in error["message"]


def test_uncommitted_bob_files_warn_but_do_not_block(repo, capsys):
    for path in ("decisions/new decision.json", "probes/new probe.json"):
        file = repo / ".bobreviewer" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}")
    assert run_cli(repo) == 0
    err = capsys.readouterr().err
    assert "Not included (uncommitted): .bobreviewer/decisions/new decision.json" in err
    assert "Not included (uncommitted): .bobreviewer/probes/new probe.json" in err
    assert "commit it to use it" in err
    saved = next((repo / ".bobreviewer/runs").iterdir())
    assert json.loads((saved / "evidence.json").read_text())["probe_results"] == []


@pytest.mark.parametrize("tty,answer,expected", [(False, None, 1), (True, "n", 1), (True, "", 1), (True, "y", 0)])
def test_dirty_source_requires_interactive_consent(repo, monkeypatch, capsys, tty, answer, expected):
    source = repo / "discount.py"
    source.write_text("this uncommitted source is invalid Python")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    prompts = []
    def respond(prompt):
        prompts.append(prompt)
        return answer
    monkeypatch.setattr("builtins.input", respond)
    assert run_cli(repo) == expected
    assert "discount.py" in capsys.readouterr().err
    assert prompts == (["Continue without these changes? [y/N] "] if tty else [])
    assert source.read_text() == "this uncommitted source is invalid Python"


def test_dirty_paths_include_both_rename_ends(repo):
    (repo / ".bobreviewer").mkdir()
    _git(["mv", "invoice.py", ".bobreviewer/moved file.py"], repo)
    bob, other = uncommitted_files(repo)
    assert bob == [".bobreviewer/moved file.py"]
    assert other == ["invoice.py"]


@pytest.mark.parametrize("source,detail", [
    ("def test_bad(:\n", "SyntaxError"),
    ("value = 1\n", "no tests ran"),
])
def test_collection_failure_is_an_error(tmp_path, source, detail):
    (tmp_path / "test_bad.py").write_text(source)
    results = _run_pytest(str(tmp_path), sys.executable, ["test_bad.py"], 30)
    assert results["<collection>"]["status"] == "error"
    assert detail in results["<collection>"]["message"]
    assert str(tmp_path) not in results["<collection>"]["message"]
    assert tmp_path.as_posix() not in results["<collection>"]["message"]
