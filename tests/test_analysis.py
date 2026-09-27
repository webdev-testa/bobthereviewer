"""
Tests for bobthereviewer.analysis — Slice 3.

Uses temporary Git repos; does not touch the demo project.

Core milestone check (first real comparison):
  two committed refs → isolated checkouts → changed helper → caller outside
  the diff with a source location → validated evidence.

Also covers:
- Same-file function definitions
- Direct imports and aliases
- Relative imports
- module.function() calls
- Local shadowing (not resolved)
- Removed calls from base revision are not missed
- Two-hop paths with intermediate edges
- Unknown references with reasons
- Absolute paths never appear in output
- no-semantic-change detection (comment-only / formatting-only Python)
"""

import subprocess
from pathlib import Path

import pytest

from bobthereviewer.analysis import (
    AnalysisResult,
    analyze,
    changed_function_to_dict,
    _ast_equal,
    _build_import_table,
    _find_changed_symbols,
    _module_name_from_path,
    _parse_safe,
    _strip_locations,
)
from bobthereviewer.snapshots import WorktreeManager
import ast


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


def commit_files(repo: Path, files: dict[str, str], message: str, tag: str | None = None) -> str:
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
# _strip_locations / _ast_equal
# ---------------------------------------------------------------------------

def test_ast_equal_ignores_line_numbers():
    a = ast.parse("def f():\n    return 1\n")
    b = ast.parse("\n\ndef f():\n    return 1\n")  # different line numbers
    assert _ast_equal(a, b)


def test_ast_equal_detects_structural_change():
    a = ast.parse("def f():\n    return 1\n")
    b = ast.parse("def f():\n    return 2\n")
    assert not _ast_equal(a, b)


def test_ast_equal_comment_only_change():
    """Comment-only changes must look equal to the AST comparator."""
    a = ast.parse("def f():\n    # old comment\n    return 1\n")
    b = ast.parse("def f():\n    # new comment\n    return 1\n")
    assert _ast_equal(a, b)


def test_ast_equal_docstring_change():
    """Docstring changes DO change the AST (docstring is an ast.Constant node)."""
    a = ast.parse('def f():\n    """Old doc."""\n    return 1\n')
    b = ast.parse('def f():\n    """New doc."""\n    return 1\n')
    assert not _ast_equal(a, b)


# ---------------------------------------------------------------------------
# _module_name_from_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("discount.py",                  "discount"),
    ("mypackage/billing.py",         "mypackage.billing"),
    ("src/mypackage/billing.py",     "mypackage.billing"),
    ("lib/utils/helpers.py",         "utils.helpers"),
    ("a/b/c.py",                     "a.b.c"),
])
def test_module_name_from_path(path, expected):
    assert _module_name_from_path(path) == expected


# ---------------------------------------------------------------------------
# _build_import_table
# ---------------------------------------------------------------------------

def test_import_table_plain_import():
    tree = ast.parse("import os\nimport os.path\n")
    table = _build_import_table(tree, "mymod")
    assert table["os"] == "os"


def test_import_table_from_import():
    tree = ast.parse("from mypackage.billing import calculate_invoice\n")
    table = _build_import_table(tree, "mymod")
    assert table["calculate_invoice"] == "mypackage.billing.calculate_invoice"


def test_import_table_alias():
    tree = ast.parse("from mypackage.discount import apply_discount as disc\n")
    table = _build_import_table(tree, "mymod")
    assert table["disc"] == "mypackage.discount.apply_discount"


def test_import_table_relative_import():
    tree = ast.parse("from . import helper\n")
    table = _build_import_table(tree, "mypackage.invoice")
    assert table["helper"] == "mypackage.helper"


def test_import_table_star_import_not_tracked():
    tree = ast.parse("from mypackage import *\n")
    table = _build_import_table(tree, "mymod")
    assert not table  # star imports produce no entries


