"""
bobthereviewer.triage
~~~~~~~~~~~~~~~~~~~~~
Deterministic diff classification into one of five categories.

Rules (conservative — when in doubt, classify as code):

  docs-only
    Every changed file is a documentation file (.md, .rst, .txt).
    No Python files may be present in the diff.
    Unknown file types or parse failures count as code.

  tests-only
    Every changed Python file is under a test directory (test_*.py,
    *_test.py, or any file under a directory named tests/, test/).
    No production Python files changed.

  config-deps
    Changed files are package manifests, lock files, CI config, or
    environment files (pyproject.toml, setup.cfg, setup.py,
    requirements*.txt, *.lock, tox.ini, .env*, .github/**,
    Dockerfile, docker-compose*, Makefile).

  no-semantic-change
    Every changed Python file parses successfully in both revisions
    and the ASTs are structurally identical (ignoring source-location
    attributes).  Non-Python production files must not be present.

  code
    Anything else, including:
    - any Python file whose AST differs between revisions
    - any unknown file type
    - any file that fails to parse
    - newly added probe files
    - a mix of docs and non-docs changes

  Skip rule:
    Only docs-only may skip execution.  --full overrides the skip.
    A skipped run must report what was skipped and why.

Ownership: Lane 1.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from bobthereviewer.analysis import _ast_equal, _parse_safe


# ---------------------------------------------------------------------------
# Known extension sets
# ---------------------------------------------------------------------------

_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc", ".asciidoc"}

_CONFIG_PATTERNS = [
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^setup\.(cfg|py)$"),
    re.compile(r"^requirements.*\.txt$"),
    re.compile(r".*\.lock$"),
    re.compile(r"^tox\.ini$"),
    re.compile(r"^\.env.*"),
    re.compile(r"^\.github/"),
    re.compile(r"^Dockerfile$"),
    re.compile(r"^docker-compose.*"),
    re.compile(r"^Makefile$"),
    re.compile(r"^\.travis\.yml$"),
    re.compile(r"^\.circleci/"),
    re.compile(r"^Pipfile(\.lock)?$"),
    re.compile(r"^MANIFEST\.in$"),
]

_TEST_PATTERNS = [
    re.compile(r"(^|/)tests?/"),
    re.compile(r"test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r"conftest\.py$"),
]


# ---------------------------------------------------------------------------
# Public result
# ---------------------------------------------------------------------------

@dataclass
class TriageResult:
    category: str     # one of the five category strings
    skipped: bool     # True only if execution was actually skipped
    skip_reason: str | None


# ---------------------------------------------------------------------------
# Internal classifiers
# ---------------------------------------------------------------------------

def _is_doc_file(path: str) -> bool:
    return Path(path).suffix.lower() in _DOC_EXTENSIONS


def _is_config_file(path: str) -> bool:
    basename = Path(path).name
    full = path.replace("\\", "/")
    for pattern in _CONFIG_PATTERNS:
        if pattern.match(basename) or pattern.match(full):
            return True
    return False


def _is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in _TEST_PATTERNS:
        if pattern.search(normalized):
            return True
    return False


def _is_python_file(path: str) -> bool:
    return path.endswith(".py")


# ---------------------------------------------------------------------------
# AST comparison across worktrees
# ---------------------------------------------------------------------------

def _python_ast_unchanged(rel_path: str, base_path: Path, head_path: Path) -> bool:
    """Return True iff the Python file at rel_path has structurally identical
    ASTs in both revisions.  Returns False on parse failure, missing file,
    or any structural difference."""
    base_file = base_path / rel_path
    head_file = head_path / rel_path

    if not base_file.exists() or not head_file.exists():
        return False  # new or deleted file → treat as changed

    try:
        base_src = base_file.read_text(encoding="utf-8", errors="replace")
        head_src = head_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    base_tree = _parse_safe(base_src, rel_path)
    head_tree = _parse_safe(head_src, rel_path)

    if base_tree is None or head_tree is None:
        return False  # parse failure → conservative: treat as changed

    return _ast_equal(base_tree, head_tree)


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

def classify(
    changed_files: list[str],
    base_path: Path,
    head_path: Path,
    force_run: bool = False,
) -> TriageResult:
    """Classify a set of changed files into a triage category.

    Parameters
    ----------
    changed_files:
        Repo-relative paths of files that differ between revisions.
    base_path:
        Absolute path to the base worktree (for AST comparison).
    head_path:
        Absolute path to the head worktree.
    force_run:
        When True (--full flag), never skip execution.

    Returns
    -------
    TriageResult
        category: one of five enum values
        skipped: whether execution would be skipped for this category
        skip_reason: human-readable string when skipped, else None
    """
    if not changed_files:
        # No changed files at all — treat as no-semantic-change
        return TriageResult(
            category="no-semantic-change",
            skipped=False,
            skip_reason=None,
        )

    py_files     = [f for f in changed_files if _is_python_file(f)]
    non_py_files = [f for f in changed_files if not _is_python_file(f)]
    doc_files    = [f for f in changed_files if _is_doc_file(f)]
    cfg_files    = [f for f in non_py_files  if _is_config_file(f)]

    # -----------------------------------------------------------------------
    # config-deps: all changed files are known config/dependency files
    # (checked before docs-only so requirements.txt doesn't mis-classify)
    # -----------------------------------------------------------------------
    if not py_files and cfg_files and len(cfg_files) == len(changed_files):
        return TriageResult(category="config-deps", skipped=False, skip_reason=None)

    # -----------------------------------------------------------------------
    # docs-only: ONLY .md/.rst/.txt — no Python, no config, no unknown files
    # -----------------------------------------------------------------------
    if not py_files and doc_files and len(doc_files) == len(changed_files):
        if force_run:
            return TriageResult(category="docs-only", skipped=False, skip_reason=None)
        return TriageResult(
            category="docs-only",
            skipped=True,
            skip_reason="All changed files are documentation; execution skipped. Use --full to override.",
        )

    # -----------------------------------------------------------------------
    # tests-only: all changed Python files are test files, no non-test Python
    # -----------------------------------------------------------------------
    if py_files and all(_is_test_file(f) for f in py_files):
        non_test_non_py = [f for f in non_py_files if not _is_config_file(f) and not _is_doc_file(f)]
        if not non_test_non_py:
            return TriageResult(category="tests-only", skipped=False, skip_reason=None)

    # -----------------------------------------------------------------------
    # no-semantic-change: all Python files parse successfully and ASTs match
    # -----------------------------------------------------------------------
    if py_files:
        all_unchanged = all(
            _python_ast_unchanged(f, base_path, head_path)
            for f in py_files
        )
        # Also check non-py files — if there are unknown non-py non-doc non-cfg files,
        # we can't claim no-semantic-change safely
        unknown_non_py = [
            f for f in non_py_files
            if not _is_doc_file(f) and not _is_config_file(f)
        ]
        if all_unchanged and not unknown_non_py:
            return TriageResult(category="no-semantic-change", skipped=False, skip_reason=None)

    # -----------------------------------------------------------------------
    # code: everything else
    # -----------------------------------------------------------------------
    return TriageResult(category="code", skipped=False, skip_reason=None)
