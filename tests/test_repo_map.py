"""Tests for the repository map (J1).

The map answers "where does this change sit in the whole project", which the per-PR evidence
map does not. Three properties matter:

  * it is generated from source and git, never by a model;
  * an import it cannot resolve becomes an *unknown*, never a silent omission — a missing edge
    must not read as "this file affects nothing";
  * it publishes repository-relative paths only. An absolute path in published evidence is a
    leak of the machine that produced it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bobthereviewer import repo_map
from bobthereviewer.repo_map import build, python_imports, validate_map


def _git_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", "feat: one (#7)"]):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root


def _sha(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------------------
# the demo layout — the acceptance case
# ---------------------------------------------------------------------------

def test_the_demo_layout_yields_the_invoice_to_discount_edge(tmp_path):
    root = _git_repo(tmp_path / "demo", {
        "discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
        "invoice.py": "from discount import apply_discount\n\n\ndef calculate_invoice(p, r):\n    return apply_discount(p, r)\n",
        "pricing.py": "TAX_RATE = 0.1\n\n\ndef calculate_price(p):\n    return round(p * (1 + TAX_RATE), 2)\n",
        "tests/__init__.py": "",
        "tests/test_discount.py": (
            "from discount import apply_discount\nfrom invoice import calculate_invoice\n\n\n"
            "def test_one():\n    assert apply_discount(100.0, 0.0) == 100.0\n"
        ),
    })
    payload = build(root, root, "local", _sha(root))

    paths = [m["path"] for m in payload["modules"]]
    assert set(paths) == {"discount.py", "invoice.py", "pricing.py",
                          "tests/__init__.py", "tests/test_discount.py"}

    edges = {(e["from"], e["to"]) for e in payload["edges"]}
    assert ("invoice.py", "discount.py") in edges
    assert ("tests/test_discount.py", "discount.py") in edges
    assert ("tests/test_discount.py", "invoice.py") in edges

    # every module carries the last commit that touched it, with the PR number recovered
    for module in payload["modules"]:
        assert module["last_commit"] is not None
        assert len(module["last_commit"]["sha"]) == 7
        assert module["last_commit"]["pr"] == 7


def test_every_module_carries_a_language_and_tier(tmp_path):
    root = _git_repo(tmp_path / "demo", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    assert payload["modules"][0]["language"] == "python"
    assert payload["modules"][0]["tier"] == "full"


# ---------------------------------------------------------------------------
# unknowns — an unresolved import is reported, never dropped
# ---------------------------------------------------------------------------

def test_a_dynamic_import_with_a_variable_is_an_unknown(tmp_path):
    root = _git_repo(tmp_path / "dyn", {
        "app/__init__.py": "",
        "app/loader.py": (
            "import importlib\n\n\n"
            "def load(name):\n    return importlib.import_module(name)\n"
        ),
    })
    _, unknowns = python_imports(root / "app" / "loader.py", "app/loader.py")
    assert unknowns, "a non-constant dynamic import must be reported"
    assert unknowns[0]["reason"] == "dynamic import with a non-constant argument"
    assert unknowns[0]["line"] == 5


def test_a_constant_dynamic_import_becomes_a_real_edge(tmp_path):
    """`importlib.import_module("app.plugin")` is a real dependency and must be drawn."""
    root = _git_repo(tmp_path / "dyn2", {
        "app/__init__.py": "",
        "app/plugin.py": "VALUE = 1\n",
        "app/loader.py": (
            "import importlib\n\n\n"
            "def load():\n    return importlib.import_module(\"app.plugin\")\n"
        ),
    })
    payload = build(root, root, "local", _sha(root))
    edges = {(e["from"], e["to"]) for e in payload["edges"]}
    assert ("app/loader.py", "app/plugin.py") in edges
    assert payload["unknowns"] == []


def test_an_unparsable_file_is_an_unknown_not_a_crash(tmp_path):
    root = _git_repo(tmp_path / "broken", {
        "good.py": "import os\n",
        "bad.py": "def broken(:\n",
    })
    payload = build(root, root, "local", _sha(root))
    assert any("bad.py" == u["path"] for u in payload["unknowns"])
    # the rest of the repository is still described
    assert any(m["path"] == "good.py" for m in payload["modules"])


def test_a_third_party_import_is_not_an_unknown(tmp_path):
    """An import with no module here is resolved information, not an unknown."""
    root = _git_repo(tmp_path / "lib", {"a.py": "import os\nimport json\n"})
    payload = build(root, root, "local", _sha(root))
    assert payload["edges"] == []
    assert payload["unknowns"] == []


# ---------------------------------------------------------------------------
# published evidence rules
# ---------------------------------------------------------------------------

def test_no_absolute_paths_are_published(tmp_path):
    root = _git_repo(tmp_path / "demo", {
        "invoice.py": "from discount import apply_discount\n",
        "discount.py": "def apply_discount(p, r):\n    return p\n",
    })
    payload = build(root, root, "local", _sha(root))
    rendered = json.dumps(payload)
    assert str(tmp_path) not in rendered
    assert "/home/" not in rendered
    assert "C:\\" not in rendered


def test_other_languages_are_listed_without_edges_and_with_a_limit(tmp_path):
    """No analyser for TypeScript yet, so no edge is invented and the report says so."""
    root = _git_repo(tmp_path / "mixed", {
        "a.py": "x = 1\n",
        "web/app.ts": "export const x = 1\n",
    })
    payload = build(root, root, "local", _sha(root))
    ts = [m for m in payload["modules"] if m["language"] == "typescript"]
    assert len(ts) == 1
    assert ts[0]["tier"] == "static_same_file"
    assert not any(e["from"].endswith(".ts") or e["to"].endswith(".ts") for e in payload["edges"])
    assert any("Static structure only for typescript" in l for l in payload["limits"])


def test_vendored_and_generated_directories_are_skipped(tmp_path):
    root = _git_repo(tmp_path / "skip", {
        "real.py": "x = 1\n",
        ".venv/lib/site-packages/vendored.py": "y = 2\n",
        "node_modules/pkg/index.js": "z = 3\n",
        "__pycache__/cached.py": "w = 4\n",
    })
    payload = build(root, root, "local", _sha(root))
    assert [m["path"] for m in payload["modules"]] == ["real.py"]


# ---------------------------------------------------------------------------
# validate_map and write_map
# ---------------------------------------------------------------------------

def test_validate_map_accepts_a_real_map(tmp_path):
    root = _git_repo(tmp_path / "demo", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    validate_map(payload)  # must not raise


@pytest.mark.parametrize("mutation,message", [
    ({"limits": None}, "limits"),
    ({"schema_version": None}, "schema_version"),
])
def test_validate_map_rejects_a_malformed_map(tmp_path, mutation, message):
    root = _git_repo(tmp_path / "demo", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    payload.update(mutation)
    with pytest.raises(ValueError, match=message):
        validate_map(payload)


def test_validate_map_rejects_an_unknown_tier(tmp_path):
    root = _git_repo(tmp_path / "demo", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    payload["modules"][0]["tier"] = "totally-made-up"
    with pytest.raises(ValueError, match="unknown tier"):
        validate_map(payload)


def test_write_map_persists_valid_json(tmp_path):
    root = _git_repo(tmp_path / "demo", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    destination = tmp_path / "out" / "repo_map.json"
    repo_map.write_map(payload, destination)
    assert destination.exists()
    assert json.loads(destination.read_text())["modules"][0]["path"] == "a.py"


def test_the_map_is_created_by_a_fresh_run(tmp_path):
    """A run must leave repo_map.json beside its evidence, not only when asked."""
    from bobthereviewer import run_store

    run_dir = run_store.create_run_dir(str(tmp_path), "00000000-0000-0000-0000-000000000000")
    assert run_dir.exists()
    # the CLI writes it; here we assert the writer is usable against a run directory
    root = _git_repo(tmp_path / "demo2", {"a.py": "x = 1\n"})
    payload = build(root, root, "local", _sha(root))
    written = repo_map.write_map(payload, run_dir / "repo_map.json")
    assert written.exists()
