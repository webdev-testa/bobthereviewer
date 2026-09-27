"""Tests for multi-language impact analysis and report tiers (Wave 3 P1, Block I)."""

import json
from pathlib import Path

import pytest

from bobthereviewer.adapters import (
    LANGUAGES,
    format_analyzed_as,
    get_language_spec_for_path,
    get_tier_note,
)
from bobthereviewer.analysis import analyze, changed_function_to_dict
from bobthereviewer.cli import _print_evidence_summary
from bobthereviewer.contracts import validate_evidence
from bobthereviewer.report import render_markdown


def _write_files(root: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        p = root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_registry_specs_and_tiers():
    assert LANGUAGES["python"].tier == "full"
    assert LANGUAGES["typescript"].tier == "static"
    assert LANGUAGES["javascript"].tier == "static"
    assert LANGUAGES["java"].tier == "static"
    assert LANGUAGES["rust"].tier == "static_same_file"

    assert get_language_spec_for_path("src/index.ts").name == "TypeScript"
    assert get_language_spec_for_path("src/index.tsx").name == "TypeScript"
    assert get_language_spec_for_path("src/app.jsx").name == "JavaScript"
    assert get_language_spec_for_path("com/Main.java").name == "Java"
    assert get_language_spec_for_path("lib.rs").name == "Rust"

    assert get_tier_note(LANGUAGES["python"]) is None
    ts_note = get_tier_note(LANGUAGES["typescript"])
    assert ts_note == "TypeScript: static impact only (tier static) — no tests or probes are run for this language."
    rust_note = get_tier_note(LANGUAGES["rust"])
    assert rust_note == "Rust: same-file callers only (tier static_same_file, beta) — no tests or probes are run for this language."


def test_typescript_cross_file_callers(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    ts_discount_base = """
export function applyDiscount(price: number, rate: number): number {
    return price - price * rate;
}
"""
    ts_discount_head = """
export function applyDiscount(price: number, rate: number): number {
    return Math.round((price - price * rate) * 100) / 100;
}
"""
    ts_invoice = """
import { applyDiscount } from "./discount";

export function priceTotal(quantity: number, price: number): number {
    return applyDiscount(quantity * price, 0.1);
}
"""
    _write_files(base_dir, {
        "src/discount.ts": ts_discount_base,
        "src/invoice.ts": ts_invoice,
    })
    _write_files(head_dir, {
        "src/discount.ts": ts_discount_head,
        "src/invoice.ts": ts_invoice,
    })

    result = analyze(base_dir, head_dir, ["src/discount.ts"])

    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert cf.symbol == "discount.applyDiscount"
    assert cf.file_path == "src/discount.ts"

    assert len(cf.callers) == 1
    caller = cf.callers[0]
    assert caller.symbol == "invoice.priceTotal"
    assert caller.file_path == "src/invoice.ts"
    assert caller.in_diff is False
    assert caller.needs_probe is True

    # Tier and notes verification
    langs = result.analysis_limits.get("languages", [])
    assert len(langs) == 1
    assert langs[0] == {"language": "TypeScript", "adapter": "tree-sitter", "tier": "static"}
    assert any("TypeScript: static impact only" in n for n in result.analysis_limits.get("notes", []))


def test_typescript_namespace_import(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    _write_files(base_dir, {
        "src/discount.ts": "export function applyDiscount(p: number): number { return p; }",
        "src/invoice.ts": """
import * as d from "./discount";
export function total(p: number): number {
    return d.applyDiscount(p);
}
""",
    })
    _write_files(head_dir, {
        "src/discount.ts": "export function applyDiscount(p: number): number { return p * 0.9; }",
        "src/invoice.ts": """
import * as d from "./discount";
export function total(p: number): number {
    return d.applyDiscount(p);
}
""",
    })

    result = analyze(base_dir, head_dir, ["src/discount.ts"])
    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert cf.symbol == "discount.applyDiscount"
    assert len(cf.callers) == 1
    assert cf.callers[0].symbol == "invoice.total"


def test_java_cross_file_callers(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    java_discount_base = """
package com.example;

public class Discount {
    public static double applyDiscount(double price, double rate) {
        return price - price * rate;
    }
}
"""
    java_discount_head = """
package com.example;

public class Discount {
    public static double applyDiscount(double price, double rate) {
        return Math.round(price - price * rate);
    }
}
"""
    java_invoice = """
package com.example;
import com.example.Discount;

public class Invoice {
    public static double priceTotal(double q, double p) {
        return Discount.applyDiscount(q * p, 0.1);
    }
}
"""
    _write_files(base_dir, {
        "src/com/example/Discount.java": java_discount_base,
        "src/com/example/Invoice.java": java_invoice,
    })
    _write_files(head_dir, {
        "src/com/example/Discount.java": java_discount_head,
        "src/com/example/Invoice.java": java_invoice,
    })

    result = analyze(base_dir, head_dir, ["src/com/example/Discount.java"])

    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert "applyDiscount" in cf.symbol
    assert cf.file_path == "src/com/example/Discount.java"

    assert len(cf.callers) >= 1
    assert any("priceTotal" in c.symbol and c.file_path == "src/com/example/Invoice.java" for c in cf.callers)

    langs = result.analysis_limits.get("languages", [])
    assert any(l["language"] == "Java" and l["tier"] == "static" for l in langs)
    assert any("Java: static impact only" in n for n in result.analysis_limits.get("notes", []))


def test_rust_same_file_callers_only(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    rust_lib_base = """
pub fn apply_discount(p: f64, r: f64) -> f64 {
    p - p * r
}

pub fn local_caller(q: f64, p: f64) -> f64 {
    apply_discount(q * p, 0.1)
}
"""
    rust_lib_head = """
pub fn apply_discount(p: f64, r: f64) -> f64 {
    (p - p * r).round()
}

pub fn local_caller(q: f64, p: f64) -> f64 {
    apply_discount(q * p, 0.1)
}
"""
    rust_other = """
use crate::apply_discount;

pub fn external_caller(p: f64) -> f64 {
    apply_discount(p, 0.2)
}
"""
    _write_files(base_dir, {
        "src/lib.rs": rust_lib_base,
        "src/other.rs": rust_other,
    })
    _write_files(head_dir, {
        "src/lib.rs": rust_lib_head,
        "src/other.rs": rust_other,
    })

    result = analyze(base_dir, head_dir, ["src/lib.rs"])

    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert "apply_discount" in cf.symbol
    assert cf.file_path == "src/lib.rs"

    # In static_same_file tier (Rust), only same-file callers are resolved
    caller_files = {c.file_path for c in cf.callers}
    assert "src/lib.rs" in caller_files
    assert "src/other.rs" not in caller_files

    langs = result.analysis_limits.get("languages", [])
    assert any(l["language"] == "Rust" and l["tier"] == "static_same_file" for l in langs)
    assert any("Rust: same-file callers only (tier static_same_file, beta)" in n for n in result.analysis_limits.get("notes", []))


def test_mixed_python_and_typescript_diff(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    py_base = "def py_calc(x):\n    return x + 1\n"
    py_head = "def py_calc(x):\n    return x + 2\n"
    ts_base = "export function tsCalc(x: number): number { return x + 1; }\n"
    ts_head = "export function tsCalc(x: number): number { return x + 2; }\n"

    _write_files(base_dir, {
        "calc.py": py_base,
        "calc.ts": ts_base,
    })
    _write_files(head_dir, {
        "calc.py": py_head,
        "calc.ts": ts_head,
    })

    result = analyze(base_dir, head_dir, ["calc.py", "calc.ts"])

    symbols = {cf.symbol for cf in result.changed_functions}
    assert "calc.py_calc" in symbols
    assert "calc.tsCalc" in symbols

    langs = result.analysis_limits.get("languages", [])
    lang_names = [l["language"] for l in langs]
    assert "Python" in lang_names
    assert "TypeScript" in lang_names

    formatted = format_analyzed_as(langs)
    assert "Python (full)" in formatted
    assert "TypeScript (static, no execution)" in formatted


def test_pure_python_diff_unchanged(tmp_path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"

    _write_files(base_dir, {
        "discount.py": "def apply_discount(p, r):\n    return p - p * r\n",
        "invoice.py": "from discount import apply_discount\ndef calc(q, p):\n    return apply_discount(q * p, 0.1)\n",
    })
    _write_files(head_dir, {
        "discount.py": "def apply_discount(p, r):\n    return round(p - p * r, 2)\n",
        "invoice.py": "from discount import apply_discount\ndef calc(q, p):\n    return apply_discount(q * p, 0.1)\n",
    })

    result = analyze(base_dir, head_dir, ["discount.py"])
    assert len(result.changed_functions) == 1
    cf = result.changed_functions[0]
    assert cf.symbol == "discount.apply_discount"
    assert len(cf.callers) == 1
    assert cf.callers[0].symbol == "invoice.calc"

    langs = result.analysis_limits.get("languages", [])
    assert len(langs) == 1
    assert langs[0] == {"language": "Python", "adapter": "python-ast", "tier": "full"}
    assert format_analyzed_as(langs) == "Python (full)"


def test_report_and_cli_analyzed_as_display(capsys):
    # Python-only evidence
    py_evidence = {
        "schema_version": "1",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "generated_at": "2025-01-01T00:00:00Z",
        "repository": "https://github.com/example/repo",
        "base_ref": "main",
        "head_ref": "feature",
        "base_commit": "a" * 40,
        "head_commit": "b" * 40,
        "triage": {"category": "code", "skipped": False, "skip_reason": None},
        "analysis_limits": {
            "max_hops": 2,
            "languages": [{"language": "Python", "adapter": "python-ast", "tier": "full"}],
        },
        "changed_functions": [],
        "test_results": {"base": {}, "head": {}},
        "probe_results": [],
        "decisions": [],
    }

    md_py = render_markdown(py_evidence)
    assert "| **Triage** | Code change |" in md_py
    assert "| **Analyzed as** | Python (full) |" in md_py

    _print_evidence_summary(py_evidence)
    out_py = capsys.readouterr().out
    assert "triage   : code" in out_py
    assert "Analyzed as: Python (full)" in out_py

    # TypeScript-only evidence
    ts_evidence = {
        **py_evidence,
        "analysis_limits": {
            "max_hops": 2,
            "languages": [{"language": "TypeScript", "adapter": "tree-sitter", "tier": "static"}],
        },
    }

    md_ts = render_markdown(ts_evidence)
    assert "| **Analyzed as** | TypeScript (static, no execution) |" in md_ts

    _print_evidence_summary(ts_evidence)
    out_ts = capsys.readouterr().out
    assert "Analyzed as: TypeScript (static, no execution)" in out_ts

    # Missing languages in evidence -> fallback Python (full)
    fallback_evidence = {
        **py_evidence,
        "analysis_limits": {"max_hops": 2},
    }
    md_fallback = render_markdown(fallback_evidence)
    assert "| **Analyzed as** | Python (full) |" in md_fallback

    # Evidence contract validation
    validate_evidence(py_evidence)
    validate_evidence(ts_evidence)


def test_cli_analyze_typescript_acceptance(tmp_path, capsys):
    import subprocess
    from bobthereviewer.cli import main

    repo = tmp_path / "ts_repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

    d = repo / "src"
    d.mkdir(parents=True)
    (d / "discount.ts").write_text(
        "export function applyDiscount(price: number, rate: number): number {\n"
        "  return price - price * rate;\n"
        "}\n",
        encoding="utf-8",
    )
    (d / "invoice.ts").write_text(
        "import { applyDiscount } from './discount';\n\n"
        "export function priceTotal(quantity: number, price: number): number {\n"
        "  return applyDiscount(quantity * price, 0.1);\n"
        "}\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

    (d / "discount.ts").write_text(
        "export function applyDiscount(price: number, rate: number): number {\n"
        "  return Math.round((price - price * rate) * 100) / 100;\n"
        "}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "rounding change"], cwd=repo, check=True)

    out_dir = tmp_path / "out"
    code = main([
        "analyze",
        "--before", "HEAD~1",
        "--after", "HEAD",
        "--repo-dir", str(repo),
        "--output", str(out_dir),
    ])
    assert code == 0

    out = capsys.readouterr().out
    assert "triage   : code" in out
    assert "Analyzed as: TypeScript (static, no execution)" in out
    assert "discount.applyDiscount" in out
    assert "invoice.priceTotal" in out
    assert "src/invoice.ts:" in out

    evidence_file = out_dir / "evidence.json"
    assert evidence_file.exists()
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert evidence["triage"]["category"] == "code"
    assert evidence["triage"]["skipped"] is False
    assert any("TypeScript: static impact only" in n for n in evidence["analysis_limits"]["notes"])
    validate_evidence(evidence)