# ---------------------------------------------------------------------------
# _find_changed_symbols (uses real worktrees via tmp directories, not git)
# ---------------------------------------------------------------------------

def make_worktree_pair(tmp_path: Path, base_files: dict, head_files: dict):
    """Create two directory trees simulating worktrees (no git needed for unit tests)."""
    base = tmp_path / "base"
    head = tmp_path / "head"
    for files, root in ((base_files, base), (head_files, head)):
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return base, head


def test_find_changed_symbols_detects_modified_function(tmp_path):
    base, head = make_worktree_pair(tmp_path,
        {"discount.py": "def apply_discount(price, rate):\n    return price - price * rate\n"},
        {"discount.py": "def apply_discount(price, rate):\n    return round(price - price * rate, 2)\n"},
    )
    changed = _find_changed_symbols(base, head, ["discount.py"])
    symbols = [s for s, _ in changed]
    assert "discount.apply_discount" in symbols


def test_find_changed_symbols_detects_new_function(tmp_path):
    base, head = make_worktree_pair(tmp_path,
        {"mod.py": "def old():\n    pass\n"},
        {"mod.py": "def old():\n    pass\ndef new():\n    pass\n"},
    )
    changed = _find_changed_symbols(base, head, ["mod.py"])
    symbols = [s for s, _ in changed]
    assert "mod.new" in symbols


def test_find_changed_symbols_detects_removed_function(tmp_path):
    base, head = make_worktree_pair(tmp_path,
        {"mod.py": "def keep():\n    pass\ndef gone():\n    pass\n"},
        {"mod.py": "def keep():\n    pass\n"},
    )
    changed = _find_changed_symbols(base, head, ["mod.py"])
    symbols = [s for s, _ in changed]
    assert "mod.gone" in symbols


def test_find_changed_symbols_ignores_comment_only_change(tmp_path):
    """A comment-only change must NOT appear in changed symbols (ASTs identical)."""
    base, head = make_worktree_pair(tmp_path,
        {"mod.py": "def f():\n    # old comment\n    return 1\n"},
        {"mod.py": "def f():\n    # new comment\n    return 1\n"},
    )
    changed = _find_changed_symbols(base, head, ["mod.py"])
    assert not changed, "comment-only change incorrectly flagged as changed"


def test_find_changed_symbols_skips_non_python_files(tmp_path):
    base, head = make_worktree_pair(tmp_path,
        {"README.md": "old", "mod.py": "def f():\n    return 1\n"},
        {"README.md": "new", "mod.py": "def f():\n    return 1\n"},
    )
    changed = _find_changed_symbols(base, head, ["README.md", "mod.py"])
    # README.md is not Python; mod.py unchanged
    assert not changed


# ---------------------------------------------------------------------------
# Full analyze() via real git worktrees
# ---------------------------------------------------------------------------

