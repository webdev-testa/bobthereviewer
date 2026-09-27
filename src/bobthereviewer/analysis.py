"""
bobthereviewer.analysis
~~~~~~~~~~~~~~~~~~~~~~~
AST-based impact analysis: changed functions, direct callers, two-hop paths.

Algorithm overview
------------------
1.  For each Python file that appears in changed_files, parse both the base
    and head AST.  A function is "changed" if its body is structurally
    different between revisions (ignoring source-location attributes).  New
    functions (only in head) and removed functions (only in base) are also
    reported as changed.

2.  Build an import table for every Python file in both worktrees.  The table
    maps each name visible in that file to (module_dotted_path, member_name).

3.  Walk every Python file in both worktrees (not just changed files) looking
    for call sites that resolve to a changed symbol.  A call site resolves
    when the import table unambiguously maps the called name to the changed
    symbol.  Import-only references that have no call site are not reported
    as callers.

4.  Two-hop paths: for each first-hop caller, repeat step 3 using that
    caller as the target symbol.  Preserve the intermediate edge in `via`.

5.  References that cannot be resolved (dynamic dispatch, ambiguous name,
    missing import) appear in `unknown_references` with a reason string.

6.  Call relationships from both revisions are combined so that removed
    calls are not missed.

Absolute filesystem paths never appear in the output.  All file_path values
are repo-relative strings.

Ownership: Lane 1.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass
class CallerEdge:
    """A resolved call site that calls a changed (or intermediate) function."""
    symbol: str            # fully-qualified name of the caller
    file_path: str         # repo-relative
    line: int
    in_diff: bool          # True if the caller's file is in changed_files
    needs_probe: bool      # True until a probe covers this caller
    via: list[dict] | None = None   # intermediate edges for two-hop paths


@dataclass
class UnknownReference:
    """A reference we found but could not resolve reliably."""
    file_path: str         # repo-relative
    line: int
    reason: str


@dataclass
class ChangedFunction:
    symbol: str            # fully-qualified name
    file_path: str         # repo-relative
    callers: list[CallerEdge] = field(default_factory=list)
    unknown_references: list[UnknownReference] = field(default_factory=list)


@dataclass
class AnalysisResult:
    changed_functions: list[ChangedFunction] = field(default_factory=list)
    analysis_limits: dict = field(default_factory=lambda: {
        "max_hops": 2,
        "notes": [],
    })


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _strip_locations(node: ast.AST) -> ast.AST:
    """Return a deep copy of *node* with all source-location attrs removed.

    This lets us compare AST structure independent of line/col numbers,
    which change when comments or blank lines are added.
    """
    node = copy.deepcopy(node)
    for child in ast.walk(node):
        for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset",
                     "type_comment"):
            child.__dict__.pop(attr, None)
    return node


def _ast_equal(a: ast.AST, b: ast.AST) -> bool:
    """True if two AST nodes are structurally identical (location-independent)."""
    return ast.dump(_strip_locations(a)) == ast.dump(_strip_locations(b))


def _parse_safe(source: str, filename: str) -> ast.Module | None:
    """Parse Python source; return None on SyntaxError."""
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError:
        return None


def _collect_functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return a mapping of local function name → AST node for top-level and
    class-method definitions (one level deep for class bodies)."""
    funcs: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
    return funcs


# ---------------------------------------------------------------------------
# Import table
# ---------------------------------------------------------------------------

def _build_import_table(tree: ast.Module, file_module: str) -> dict[str, str]:
    """Build a name→fully-qualified-symbol table for the module.

    Returns a dict mapping every locally-available name to a dotted FQN.
    Only names that are explicitly imported are tracked; locally-defined
    names are mapped to ``<file_module>.<name>``.

    Relative imports are resolved relative to *file_module*.
    """
    table: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    # import os.path as osp  →  osp → os.path
                    table[alias.asname] = alias.name
                else:
                    # import os  →  os → os
                    # import os.path  →  os → os  (first component only)
                    first = alias.name.split(".")[0]
                    if first not in table:   # don't let os.path overwrite os
                        table[first] = first

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import: resolve against file_module
                parts = file_module.split(".")
                # Go up `level` steps
                base_parts = parts[:max(0, len(parts) - node.level)]
                if node.module:
                    abs_module = ".".join(base_parts + [node.module])
                else:
                    abs_module = ".".join(base_parts)
            else:
                if node.module is None:
                    continue
                abs_module = node.module

            for alias in node.names:
                if alias.name == "*":
                    # Star import — can't resolve statically
                    continue
                local_name = alias.asname if alias.asname else alias.name
                table[local_name] = f"{abs_module}.{alias.name}"

    return table


