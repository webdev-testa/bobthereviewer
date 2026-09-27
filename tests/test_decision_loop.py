"""Tests for the decision ledger loop: A6 (approved history) and A7 (decision in the report).

Two rules that are easy to get subtly wrong, and both have bitten this repo:

  * approval is a question about the default branch's *history*, not about the working tree.
    Reading the filesystem means a decision merged into `main` disappears from the report
    whenever the checkout happens to be on a branch that predates the merge;
  * a decision is matched on symbol *and* source file, so two same-named functions in
    different files never borrow each other's decision. The source file must be recorded on
    the decision itself — storing the probe's path makes the record unmatchable forever.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bobthereviewer.decisions import approved_for_symbols, load_branch_decisions
from bobthereviewer.report import _decision_cell, render_markdown


# ---------------------------------------------------------------------------
# helpers: a real git repo, because approval is a git question
# ---------------------------------------------------------------------------

def _decision_file(symbol: str, file_path: str, verdict: str = "intended",
                   rationale: str = "Tax policy for 2026", repository: str = "local") -> str:
    return json.dumps({
        "schema_version": "1", "run_id": "r", "repository": repository,
        "file_path": file_path, "symbol": symbol,
        "base_commit": "a" * 40, "head_commit": "b" * 40,
        "probe_file": ".bobreviewer/probes/p.json", "probe_hash": "sha256:x",
        "case_id": "c1", "observed_before": 1, "observed_after": 2,
        "verdict": verdict, "rationale": rationale,
        "status": "proposed", "timestamp": "2026-09-27T00:00:00Z",
    })


def _repo_with_branches(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "pricing.py").write_text("def calculate_price(p):\n    return p * 1.1\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True, capture_output=True)
    # a feature branch carrying both a code change and the decision, not yet merged
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=root, check=True, capture_output=True)
    (root / "pricing.py").write_text("def calculate_price(p):\n    return p * 1.11\n")
    decisions = root / ".bobreviewer" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "pricing_calculate_price-aaaaaaa.json").write_text(
        _decision_file("pricing.calculate_price", "pricing.py")
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "feature + decision"], cwd=root, check=True, capture_output=True)
    return root


# ---------------------------------------------------------------------------
# load_branch_decisions / approved_for_symbols — A6
# ---------------------------------------------------------------------------

def test_a_decision_only_on_a_feature_branch_is_not_approved(tmp_path):
    """Not merged into the default branch means not approved."""
    root = _repo_with_branches(tmp_path)
    symbols = {"pricing.calculate_price": "pricing.py"}
    assert approved_for_symbols("local", symbols, "main", root) == []


def test_after_merging_into_the_default_branch_it_is_approved(tmp_path):
    root = _repo_with_branches(tmp_path)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "merge", "feature"],
                   cwd=root, check=True, capture_output=True)
    symbols = {"pricing.calculate_price": "pricing.py"}
    matched = approved_for_symbols("local", symbols, "main", root)
    assert len(matched) == 1
    assert matched[0]["rationale"] == "Tax policy for 2026"


def test_approval_does_not_depend_on_the_checked_out_branch(tmp_path):
    """The regression: reading the filesystem hides a merged decision when the checkout
    is on a branch that predates the merge."""
    root = _repo_with_branches(tmp_path)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "merge", "feature"],
                   cwd=root, check=True, capture_output=True)
    # work from an unrelated branch that does not contain the decision in its tree
    subprocess.run(["git", "checkout", "-q", "-b", "elsewhere", "HEAD~1"],
                   cwd=root, check=True, capture_output=True)
    assert not (root / ".bobreviewer" / "decisions").exists(), "precondition: not on disk"
    symbols = {"pricing.calculate_price": "pricing.py"}
    assert len(approved_for_symbols("local", symbols, "main", root)) == 1


def test_a_same_named_function_in_another_file_does_not_borrow_it(tmp_path):
    """Matching is on file_path + symbol, not the bare symbol."""
    root = _repo_with_branches(tmp_path)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "merge", "-q", "--no-ff", "-m", "merge", "feature"],
                   cwd=root, check=True, capture_output=True)
    assert approved_for_symbols("local", {"pricing.calculate_price": "other.py"}, "main", root) == []
    assert len(approved_for_symbols("local", {"pricing.calculate_price": "pricing.py"}, "main", root)) == 1


def test_a_superseded_or_malformed_record_is_skipped(tmp_path):
    root = _repo_with_branches(tmp_path)
    bad = root / ".bobreviewer" / "decisions" / "broken.json"
    bad.write_text("{ not json")
    (root / ".bobreviewer" / "decisions" / "empty.json").write_text("{}")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add junk"], cwd=root, check=True, capture_output=True)
    records = load_branch_decisions("feature", root)
    assert [r["symbol"] for r in records] == ["pricing.calculate_price"]


# ---------------------------------------------------------------------------
# _decision_cell / render_markdown — A7
# ---------------------------------------------------------------------------

def _evidence(status: str = "differ", decisions: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1", "run_id": "r", "generated_at": "2026-09-27T00:00:00Z",
        "repository": "local", "base_ref": "demo-base", "head_ref": "HEAD",
        "base_commit": "a", "head_commit": "b",
        "triage": {"category": "code", "skipped": False, "skip_reason": None},
        "analysis_limits": {"max_hops": 2, "notes": []},
        "changed_functions": [],
        "test_results": {"base": {}, "head": {}},
        "probe_results": [{
            "probe_file": ".bobreviewer/probes/p.json", "probe_hash": "sha256:x",
            "target": "invoice.calculate_invoice",
            "cases": [{"id": "c1", "args": [], "kwargs": {},
                       "base_output": 100.0, "head_output": 99.99,
                       "execution_status": "success", "comparison_status": status}],
        }],
        "decisions": decisions or [],
        "prior_decisions": [],
    }


def test_a_differing_case_with_no_decision_says_so():
    assert "No decision yet" in _decision_cell("c1", "invoice.calculate_invoice", "sha256:x", [])


def test_a_differing_case_with_a_decision_shows_the_verdict_and_rationale():
    cell = _decision_cell("c1", "invoice.calculate_invoice", "sha256:x", [{
        "case_id": "c1", "symbol": "invoice.calculate_invoice",
        "probe_hash": "sha256:x", "verdict": "intended", "rationale": "Rounding policy",
    }])
    assert "Intended" in cell and "Rounding policy" in cell
    assert "proposed — approved when merged" in cell


def test_a_decision_for_a_different_probe_hash_is_not_applied():
    """A probe whose bytes changed is a different probe; its decision must not be reused."""
    cell = _decision_cell("c1", "invoice.calculate_invoice", "sha256:different", [{
        "case_id": "c1", "symbol": "invoice.calculate_invoice",
        "probe_hash": "sha256:x", "verdict": "intended", "rationale": "Old",
    }])
    assert "No decision yet" in cell


def test_the_report_shows_the_no_decision_marker_in_the_row():
    md = render_markdown(_evidence())
    row = [l for l in md.splitlines() if "c1" in l and "|" in l][0]
    assert "No decision yet" in row
    assert "unresolved work, not an approval" in md


def test_the_report_shows_the_decision_once_recorded():
    md = render_markdown(_evidence(decisions=[{
        "case_id": "c1", "symbol": "invoice.calculate_invoice",
        "probe_hash": "sha256:x", "verdict": "intended", "rationale": "Rounding policy",
    }]))
    row = [l for l in md.splitlines() if "c1" in l and "|" in l][0]
    assert "Intended" in row and "Rounding policy" in row


def test_a_matching_case_needs_no_decision_column_value():
    """Only a difference needs a disposition; a match is not pending work."""
    md = render_markdown(_evidence(status="match"))
    row = [l for l in md.splitlines() if "c1" in l and "|" in l][0]
    assert "No decision yet" not in row


def test_prior_section_lists_only_approved_decisions():
    evidence = json.loads((Path(__file__).parent / "fixtures" / "evidence_rounding_change.json").read_text(encoding="utf-8"))
    decision = {"verdict": "intended", "symbol": "pricing.calculate_price", "rationale": "Tax rate raised"}
    branch_only = render_markdown({**evidence, "decisions": [decision], "prior_decisions": []})
    assert "Prior decisions" not in branch_only
    approved = render_markdown({**evidence, "decisions": [], "prior_decisions": [decision]})
    assert "Prior decisions" in approved and "Tax rate raised" in approved


def test_report_groups_test_callers_into_one_line():
    evidence = json.loads((Path(__file__).parent / "fixtures" / "evidence_rounding_change.json").read_text(encoding="utf-8"))
    evidence["changed_functions"][0]["callers"] = [
        {"symbol": "invoice.calculate_invoice", "file_path": "invoice.py", "line": 8, "in_diff": False,
         "resolution": "resolved", "needs_probe": True, "via": None},
        {"symbol": "tests.test_discount.test_no_discount", "file_path": "tests/test_discount.py", "line": 16,
         "in_diff": False, "resolution": "resolved", "needs_probe": False, "via": None},
    ]
    md = render_markdown(evidence)
    assert "| `invoice.calculate_invoice` |" in md
    assert "| `tests.test_discount.test_no_discount` |" not in md
    assert "**1 test(s) call it:** `test_no_discount`" in md


def test_repository_urls_match_with_or_without_dot_git():
    from bobthereviewer.decisions import same_repository
    assert same_repository("https://github.com/o/r.git", "https://github.com/o/r")
    assert same_repository("https://github.com/O/R/", "https://github.com/o/r")
    assert not same_repository("https://github.com/o/r", "https://github.com/o/other")


def test_head_decisions_leave_out_files_already_on_the_base(tmp_path):
    """A decision merged earlier is prior context, never this change's verdict."""
    from types import SimpleNamespace
    from bobthereviewer.pipeline import _load_head_decisions

    base, head = tmp_path / "base", tmp_path / "head"
    for root in (base, head):
        (root / ".bobreviewer" / "decisions").mkdir(parents=True)
    old = {"symbol": "pricing.calculate_price", "case_id": "price-100", "verdict": "intended"}
    new = {"symbol": "invoice.calculate_invoice", "case_id": "small", "verdict": "unintended"}
    for root in (base, head):
        (root / ".bobreviewer" / "decisions" / "old.json").write_text(json.dumps(old), encoding="utf-8")
    (head / ".bobreviewer" / "decisions" / "new.json").write_text(json.dumps(new), encoding="utf-8")

    decisions = _load_head_decisions(SimpleNamespace(head_path=head, base_path=base))
    assert [d["symbol"] for d in decisions] == ["invoice.calculate_invoice"]


def test_approved_decisions_are_found_when_only_origin_main_exists(tmp_path):
    """Like a CI checkout: the default branch exists only as origin/main."""
    from bobthereviewer.decisions import load_branch_decisions
    from tests.test_setup_cli import commit_files, init_repo

    upstream = tmp_path / "upstream"
    init_repo(upstream)
    record = {"symbol": "pricing.calculate_price", "case_id": "price-100", "verdict": "intended"}
    commit_files(upstream, {".bobreviewer/decisions/d.json": json.dumps(record)}, "decision")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(upstream), str(clone)], check=True)
    subprocess.run(["git", "checkout", "-q", "--detach"], cwd=clone, check=True)
    subprocess.run(["git", "branch", "-q", "-D", "main"], cwd=clone, check=True)

    assert [r["symbol"] for r in load_branch_decisions("main", clone)] == ["pricing.calculate_price"]