def test_analyze_finds_caller_outside_diff(tmp_path):
    """Core milestone: discount changes; invoice (not in diff) calls it; caller found."""
    repo = tmp_path / "repo"
    init_repo(repo)

    discount_base = "def apply_discount(price, rate):\n    return price - price * rate\n"
    invoice = (
        "from discount import apply_discount\n\n"
        "def calculate_invoice(qty, unit_price):\n"
        "    subtotal = qty * unit_price\n"
        "    return apply_discount(subtotal, 0.10)\n"
    )
    commit_files(repo, {"discount.py": discount_base, "invoice.py": invoice},
                 "base commit", tag="base")

    discount_head = "def apply_discount(price, rate):\n    return round(price - price * rate, 2)\n"
    commit_files(repo, {"discount.py": discount_head}, "change discount", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert cf.symbol == "discount.apply_discount"
    assert cf.file_path == "discount.py"

    # invoice.calculate_invoice must appear as a caller
    caller_symbols = [c.symbol for c in cf.callers]
    assert any("calculate_invoice" in s for s in caller_symbols), \
        f"expected calculate_invoice in callers, got {caller_symbols}"

    # The caller must be in an unchanged file
    outside_callers = [c for c in cf.callers if not c.in_diff]
    assert outside_callers, "no caller found outside the diff"

    # All file_path values must be repo-relative
    for caller in cf.callers:
        assert not Path(caller.file_path).is_absolute(), \
            f"absolute path in caller: {caller.file_path}"

    # line number must be non-zero
    for caller in cf.callers:
        assert caller.line > 0


def test_analyze_result_has_no_absolute_paths(tmp_path):
    """No absolute filesystem paths may appear anywhere in the analysis result."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo,
        {"mod.py": "def f():\n    return 1\n",
         "caller.py": "from mod import f\ndef g():\n    return f()\n"},
        "base", tag="base")
    commit_files(repo,
        {"mod.py": "def f():\n    return 2\n"},
        "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    for cf in result.changed_functions:
        assert not Path(cf.file_path).is_absolute()
        for c in cf.callers:
            assert not Path(c.file_path).is_absolute()
        for u in cf.unknown_references:
            assert not Path(u.file_path).is_absolute()


def test_analyze_removed_caller_from_base_not_missed(tmp_path):
    """A call that existed in base but was removed in head must still appear."""
    repo = tmp_path / "repo"
    init_repo(repo)

    helper = "def helper():\n    return 1\n"
    caller_base = "from helper import helper\ndef do_work():\n    return helper()\n"
    caller_head = "def do_work():\n    return 42\n"  # call removed

    commit_files(repo, {"helper.py": helper, "caller.py": caller_base}, "base", tag="base")

    helper_changed = "def helper():\n    return 2\n"
    commit_files(repo, {"helper.py": helper_changed, "caller.py": caller_head}, "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    # helper changed; even though caller.py also changed and removed the call,
    # the base worktree still has the call — it should appear in the combined result
    cf = next((f for f in result.changed_functions if "helper" in f.symbol), None)
    assert cf is not None
    # The caller from base should be present (even though head removed it)
    caller_symbols = [c.symbol for c in cf.callers]
    assert any("do_work" in s for s in caller_symbols), \
        f"removed caller not found in combined result; callers={caller_symbols}"


def test_analyze_two_hop_path_has_via_edge(tmp_path):
    """Two-hop callers must carry a via[] list with the intermediate edge."""
    repo = tmp_path / "repo"
    init_repo(repo)

    core = "def core_fn():\n    return 1\n"
    mid = "from core import core_fn\ndef mid_fn():\n    return core_fn()\n"
    outer = "from mid import mid_fn\ndef outer_fn():\n    return mid_fn()\n"

    commit_files(repo, {"core.py": core, "mid.py": mid, "outer.py": outer}, "base", tag="base")

    core_changed = "def core_fn():\n    return 2\n"
    commit_files(repo, {"core.py": core_changed}, "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    cf = next((f for f in result.changed_functions if "core_fn" in f.symbol), None)
    assert cf is not None

    two_hop = [c for c in cf.callers if c.via]
    assert two_hop, "expected at least one two-hop caller with via edge"
    # The via edge should reference the intermediate function
    for c in two_hop:
        assert isinstance(c.via, list)
        assert len(c.via) >= 1
        assert "symbol" in c.via[0]
        assert "file_path" in c.via[0]
        assert "line" in c.via[0]


def test_analyze_local_shadow_reported_as_unknown(tmp_path):
    """A name that shadows an import locally must appear in unknown_references."""
    repo = tmp_path / "repo"
    init_repo(repo)

    target = "def target_fn():\n    return 1\n"
    shadower = (
        "from target import target_fn\n"
        "def target_fn():  # local definition shadows the import\n"
        "    return 99\n"
        "def caller():\n"
        "    return target_fn()  # ambiguous — local or import?\n"
    )
    commit_files(repo, {"target.py": target, "shadower.py": shadower}, "base", tag="base")
    target_changed = "def target_fn():\n    return 2\n"
    commit_files(repo, {"target.py": target_changed}, "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    cf = next((f for f in result.changed_functions if "target_fn" in f.symbol), None)
    assert cf is not None
    # The shadowed call should appear in unknown_references, not as a resolved caller
    unknown_files = [u.file_path for u in cf.unknown_references]
    assert "shadower.py" in unknown_files


def test_analyze_module_dot_function_call(tmp_path):
    """A module.function() call pattern must resolve correctly."""
    repo = tmp_path / "repo"
    init_repo(repo)

    target = "def compute():\n    return 1\n"
    caller = "import target\ndef run():\n    return target.compute()\n"

    commit_files(repo, {"target.py": target, "caller.py": caller}, "base", tag="base")
    target_changed = "def compute():\n    return 2\n"
    commit_files(repo, {"target.py": target_changed}, "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    cf = next((f for f in result.changed_functions if "compute" in f.symbol), None)
    assert cf is not None
    caller_symbols = [c.symbol for c in cf.callers]
    assert any("run" in s for s in caller_symbols), \
        f"module.function() call not resolved; callers={caller_symbols}"


# ---------------------------------------------------------------------------
# changed_function_to_dict
# ---------------------------------------------------------------------------

def test_changed_function_to_dict_shape(tmp_path):
    """Serialised output must match the evidence schema caller shape."""
    repo = tmp_path / "repo"
    init_repo(repo)
    commit_files(repo, {"mod.py": "def f():\n    return 1\n",
                         "caller.py": "from mod import f\ndef g():\n    return f()\n"},
                 "base", tag="base")
    commit_files(repo, {"mod.py": "def f():\n    return 2\n"}, "head", tag="head")

    with WorktreeManager(repo, "base", "head") as ctx:
        result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)

    for cf in result.changed_functions:
        d = changed_function_to_dict(cf)
        assert "symbol" in d
        assert "file_path" in d
        assert "callers" in d
        assert "unknown_references" in d
        for caller in d["callers"]:
            assert "resolution" in caller
            assert caller["resolution"] == "resolved"
            assert "via" in caller


def test_find_changed_symbols_marks_readers_of_a_changed_constant(tmp_path):
    base, head = make_worktree_pair(tmp_path,
        {"pricing.py": "TAX_RATE = 0.10\ndef calculate_price(p):\n    return p * (1 + TAX_RATE)\ndef label():\n    return 'price'\n"},
        {"pricing.py": "TAX_RATE = 0.11\ndef calculate_price(p):\n    return p * (1 + TAX_RATE)\ndef label():\n    return 'price'\n"},
    )
    symbols = [s for s, _ in _find_changed_symbols(base, head, ["pricing.py"])]
    assert symbols == ["pricing.calculate_price"]


def test_minified_files_are_skipped_and_named_in_the_notes(tmp_path):
    from bobthereviewer.adapters import is_generated_source
    from bobthereviewer.analysis import analyze

    bundle = "function a(){return 1}" * 200  # one long line, like a minified bundle
    base, head = make_worktree_pair(tmp_path,
        {"assets/app.js": bundle, "app.min.js": "x", "src/ok.js": "function ok() { return 1 }\n"},
        {"assets/app.js": bundle + "function b(){return 2}", "app.min.js": "y", "src/ok.js": "function ok() { return 2 }\n"},
    )
    assert is_generated_source(head / "assets/app.js") and is_generated_source(head / "app.min.js")
    assert not is_generated_source(head / "src/ok.js")

    result = analyze(base, head, ["assets/app.js", "app.min.js", "src/ok.js"])
    note = next(n for n in result.analysis_limits["notes"] if n.startswith("Skipped"))
    assert "assets/app.js" in note and "app.min.js" in note and "src/ok.js" not in note
    assert all(cf.file_path != "assets/app.js" for cf in result.changed_functions)