def _module_name_from_path(file_path: str) -> str:
    """Derive a dotted module name from a repo-relative path.

    ``src/mypackage/billing.py`` → ``mypackage.billing``
    ``discount.py`` → ``discount``
    """
    p = Path(file_path)
    # Strip leading src/ or lib/ convention
    parts = p.with_suffix("").parts
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Call-site resolution
# ---------------------------------------------------------------------------

def _resolve_call_target(
    call_node: ast.Call,
    import_table: dict[str, str],
    local_names: set[str],
    file_module: str,
) -> tuple[str | None, str | None]:
    """Attempt to resolve the target of a call node.

    Returns (fqn, reason_if_unknown).
    - If fully resolved: (fqn, None)
    - If unresolvable:   (None, reason_string)
    """
    func = call_node.func

    if isinstance(func, ast.Name):
        name = func.id
        if name in local_names:
            # Locally defined — could shadow an import; treat as unknown
            return None, f"name '{name}' is defined locally, may shadow an import"
        if name in import_table:
            return import_table[name], None
        # Not in import table and not locally defined — dynamic or builtin
        return None, f"name '{name}' has no visible import and is not locally defined"

    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            obj_name = func.value.id
            attr_name = func.attr
            if obj_name in import_table:
                # module.function() call
                module_fqn = import_table[obj_name]
                return f"{module_fqn}.{attr_name}", None
            # Could be self.method(), cls.method(), or a dynamic object
            return None, f"cannot resolve attribute call '{obj_name}.{attr_name}' statically"

    # Complex call (subscript, call result, etc.)
    return None, "call target is not a simple name or attribute expression"


def _local_function_names(tree: ast.Module) -> set[str]:
    """Return all function names defined at any scope in the module."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ---------------------------------------------------------------------------
# Changed-function detection
# ---------------------------------------------------------------------------

def _module_constants(tree: ast.Module | None) -> dict[str, ast.AST]:
    """Top-level `NAME = value` / `NAME: T = value` assignments, by name."""
    constants: dict[str, ast.AST] = {}
    for stmt in tree.body if tree else []:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            constants[stmt.target.id] = stmt.value
    return constants


def _reads_any(func: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in names for n in ast.walk(func))


def _find_changed_symbols(
    base_path: Path,
    head_path: Path,
    changed_files: list[str],
    repo_root_for_log: str = "",
) -> list[tuple[str, str]]:
    """Return list of (fully_qualified_symbol, repo_relative_file_path) for
    functions that changed, were added, or were removed between revisions.
    Only files listed in *changed_files* are inspected.
    """
    changed: list[tuple[str, str]] = []

    for rel_path in changed_files:
        if not rel_path.endswith(".py"):
            continue

        base_file = base_path / rel_path
        head_file = head_path / rel_path

        base_source = base_file.read_text(encoding="utf-8", errors="replace") if base_file.exists() else None
        head_source = head_file.read_text(encoding="utf-8", errors="replace") if head_file.exists() else None

        base_tree = _parse_safe(base_source, rel_path) if base_source is not None else None
        head_tree = _parse_safe(head_source, rel_path) if head_source is not None else None

        module_name = _module_name_from_path(rel_path)

        base_funcs = _collect_functions(base_tree) if base_tree else {}
        head_funcs = _collect_functions(head_tree) if head_tree else {}

        all_names = set(base_funcs) | set(head_funcs)

        for name in all_names:
            fqn = f"{module_name}.{name}"
            if name not in base_funcs:
                changed.append((fqn, rel_path))   # new function
            elif name not in head_funcs:
                changed.append((fqn, rel_path))   # removed function
            elif not _ast_equal(base_funcs[name], head_funcs[name]):
                changed.append((fqn, rel_path))   # modified function

        # A changed module constant (e.g. TAX_RATE) changes every function in the module that
        # reads it, even though their own code is identical. Other modules' reads are not traced.
        base_consts = _module_constants(base_tree)
        head_consts = _module_constants(head_tree)
        changed_consts = {
            name for name in set(base_consts) | set(head_consts)
            if name not in base_consts or name not in head_consts
            or not _ast_equal(base_consts[name], head_consts[name])
        }
        if changed_consts:
            already = {fqn for fqn, _ in changed}
            for name, func in head_funcs.items():
                fqn = f"{module_name}.{name}"
                if fqn not in already and _reads_any(func, changed_consts):
                    changed.append((fqn, rel_path))   # reads a changed constant

    return changed


# ---------------------------------------------------------------------------
# Caller discovery (single hop)
# ---------------------------------------------------------------------------

def _find_callers_of(
    target_fqn: str,
    worktree_path: Path,
    changed_files: set[str],
    repo_root: Path,
    existing_symbols: set[str] | None = None,
) -> tuple[list[CallerEdge], list[UnknownReference]]:
    """Search all Python files in *worktree_path* for call sites that
    resolve to *target_fqn*.

    Returns (callers, unknown_references).
    """
    callers: list[CallerEdge] = []
    unknown_refs: list[UnknownReference] = []

    for py_file in sorted(worktree_path.rglob("*.py")):
        # Compute repo-relative path
        try:
            rel_path = str(py_file.relative_to(worktree_path))
        except ValueError:
            continue

        # Normalise separator
        rel_path = rel_path.replace("\\", "/")

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        tree = _parse_safe(source, rel_path)
        if tree is None:
            continue

        file_module = _module_name_from_path(rel_path)
        import_table = _build_import_table(tree, file_module)
        local_names = _local_function_names(tree)

        # Walk all call nodes in this file
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            line = getattr(node, "lineno", 0)
            fqn, reason = _resolve_call_target(node, import_table, local_names, file_module)

            if fqn == target_fqn:
                # Determine the enclosing function name for the caller symbol
                caller_symbol = _enclosing_function_fqn(node, tree, file_module)
                in_diff = rel_path in changed_files
                callers.append(CallerEdge(
                    symbol=caller_symbol,
                    file_path=rel_path,
                    line=line,
                    in_diff=in_diff,
                    needs_probe=True,
                ))
            elif fqn is None and reason is not None:
                # Only surface as unknown if the name loosely matches the target
                # (to avoid flooding with every unresolved call in the project)
                target_short = target_fqn.split(".")[-1]
                call_text = _call_name_text(node)
                if call_text and target_short in call_text:
                    unknown_refs.append(UnknownReference(
                        file_path=rel_path,
                        line=line,
                        reason=reason,
                    ))

    return callers, unknown_refs


def _enclosing_function_fqn(node: ast.AST, tree: ast.Module, file_module: str) -> str:
    """Return the FQN of the function that directly contains *node*, or
    ``<file_module>.<module_level>`` if the call is at module scope."""
    # Build a parent map
    parent: dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            parent[id(child)] = n

    current = node
    while id(current) in parent:
        current = parent[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"{file_module}.{current.name}"

    return f"{file_module}.<module>"


def _call_name_text(node: ast.Call) -> str | None:
    """Return a short string representation of the called name, or None."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
    return None


