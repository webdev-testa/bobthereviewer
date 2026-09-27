"""Language adapter registry and tier definitions.

The registry is explicit: each supported language maps to an adapter
and a defined tier (GAP_REVIEW Wave 3 P1, Block I):
- full: Python only (AST impact + tests + probes).
- static: TypeScript, JavaScript, Java, C#, Go (cross-file impact, no execution).
- static_same_file: Rust, C, C++ (same-file callers only, labeled beta).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TIERS = ("full", "static", "static_same_file")


@dataclass(frozen=True)
class LanguageSpec:
    name: str              # e.g. "TypeScript", "Python"
    key: str               # e.g. "typescript", "python"
    tier: str              # "full" | "static" | "static_same_file"
    adapter: str           # "python-ast" | "tree-sitter"
    extensions: tuple[str, ...]
    grammar: str | None = None


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        name="Python",
        key="python",
        tier="full",
        adapter="python-ast",
        extensions=(".py",),
        grammar=None,
    ),
    "typescript": LanguageSpec(
        name="TypeScript",
        key="typescript",
        tier="static",
        adapter="tree-sitter",
        extensions=(".ts", ".tsx"),
        grammar="typescript",
    ),
    "javascript": LanguageSpec(
        name="JavaScript",
        key="javascript",
        tier="static",
        adapter="tree-sitter",
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        grammar="javascript",
    ),
    "java": LanguageSpec(
        name="Java",
        key="java",
        tier="static",
        adapter="tree-sitter",
        extensions=(".java",),
        grammar="java",
    ),
    "csharp": LanguageSpec(
        name="C#",
        key="csharp",
        tier="static",
        adapter="tree-sitter",
        extensions=(".cs",),
        grammar="c_sharp",
    ),
    "go": LanguageSpec(
        name="Go",
        key="go",
        tier="static",
        adapter="tree-sitter",
        extensions=(".go",),
        grammar="go",
    ),
    "rust": LanguageSpec(
        name="Rust",
        key="rust",
        tier="static_same_file",
        adapter="tree-sitter",
        extensions=(".rs",),
        grammar="rust",
    ),
    "c": LanguageSpec(
        name="C",
        key="c",
        tier="static_same_file",
        adapter="tree-sitter",
        extensions=(".c", ".h"),
        grammar="c",
    ),
    "cpp": LanguageSpec(
        name="C++",
        key="cpp",
        tier="static_same_file",
        adapter="tree-sitter",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hxx"),
        grammar="cpp",
    ),
}

EXTENSION_TO_LANGUAGE: dict[str, LanguageSpec] = {}
for spec in LANGUAGES.values():
    for ext in spec.extensions:
        EXTENSION_TO_LANGUAGE[ext] = spec


def get_language_spec_for_path(path: str | Path) -> LanguageSpec | None:
    """Return the LanguageSpec for a given file path by extension."""
    p = Path(path)
    return EXTENSION_TO_LANGUAGE.get(p.suffix.lower())


def get_tier_note(spec: LanguageSpec) -> str | None:
    """Plain-language caveat added to analysis_limits.notes for non-full tiers."""
    if spec.tier == "full":
        return None
    if spec.tier == "static":
        return f"{spec.name}: static impact only (tier static) — no tests or probes are run for this language."
    if spec.tier == "static_same_file":
        return f"{spec.name}: same-file callers only (tier static_same_file, beta) — no tests or probes are run for this language."
    return f"{spec.name}: tier {spec.tier} — no tests or probes are run for this language."


def format_analyzed_as(languages: list[dict] | None) -> str:
    """Format the list of languages and tiers for report display.

    Example outputs:
    - Python (full)
    - TypeScript (static, no execution)
    - Rust (static, same-file callers only)
    - Python (full), TypeScript (static, no execution)
    """
    if not languages:
        return "Python (full)"
    parts = []
    for entry in languages:
        lang = entry.get("language", "")
        tier = entry.get("tier", "full")
        if tier == "full":
            desc = "full"
        elif tier == "static":
            desc = "static, no execution"
        elif tier == "static_same_file":
            desc = "static, same-file callers only"
        else:
            desc = tier
        parts.append(f"{lang} ({desc})")
    return ", ".join(parts) if parts else "Python (full)"
