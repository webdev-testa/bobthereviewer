"""Tests for `needs_probe` (B3) and the test-caller rule.

Bob should only ask for a probe on a caller that is real, uncovered impact. Two rules:
  * a caller inside the project's test suite never needs a probe — the tests are how the
    change is already checked, not an impacted caller;
  * once a probe for a caller has actually executed, that caller stops needing one.

The first rule is exercised through `is_test_caller` and `analyze`; the second through
`_apply_probe_coverage`, which the pipeline calls after execution.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from bobthereviewer.analysis import CallerEdge, ChangedFunction, analyze, is_test_caller
from bobthereviewer.pipeline import _apply_probe_coverage


# ---------------------------------------------------------------------------
# is_test_caller — the rule itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("file_path,symbol", [
    ("tests/test_discount.py", "tests.test_discount.test_no_discount"),
    ("tests/sub/test_thing.py", "tests.sub.test_thing.test_thing"),
    ("test_root_level.py", "test_root_level.test_something"),
    ("pkg/thing_test.py", "pkg.thing_test.test_thing"),
    ("tests/conftest.py", "tests.conftest.<module>"),
    ("backend/tests/test_api.py", "backend.tests.test_api.test_login"),
])
def test_suite_callers_do_not_need_a_probe(file_path, symbol):
    assert is_test_caller(file_path, symbol) is True


@pytest.mark.parametrize("file_path,symbol", [
    ("invoice.py", "invoice.calculate_invoice"),
    ("pkg/pricing.py", "pkg.pricing.calculate_price"),
    ("backend/app/api/news.py", "backend.app.api.news.add_news"),
    ("src/shop/latest.py", "src.shop.latest.recent"),   # 'latest' is not 'tests'
    ("contest.py", "contest.run"),                       # not a test file
])
def test_real_callers_still_need_a_probe(file_path, symbol):
    assert is_test_caller(file_path, symbol) is False


def test_a_configured_test_root_is_respected():
    """A project may keep its tests somewhere other than tests/.

    The filename convention still applies: `test_thing.py` is a test file wherever it sits,
    and the configured root adds to that rather than replacing it.
    """
    assert is_test_caller("spec/test_thing.py", "spec.test_thing.test_x", test_root="spec") is True
    # A file that is not test-named and not under the configured root is a real caller.
    assert is_test_caller("tests/helpers.py", "tests.helpers.build", test_root="spec") is False
    assert is_test_caller("tests/helpers.py", "tests.helpers.build", test_root="tests") is True


# ---------------------------------------------------------------------------
# analyze() applies the rule
# ---------------------------------------------------------------------------

def _git_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one"]):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root


DISCOUNT_ROUND = "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n"
DISCOUNT_FLOOR = "import math\n\n\ndef apply_discount(p, r):\n    return math.floor(p * (1 - r) * 100) / 100\n"


def test_analyze_marks_only_real_callers_as_needing_a_probe(tmp_path):
    """The demo shape: one caller outside the diff, seven callers inside the suite."""
    source = _git_repo(tmp_path / "repo", {
        "discount.py": DISCOUNT_ROUND,
        "invoice.py": "from discount import apply_discount\n\n\ndef calculate_invoice(p, r):\n    return apply_discount(p, r)\n",
        "tests/__init__.py": "",
        "tests/test_discount.py": (
            "from discount import apply_discount\n\n\n"
            "def test_zero():\n    assert apply_discount(100.0, 0.0) == 100.0\n\n\n"
            "def test_half():\n    assert apply_discount(200.0, 0.5) == 100.0\n"
        ),
    })
    (source / "discount.py").write_text(DISCOUNT_FLOOR)
    subprocess.run(["git", "add", "-A"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "two"],
                   cwd=source, check=True, capture_output=True)

    from bobthereviewer.analysis import analyze as run_analyze
    from bobthereviewer.snapshots import WorktreeManager

    with WorktreeManager(source, "HEAD~1", "HEAD") as ctx:
        result = run_analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    by_symbol = {}
    for cf in result.changed_functions:
        for caller in cf.callers:
            by_symbol[caller.symbol] = caller.needs_probe

    assert by_symbol.get("invoice.calculate_invoice") is True
    assert by_symbol.get("tests.test_discount.test_zero") is False
    assert by_symbol.get("tests.test_discount.test_half") is False


# ---------------------------------------------------------------------------
# _apply_probe_coverage — the second rule
# ---------------------------------------------------------------------------

def _changed_with(callers: list[CallerEdge]) -> object:
    return type("R", (), {"changed_functions": [
        ChangedFunction(symbol="discount.apply_discount", file_path="discount.py", callers=callers)
    ]})()


def test_a_probe_that_ran_clears_needs_probe_for_its_caller():
    result = _changed_with([
        CallerEdge(symbol="invoice.calculate_invoice", file_path="invoice.py", line=8,
                   in_diff=False, needs_probe=True),
    ])
    _apply_probe_coverage(result, [{"target": "invoice.calculate_invoice", "cases": []}])
    assert result.changed_functions[0].callers[0].needs_probe is False


def test_a_probe_for_another_caller_leaves_needs_probe_alone():
    result = _changed_with([
        CallerEdge(symbol="invoice.calculate_invoice", file_path="invoice.py", line=8,
                   in_diff=False, needs_probe=True),
    ])
    _apply_probe_coverage(result, [{"target": "pricing.calculate_price", "cases": []}])
    assert result.changed_functions[0].callers[0].needs_probe is True


def test_no_probes_leaves_needs_probe_untouched():
    result = _changed_with([
        CallerEdge(symbol="invoice.calculate_invoice", file_path="invoice.py", line=8,
                   in_diff=False, needs_probe=True),
    ])
    _apply_probe_coverage(result, [])
    assert result.changed_functions[0].callers[0].needs_probe is True


def test_a_probe_case_target_also_counts():
    """A case-level target must count, not only the probe-level one."""
    result = _changed_with([
        CallerEdge(symbol="invoice.calculate_invoice", file_path="invoice.py", line=8,
                   in_diff=False, needs_probe=True),
    ])
    _apply_probe_coverage(result, [
        {"cases": [{"id": "c1", "target": "invoice.calculate_invoice"}]}
    ])
    assert result.changed_functions[0].callers[0].needs_probe is False