# ---------------------------------------------------------------------------
# Two-hop caller discovery
# ---------------------------------------------------------------------------

def _dedup_callers(callers: list[CallerEdge]) -> list[CallerEdge]:
    """Remove duplicate (symbol, file_path, line) triples, keeping first."""
    seen: set[tuple[str, str, int]] = set()
    result = []
    for c in callers:
        key = (c.symbol, c.file_path, c.line)
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def _find_callers_two_hops(
    target_fqn: str,
    base_worktree: Path,
    head_worktree: Path,
    changed_files: set[str],
) -> tuple[list[CallerEdge], list[UnknownReference]]:
    """Find callers of *target_fqn* up to two hops, combining both worktrees."""
    all_callers: list[CallerEdge] = []
    all_unknown: list[UnknownReference] = []

    for wt in (base_worktree, head_worktree):
        hop1_callers, hop1_unknown = _find_callers_of(
            target_fqn, wt, changed_files, wt
        )
        all_callers.extend(hop1_callers)
        all_unknown.extend(hop1_unknown)

        # Hop 2: find callers of each hop-1 caller
        for hop1 in hop1_callers:
            hop2_callers, hop2_unknown = _find_callers_of(
                hop1.symbol, wt, changed_files, wt
            )
            for hop2 in hop2_callers:
                # Attach intermediate edge
                via_edge = {
                    "symbol": hop1.symbol,
                    "file_path": hop1.file_path,
                    "line": hop1.line,
                }
                all_callers.append(CallerEdge(
                    symbol=hop2.symbol,
                    file_path=hop2.file_path,
                    line=hop2.line,
                    in_diff=hop2.in_diff,
                    needs_probe=True,
                    via=[via_edge],
                ))
            all_unknown.extend(hop2_unknown)

    # Deduplicate after combining both worktrees
    all_callers = _dedup_callers(all_callers)

    # Deduplicate unknowns
    seen_unknown: set[tuple[str, int]] = set()
    dedup_unknown = []
    for u in all_unknown:
        key = (u.file_path, u.line)
        if key not in seen_unknown:
            seen_unknown.add(key)
            dedup_unknown.append(u)

    return all_callers, dedup_unknown


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def is_test_caller(file_path: str, symbol: str, test_root: str = "tests") -> bool:
    """Whether a caller is part of the project's own test suite.

    Bob should not be asked to author probes for the tests themselves: they are not
    impacted callers of the change, they are how the change is already checked. Matching is
    on the configured test folder (any path segment) and on the conventional test prefixes,
    so `tests/test_discount.py::test_no_discount` and a top-level `test_x.py` both count.
    """
    normalised = (file_path or "").replace("\\", "/").strip("/")
    if not normalised:
        return False

    root = (test_root or "tests").replace("\\", "/").strip("/")
    if root and any(segment == root for segment in normalised.split("/")[:-1]):
        return True

    filename = normalised.rsplit("/", 1)[-1]
    stem = filename[:-3] if filename.endswith(".py") else filename
    if stem == "conftest" or stem.startswith("test_") or stem.endswith("_test"):
        return True

    # A caller symbol carries the test function's own name too (`tests.test_x.test_y`).
    leaf = (symbol or "").rsplit(".", 1)[-1]
    return leaf.startswith("test_") or leaf.endswith("_test")


