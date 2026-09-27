"""Tree-sitter impact adapter for non-Python languages.

Implements static impact analysis (changed functions, callers up to 2 hops,
unknown references) using tree-sitter.

Support tiers:
- static (TypeScript, JavaScript, Java, C#, Go):
  Cross-file impact through import and call resolution. No execution.
- static_same_file (Rust, C, C++):
  Same-file callers only (labeled beta). Cross-file calls are never resolved
  to caller edges; unresolved leaf matches go to unknown_references.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from bobthereviewer.adapters.registry import (
    is_generated_source,
    LanguageSpec,
    get_language_spec_for_path,
)
from bobthereviewer.analysis import (
    CallerEdge,
    ChangedFunction,
    UnknownReference,
    _module_name_from_path,
    is_test_caller,
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".bob",
    ".bobreviewer",
}

FUNCTION_NODE_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "abstract_method_signature",
    "method_declaration",
    "constructor_declaration",
    "function_definition",
    "function_item",
    "local_function_statement",
    "method",
    "singleton_method",
}

CLASS_NODE_TYPES = {
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "enum_declaration",
    "struct_declaration",
    "record_declaration",
    "class_specifier",
    "struct_specifier",
    "impl_item",
    "trait_item",
}

CALL_NODE_TYPES = {
    "call_expression",
    "new_expression",
    "await_expression",
    "method_invocation",
    "invocation_expression",
    "function_call_expression",
    "member_call_expression",
    "call",
    "method_call",
}

VARIABLE_NODE_TYPES = {
    "lexical_declaration",
    "variable_declaration",
    "short_var_declaration",
    "var_declaration",
    "const_declaration",
}


@dataclass(frozen=True)
class FunctionDef:
    line: int
    signature: str
    body: str


@dataclass(frozen=True)
class ImportSpec:
    local: str
    imported: str
    source: str
    namespace: bool = False
    line: int = 0


@dataclass(frozen=True)
class CallRef:
    caller: str             # FQN of the enclosing function, e.g. "invoice.priceTotal"
    callee: str             # raw callee expression, e.g. "applyDiscount" or "d.applyDiscount"
    line: int


@dataclass
class TSModule:
    path: str               # repo-relative path, e.g. "src/discount.ts"
    file_module: str        # dotted module name, e.g. "discount"
    spec: LanguageSpec
    text: str
    symbols: dict[str, FunctionDef] = field(default_factory=dict)  # local name -> def
    imports: list[ImportSpec] = field(default_factory=list)
    package_name: str = ""  # Java / Go package
    calls: list[CallRef] = field(default_factory=list)
    error: str | None = None

    # Resolved bindings
    bindings: dict[str, tuple[str, str]] = field(default_factory=dict)  # local -> (target_path, target_fqn)
    namespaces: dict[str, str] = field(default_factory=dict)            # local -> target_path


_PARSER_CACHE: dict[str, Any] = {}


def _get_parser(grammar: str) -> Any:
    if grammar not in _PARSER_CACHE:
        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language

        _PARSER_CACHE[grammar] = Parser(get_language(grammar))
    return _PARSER_CACHE[grammar]


def _node_text(node: Any) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _node_line(node: Any) -> int:
    return int(node.start_point[0]) + 1


def _extract_name(node: Any) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        val = _node_text(name_node).strip()
        if val:
            return val
    decl = node.child_by_field_name("declarator")
    if decl is not None:
        val = _extract_declarator_name(decl)
        if val:
            return val
    for child in node.named_children:
        if child.type in {"identifier", "property_identifier", "type_identifier", "field_identifier"}:
            return _node_text(child).strip()
    return ""


def _extract_declarator_name(node: Any) -> str:
    if node.type in {"identifier", "field_identifier", "property_identifier", "type_identifier"}:
        return _node_text(node).strip()
    named = node.child_by_field_name("declarator") or node.child_by_field_name("name")
    if named is not None:
        val = _extract_declarator_name(named)
        if val:
            return val
    for child in node.named_children:
        val = _extract_declarator_name(child)
        if val:
            return val
    return ""


def _extract_signature(node: Any) -> str:
    parts = []
    for field_name in ("type_parameters", "parameters", "parameter_list", "return_type", "result"):
        val = node.child_by_field_name(field_name)
        if val is not None:
            parts.append(_node_text(val).strip())
    return " ".join(parts)


def _extract_body(node: Any) -> str:
    body = node.child_by_field_name("body")
    return _node_text(body).strip() if body is not None else _node_text(node).strip()


def _parse_ts_js_imports(text: str) -> list[tuple[str, str, str, bool]]:
    """Return [(local, imported, source, is_namespace)] from JS/TS import or require."""
    source_match = re.search(r"""(?:from|require\s*\()\s*["']([^"']+)["']""", text)
    if not source_match:
        return []
    source = source_match.group(1)
    clause = text[: source_match.start()].strip()
    clause = re.sub(r"^export\s+", "", clause)
    clause = re.sub(r"^(?:import|const|let|var)\s+", "", clause).strip()

    result: list[tuple[str, str, str, bool]] = []
    ns_match = re.search(r"""\*\s+as\s+([A-Za-z_$][\w$]*)""", clause)
    if ns_match:
        result.append((ns_match.group(1), "*", source, True))
        return result

    named_match = re.search(r"""\{(.*?)\}""", clause, flags=re.DOTALL)
    if named_match:
        for item in named_match.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            parts = re.split(r"""\s+as\s+|:\s*""", item, maxsplit=1)
            imported = parts[0].strip()
            local = parts[-1].strip()
            if imported and local:
                result.append((local, imported, source, False))

    default_match = re.match(r"""^([A-Za-z_$][\w$]*)""", clause)
    if default_match and not named_match and not ns_match:
        name = default_match.group(1)
        if name not in {"import", "from", "default"}:
            result.append((name, "default", source, False))

    return result


def _parse_java_imports(text: str) -> list[tuple[str, str, str, bool]]:
    """Return [(local, imported, source, is_namespace)] for Java."""
    match = re.search(r"""\bimport\s+(?:static\s+)?(?P<qualified>[\w.]+)\s*;""", text)
    if not match:
        return []
    qualified = match.group("qualified")
    is_static = "static" in text
    parts = qualified.split(".")
    local = parts[-1]
    if local == "*":
        source = ".".join(parts[:-1])
        return [("*", "*", source, True)]
    if is_static:
        source = ".".join(parts[:-1]) if len(parts) > 1 else qualified
        return [(local, local, source, False)]
    # Regular class import: acts as a namespace or class import
    source = qualified
    return [(local, "*", source, True)]


def _parse_csharp_imports(text: str) -> list[tuple[str, str, str, bool]]:
    match = re.search(r"""\busing\s+(?:(?P<alias>[\w]+)\s*=\s*)?(?P<ns>[\w.]+)\s*;""", text)
    if not match:
        return []
    source = match.group("ns")
    alias = match.group("alias")
    local = alias if alias else source.rsplit(".", 1)[-1]
    return [(local, "*", source, True)]


def _parse_go_imports(text: str) -> list[tuple[str, str, str, bool]]:
    result = []
    for match in re.finditer(r'(?:(?P<alias>[\w_.]+)\s+)?"(?P<source>[^"\n]+)"', text):
        source = match.group("source")
        alias = match.group("alias")
        local = None if alias in {None, "import"} else alias
        local = local or source.rstrip("/").rsplit("/", 1)[-1]
        if local != ".":
            result.append((local, "*", source, True))
    return result


def _extract_callee(node: Any) -> str:
    """Extract called function or method name from call node."""
    fn = node.child_by_field_name("function") or node.child_by_field_name("constructor")
    if fn is not None:
        return _node_text(fn).strip()
    name = node.child_by_field_name("name") or node.child_by_field_name("method")
    receiver = node.child_by_field_name("object") or node.child_by_field_name("receiver")
    if name is not None:
        member = _node_text(name).strip()
        if receiver is not None:
            return f"{_node_text(receiver).strip()}.{member}"
        return member
    expr = node.child_by_field_name("expression")
    if expr is not None:
        return _node_text(expr).strip()
    if node.named_children:
        first = node.named_children[0]
        if first.type in {"identifier", "field_identifier", "property_identifier", "scoped_identifier"}:
            return _node_text(first).strip()
    return ""


def _collect_module_data(module: TSModule, root_node: Any) -> None:
    """Recursively collect definitions, imports, and calls from syntax tree."""
    spec = module.spec

    def visit(node: Any, current_func: str | None = None, class_prefix: str | None = None) -> None:
        node_type = node.type

        # Check package declarations (Java / Go)
        if node_type == "package_declaration":
            for child in node.named_children:
                if child.type in {"scoped_identifier", "identifier", "package_identifier"}:
                    module.package_name = _node_text(child).strip()
            return

        # Check import nodes
        if node_type in {
            "import_statement",
            "import_declaration",
            "using_directive",
            "use_declaration",
            "preproc_include",
        }:
            txt = _node_text(node)
            line = _node_line(node)
            items: list[tuple[str, str, str, bool]] = []
            if spec.key in {"typescript", "javascript"}:
                items = _parse_ts_js_imports(txt)
            elif spec.key == "java":
                items = _parse_java_imports(txt)
            elif spec.key == "csharp":
                items = _parse_csharp_imports(txt)
            elif spec.key == "go":
                items = _parse_go_imports(txt)

            for local, imported, src, is_ns in items:
                module.imports.append(ImportSpec(local, imported, src, is_ns, line))
            return

        # Check export statements
        if node_type == "export_statement":
            decl = node.child_by_field_name("declaration")
            if decl is not None:
                visit(decl, current_func, class_prefix)
                return
            # Re-exports: `export { x } from './foo'`
            txt = _node_text(node)
            line = _node_line(node)
            if "from" in txt:
                for local, imported, src, is_ns in _parse_ts_js_imports(txt):
                    module.imports.append(ImportSpec(local, imported, src, is_ns, line))
            return

        # Check class / struct definitions
        if node_type in CLASS_NODE_TYPES:
            cname = _extract_name(node)
            new_prefix = f"{class_prefix}.{cname}" if class_prefix and cname else (cname or class_prefix)
            body = (
                node.child_by_field_name("body")
                or node.child_by_field_name("declaration_list")
                or node.child_by_field_name("class_body")
            )
            if body is not None:
                for child in body.named_children:
                    visit(child, current_func, new_prefix)
            else:
                for child in node.named_children:
                    visit(child, current_func, new_prefix)
            return

        # Check function / method definitions
        if node_type in FUNCTION_NODE_TYPES:
            fname = _extract_name(node)
            if fname:
                symbol = f"{class_prefix}.{fname}" if class_prefix else fname
                sig = _extract_signature(node)
                b = _extract_body(node)
                module.symbols[symbol] = FunctionDef(line=_node_line(node), signature=sig, body=b)
                current_func = symbol

            body = node.child_by_field_name("body")
            if body is not None:
                for child in body.named_children:
                    visit(child, current_func, class_prefix)
            else:
                for child in node.named_children:
                    visit(child, current_func, class_prefix)
            return

        # Check variable declarations for arrow functions / function expressions
        if node_type in VARIABLE_NODE_TYPES and current_func is None:
            for child in node.named_children:
                if child.type in {"variable_declarator", "var_spec", "const_spec"}:
                    vname = _extract_name(child)
                    val = child.child_by_field_name("value")
                    if val is not None and val.type in {
                        "arrow_function",
                        "function_expression",
                        "generator_function",
                    }:
                        symbol = f"{class_prefix}.{vname}" if class_prefix else vname
                        module.symbols[symbol] = FunctionDef(
                            line=_node_line(child),
                            signature=_extract_signature(val),
                            body=_extract_body(val),
                        )
                        for sub in val.named_children:
                            visit(sub, symbol, class_prefix)
                        continue
            # Continue scanning any other children
            for child in node.named_children:
                visit(child, current_func, class_prefix)
            return

        # Check call nodes
        if node_type in CALL_NODE_TYPES:
            callee = _extract_callee(node)
            if callee:
                enclosing = f"{module.file_module}.{current_func}" if current_func else f"{module.file_module}.<module>"
                module.calls.append(CallRef(caller=enclosing, callee=callee, line=_node_line(node)))

        for child in node.named_children:
            visit(child, current_func, class_prefix)

    visit(root_node)


def _load_module(root: Path, rel_path: str, spec: LanguageSpec) -> TSModule | None:
    full_path = root / rel_path
    if not full_path.is_file():
        return None
    try:
        text = full_path.read_text(encoding="utf-8")
    except Exception as exc:
        mod = TSModule(
            path=rel_path,
            file_module=_module_name_from_path(rel_path),
            spec=spec,
            text="",
            error=f"read error: {exc}",
        )
        return mod

    grammar = spec.grammar or "typescript"
    if rel_path.endswith((".tsx", ".jsx")):
        grammar = "tsx"

    mod = TSModule(
        path=rel_path,
        file_module=_module_name_from_path(rel_path),
        spec=spec,
        text=text,
    )

    try:
        parser = _get_parser(grammar)
        tree = parser.parse(text.encode("utf-8"))
        if tree.root_node.has_error:
            # Tolerant parsing: still collect what we can, but mark error
            _collect_module_data(mod, tree.root_node)
        else:
            _collect_module_data(mod, tree.root_node)
    except Exception as exc:
        mod.error = f"parse error: {exc}"

    return mod


def _load_codebase(root: Path) -> dict[str, TSModule]:
    """Load and parse all non-Python files under root with registered adapters."""
    modules: dict[str, TSModule] = {}
    if not root.exists():
        return modules

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        spec = get_language_spec_for_path(rel)
        if spec is None or spec.key == "python" or is_generated_source(path):
            continue
        mod = _load_module(root, rel, spec)
        if mod is not None:
            modules[rel] = mod

    return modules


def _resolve_import_path(source_path: str, specifier: str, modules: dict[str, TSModule], spec: LanguageSpec) -> str | None:
    """Resolve an import specifier to a module path in modules."""
    raw_specifier = specifier.replace("\\", "/")
    if raw_specifier.startswith("."):
        parent_dir = PurePosixPath(source_path).parent.as_posix()
        norm = posixpath.normpath(f"{parent_dir}/{raw_specifier}" if parent_dir != "." else raw_specifier)
        norm = norm.lstrip("./")

        candidates = [norm]
        for ext in spec.extensions:
            candidates.append(f"{norm}{ext}")
            candidates.append(f"{norm}/index{ext}")
        # Strip trailing extension if specifier already had one
        stem = posixpath.splitext(norm)[0]
        for ext in spec.extensions:
            candidates.append(f"{stem}{ext}")

        for cand in candidates:
            if cand in modules:
                return cand
        return None

    # Non-relative imports (Java, Go, C#)
    if spec.key == "java":
        cand = raw_specifier.replace(".", "/")
        for path in modules:
            if path.endswith(f"{cand}.java") or path.endswith(f"/{cand}.java"):
                return path
        # Try matching class stem
        leaf = raw_specifier.split(".")[-1]
        matches = [p for p in modules if p.endswith(f"/{leaf}.java") or p == f"{leaf}.java"]
        if len(matches) == 1:
            return matches[0]
        return None

    if spec.key == "csharp":
        leaf = raw_specifier.split(".")[-1]
        matches = [p for p in modules if p.endswith(f"/{leaf}.cs") or p == f"{leaf}.cs"]
        if len(matches) == 1:
            return matches[0]
        return None

    if spec.key == "go":
        pkg = raw_specifier.rstrip("/").rsplit("/", 1)[-1]
        matches = [p for p in modules if f"/{pkg}/" in p or p.startswith(f"{pkg}/")]
        if matches:
            return sorted(matches, key=len)[0]
        return None

    return None


def _bind_imports(modules: dict[str, TSModule]) -> None:
    """Bind imported names to target modules and symbols."""
    for mod in modules.values():
        for imp in mod.imports:
            target_path = _resolve_import_path(mod.path, imp.source, modules, mod.spec)
            if not target_path or target_path not in modules:
                continue
            target_mod = modules[target_path]

            if imp.namespace:
                # Namespace import: e.g. import * as discount from "./discount"
                mod.namespaces[imp.local] = target_path
                # Also bind all symbols if wildcard
                if imp.imported == "*":
                    for sym in target_mod.symbols:
                        fqn = f"{target_mod.file_module}.{sym}"
                        leaf = sym.rsplit(".", 1)[-1]
                        mod.bindings.setdefault(leaf, (target_path, fqn))
            else:
                # Named or default import
                # Match imported symbol in target module
                target_sym = imp.imported
                if target_sym == "default" or target_sym not in target_mod.symbols:
                    # Look for exact symbol or single candidate
                    candidates = [s for s in target_mod.symbols if s == imp.imported or s.rsplit(".", 1)[-1] == imp.imported]
                    if len(candidates) == 1:
                        target_sym = candidates[0]
                fqn = f"{target_mod.file_module}.{target_sym}"
                mod.bindings[imp.local] = (target_path, fqn)

        # Same-package resolution for Java
        if mod.spec.key == "java" and mod.package_name:
            for other_path, other_mod in modules.items():
                if other_path != mod.path and other_mod.package_name == mod.package_name:
                    mod.namespaces.setdefault(other_mod.file_module.split(".")[-1], other_path)
                    for sym in other_mod.symbols:
                        leaf = sym.rsplit(".", 1)[-1]
                        mod.bindings.setdefault(leaf, (other_path, f"{other_mod.file_module}.{sym}"))


def _resolve_call_site(
    module: TSModule,
    call: CallRef,
    modules: dict[str, TSModule],
) -> tuple[tuple[str, str] | None, str | None]:
    """Resolve a call to (target_file_path, target_fqn) or return (None, reason)."""
    callee = call.callee.strip()
    spec = module.spec

    # static_same_file tier (Rust, C, C++): only same-file callers are resolved
    if spec.tier == "static_same_file":
        leaf = callee.rsplit("::", 1)[-1].rsplit(".", 1)[-1].rsplit("->", 1)[-1]
        for sym in module.symbols:
            if sym == leaf or sym.rsplit(".", 1)[-1] == leaf:
                return (module.path, f"{module.file_module}.{sym}"), None
        return None, "same-file caller resolution only (tier static_same_file, beta)"

    # static tier:
    # 1. Direct call matching local function
    if callee in module.symbols:
        return (module.path, f"{module.file_module}.{callee}"), None
    for sym in module.symbols:
        if sym.rsplit(".", 1)[-1] == callee:
            return (module.path, f"{module.file_module}.{sym}"), None

    # 2. Direct call matching imported name
    if callee in module.bindings:
        return module.bindings[callee], None

    # 3. Member access: obj.method or Namespace.func
    if "." in callee or "::" in callee:
        parts = re.split(r"\.|::|->", callee, maxsplit=1)
        prefix, member = parts[0].strip(), parts[1].strip()
        if prefix in module.namespaces:
            target_path = module.namespaces[prefix]
            target_mod = modules.get(target_path)
            if target_mod:
                for sym in target_mod.symbols:
                    if sym == member or sym.rsplit(".", 1)[-1] == member:
                        return (target_path, f"{target_mod.file_module}.{sym}"), None
                return None, f"dynamic member access '{callee}'"

    return None, f"unresolved call '{callee}'"


def _detect_changed_functions_for_language(
    base_modules: dict[str, TSModule],
    head_modules: dict[str, TSModule],
    changed_files: list[str],
) -> list[tuple[str, str]]:
    """Detect changed function FQNs and their file paths across revisions."""
    changed_symbols: list[tuple[str, str]] = []

    for rel_path in changed_files:
        spec = get_language_spec_for_path(rel_path)
        if spec is None or spec.key == "python":
            continue

        base_mod = base_modules.get(rel_path)
        head_mod = head_modules.get(rel_path)

        base_syms = base_mod.symbols if base_mod else {}
        head_syms = head_mod.symbols if head_mod else {}

        all_names = sorted(set(base_syms.keys()) | set(head_syms.keys()))
        file_module = (head_mod or base_mod).file_module

        for sym in all_names:
            b = base_syms.get(sym)
            h = head_syms.get(sym)
            is_changed = False

            if b is None or h is None:
                is_changed = True
            elif b.body != h.body or b.signature != h.signature:
                is_changed = True

            if is_changed:
                fqn = f"{file_module}.{sym}"
                changed_symbols.append((fqn, rel_path))

    return changed_symbols


def _find_callers_and_unknowns_ts(
    target_fqn: str,
    target_file: str,
    target_spec: LanguageSpec,
    modules: dict[str, TSModule],
    changed_files: set[str],
) -> tuple[list[CallerEdge], list[UnknownReference]]:
    """Find direct callers and matching unknowns of target_fqn in modules."""
    callers: list[CallerEdge] = []
    unknowns: list[UnknownReference] = []
    target_leaf = target_fqn.rsplit(".", 1)[-1]

    for mod_path, module in modules.items():
        # If target language is static_same_file, only search the target file
        if target_spec.tier == "static_same_file" and mod_path != target_file:
            continue

        for call in module.calls:
            resolved, reason = _resolve_call_site(module, call, modules)
            if resolved is not None:
                res_path, res_fqn = resolved
                if res_fqn == target_fqn and (target_spec.tier != "static_same_file" or res_path == target_file):
                    callers.append(
                        CallerEdge(
                            symbol=call.caller,
                            file_path=module.path,
                            line=call.line,
                            in_diff=module.path in changed_files,
                            needs_probe=True,
                        )
                    )
            else:
                # Unresolved call: check if callee leaf matches target_leaf
                callee_leaf = call.callee.rsplit(".", 1)[-1].rsplit("::", 1)[-1].rsplit("->", 1)[-1]
                if callee_leaf == target_leaf:
                    unknowns.append(
                        UnknownReference(
                            file_path=module.path,
                            line=call.line,
                            reason=reason or f"unresolved reference to '{call.callee}'",
                        )
                    )

    return callers, unknowns


def analyze_treesitter_languages(
    base_worktree: Path,
    head_worktree: Path,
    changed_files: list[str],
    test_root: str = "tests",
) -> list[ChangedFunction]:
    """Analyze non-Python changed files using Tree-sitter adapters."""
    # Check if any changed file uses a Tree-sitter language
    ts_changed = [
        f for f in changed_files
        if get_language_spec_for_path(f) is not None and get_language_spec_for_path(f).key != "python"
    ]
    if not ts_changed:
        return []

    base_modules = _load_codebase(base_worktree)
    head_modules = _load_codebase(head_worktree)
    _bind_imports(base_modules)
    _bind_imports(head_modules)

    changed_symbols = _detect_changed_functions_for_language(base_modules, head_modules, ts_changed)
    changed_set = set(changed_files)
    result_functions: list[ChangedFunction] = []

    for target_fqn, target_file in changed_symbols:
        spec = get_language_spec_for_path(target_file)
        if spec is None:
            continue

        all_callers: list[CallerEdge] = []
        all_unknowns: list[UnknownReference] = []

        # Find direct callers across base and head
        for modules in (base_modules, head_modules):
            hop1_callers, hop1_unknowns = _find_callers_and_unknowns_ts(
                target_fqn, target_file, spec, modules, changed_set
            )
            all_callers.extend(hop1_callers)
            all_unknowns.extend(hop1_unknowns)

            # Hop 2 callers (only for static tier, not static_same_file)
            if spec.tier != "static_same_file":
                for hop1 in hop1_callers:
                    hop1_spec = get_language_spec_for_path(hop1.file_path) or spec
                    hop2_callers, hop2_unknowns = _find_callers_and_unknowns_ts(
                        hop1.symbol, hop1.file_path, hop1_spec, modules, changed_set
                    )
                    for hop2 in hop2_callers:
                        all_callers.append(
                            CallerEdge(
                                symbol=hop2.symbol,
                                file_path=hop2.file_path,
                                line=hop2.line,
                                in_diff=hop2.in_diff,
                                needs_probe=True,
                                via=[{
                                    "symbol": hop1.symbol,
                                    "file_path": hop1.file_path,
                                    "line": hop1.line,
                                }],
                            )
                        )
                    all_unknowns.extend(hop2_unknowns)

        # Remove self-references
        all_callers = [c for c in all_callers if c.symbol != target_fqn]

        # Deduplicate callers by (symbol, file_path, line)
        seen_callers: set[tuple[str, str, int]] = set()
        dedup_callers: list[CallerEdge] = []
        for c in all_callers:
            key = (c.symbol, c.file_path, c.line)
            if key not in seen_callers:
                seen_callers.add(key)
                # Check test caller status
                is_test = is_test_caller(c.file_path, c.symbol, test_root)
                dedup_callers.append(
                    CallerEdge(
                        symbol=c.symbol,
                        file_path=c.file_path,
                        line=c.line,
                        in_diff=c.in_diff,
                        needs_probe=False if is_test else c.needs_probe,
                        via=c.via,
                    )
                )

        # Deduplicate unknowns by (file_path, line)
        seen_unknowns: set[tuple[str, int]] = set()
        dedup_unknowns: list[UnknownReference] = []
        for u in all_unknowns:
            ukey = (u.file_path, u.line)
            if ukey not in seen_unknowns:
                seen_unknowns.add(ukey)
                dedup_unknowns.append(u)

        result_functions.append(
            ChangedFunction(
                symbol=target_fqn,
                file_path=target_file,
                callers=dedup_callers,
                unknown_references=dedup_unknowns,
            )
        )

    return result_functions