def analyze(
    base_worktree: Path,
    head_worktree: Path,
    changed_files: list[str],
    test_root: str = "tests",
) -> AnalysisResult:
    """Perform full impact analysis.

    Parameters
    ----------
    base_worktree:
        Absolute path to the base revision checkout.
    head_worktree:
        Absolute path to the head revision checkout.
    changed_files:
        Repo-relative paths of files that differ between revisions
        (as returned by WorktreeContext.changed_files).
    test_root:
        Folder holding the project's tests, used to mark test callers.
        Callers belonging to the suite get ``needs_probe=False``: they are
        how the change is already checked, not uncovered impact.

    Returns
    -------
    AnalysisResult
        Contains changed_functions with callers and unknown_references.
        No absolute paths appear in the result.
    """
    from bobthereviewer.adapters import (
        LANGUAGES,
        LanguageSpec,
        get_language_spec_for_path,
        get_tier_note,
    )

    changed_set = set(changed_files)
    py_changed = [f for f in changed_files if f.endswith(".py")]
    ts_changed = [
        f for f in changed_files
        if get_language_spec_for_path(f) is not None and get_language_spec_for_path(f).key != "python"
    ]

    languages_in_diff: list[LanguageSpec] = []
    if py_changed or not ts_changed:
        languages_in_diff.append(LANGUAGES["python"])

    seen_lang_keys = {LANGUAGES["python"].key} if (py_changed or not ts_changed) else set()
    for f in ts_changed:
        spec = get_language_spec_for_path(f)
        if spec and spec.key not in seen_lang_keys:
            seen_lang_keys.add(spec.key)
            languages_in_diff.append(spec)

    result = AnalysisResult()
    result.analysis_limits["languages"] = [
        {"language": spec.name, "adapter": spec.adapter, "tier": spec.tier}
        for spec in languages_in_diff
    ]

    for spec in languages_in_diff:
        note = get_tier_note(spec)
        if note and note not in result.analysis_limits["notes"]:
            result.analysis_limits["notes"].append(note)

    # 1. Analyze Python files if any changed
    if py_changed:
        changed_symbols = _find_changed_symbols(base_worktree, head_worktree, py_changed)
        for fqn, file_path in changed_symbols:
            callers, unknowns = _find_callers_two_hops(
                fqn, base_worktree, head_worktree, changed_set
            )
            # Remove self-references (the changed function calling itself)
            callers = [c for c in callers if c.symbol != fqn]
            # Callers that are part of the test suite never need a probe.
            callers = [
                replace(c, needs_probe=False) if is_test_caller(c.file_path, c.symbol, test_root) else c
                for c in callers
            ]

            result.changed_functions.append(ChangedFunction(
                symbol=fqn,
                file_path=file_path,
                callers=callers,
                unknown_references=unknowns,
            ))

    # 2. Analyze non-Python files using Tree-sitter if any changed
    if ts_changed:
        from bobthereviewer.adapters.treesitter import analyze_treesitter_languages

        ts_funcs = analyze_treesitter_languages(
            base_worktree, head_worktree, changed_files, test_root
        )
        result.changed_functions.extend(ts_funcs)

    return result


# ---------------------------------------------------------------------------
# Evidence serialisation helpers
# ---------------------------------------------------------------------------

def changed_function_to_dict(cf: ChangedFunction) -> dict:
    """Convert a ChangedFunction to the evidence schema shape."""
    return {
        "symbol": cf.symbol,
        "file_path": cf.file_path,
        "callers": [
            {
                "symbol": c.symbol,
                "file_path": c.file_path,
                "line": c.line,
                "in_diff": c.in_diff,
                "resolution": "resolved",
                "needs_probe": c.needs_probe,
                "via": c.via,
            }
            for c in cf.callers
        ],
        "unknown_references": [
            {
                "file_path": u.file_path,
                "line": u.line,
                "reason": u.reason,
            }
            for u in cf.unknown_references
        ],
    }
