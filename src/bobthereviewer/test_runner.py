"""
bobthereviewer.test_runner
=======================
Runs the frozen base test suite against both worktrees.

"Frozen" means: the set of test files present in the BASE worktree, run
with the base pytest config.  New test files added on the head branch do
NOT run in the frozen suite.

Uses pytest's built-in ``--junitxml`` for structured output, requiring only
pytest (no pytest-json-report plugin needed).

Returns the ``test_results`` dict shape expected by ``evidence.schema.json``
and a ``frozen_suite_hash`` hex string (SHA-256 of sorted file contents).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Optional


_DEFAULT_TIMEOUT = 120  # seconds for the full test suite


def _sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compute_frozen_suite_hash(test_files: list[tuple[str, bytes]]) -> str:
    """
    SHA-256 of the sorted list of (relative_path, file_bytes) pairs.
    Sorting ensures stability regardless of filesystem order.
    """
    h = hashlib.sha256()
    for rel_path, content in sorted(test_files):
        h.update(rel_path.encode())
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    return h.hexdigest()


def _discover_test_files(worktree_path: str) -> list[tuple[str, bytes]]:
    """
    Return sorted list of (repo-relative path, bytes) for all Python test
    files found in the worktree using pytest discovery conventions:
    ``test_*.py`` and ``*_test.py`` under any subdirectory.
    """
    root = Path(worktree_path)
    files: list[tuple[str, bytes]] = []
    for p in sorted(root.rglob("test_*.py")) + sorted(root.rglob("*_test.py")):
        rel = p.relative_to(root).as_posix()
        files.append((rel, p.read_bytes()))
    # Deduplicate (rglob patterns may overlap)
    seen: set[str] = set()
    unique: list[tuple[str, bytes]] = []
    for rel, data in files:
        if rel not in seen:
            seen.add(rel)
            unique.append((rel, data))
    return sorted(unique)


def _clean_paths(text: str, paths: list[str | Path]) -> str:
    for p in paths:
        if not p:
            continue
        try:
            resolved = Path(p).resolve()
            text = text.replace(str(resolved), ".").replace(resolved.as_posix(), ".")
        except Exception:
            pass
        text = text.replace(str(p), ".")
    return text.strip()


def _display_interpreter(python_exe: str, worktree_path: str = "") -> str:
    exe_p = Path(python_exe).resolve()
    for root_cand in [Path(worktree_path).resolve() if worktree_path else None, Path.cwd().resolve()]:
        if root_cand:
            try:
                rel = exe_p.relative_to(root_cand)
                return str(rel)
            except (ValueError, RuntimeError):
                pass
    parts = exe_p.parts
    for venv_name in (".venv", "venv"):
        if venv_name in parts:
            idx = parts.index(venv_name)
            return str(Path(*parts[idx:]))
    return exe_p.name


def parse_junit_xml(
    xml_content: str,
    worktree_path: str = "",
    test_files: list[str] | None = None,
) -> dict[str, dict]:
    """Parse pytest JUnit XML into {node_id: {"status": status, "message": message}}.

    Statuses: "pass" | "fail" | "error".
    Skipped tests map to "error" with message "skipped: <reason>".
    """
    if not xml_content.strip():
        return {}

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return {}

    results: dict[str, dict] = {}
    known_files = [f.replace("\\", "/") for f in (test_files or [])]
    clean_targets: list[str | Path] = [worktree_path] if worktree_path else []

    mod_to_file: dict[str, str] = {}
    for f in known_files:
        p = Path(f)
        parts = list(p.parts)
        if parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        mod_name = ".".join(parts)
        mod_to_file[mod_name] = f
        mod_to_file[p.stem] = f

    for tc in root.iter("testcase"):
        name = tc.attrib.get("name", "")
        classname = tc.attrib.get("classname", "")
        file_attr = tc.attrib.get("file", "")

        fail_elem = tc.find("failure")
        err_elem = tc.find("error")
        skip_elem = tc.find("skipped")

        if fail_elem is not None:
            status = "fail"
            text_detail = (fail_elem.text or "").strip()
            attr_msg = fail_elem.attrib.get("message") or ""
            msg = f"{attr_msg}\n{text_detail}".strip() if attr_msg and text_detail else (attr_msg or text_detail or "test failed")
        elif err_elem is not None:
            status = "error"
            text_detail = (err_elem.text or "").strip()
            attr_msg = err_elem.attrib.get("message") or ""
            msg = f"{attr_msg}\n{text_detail}".strip() if attr_msg and text_detail else (attr_msg or text_detail or "test error")
        elif skip_elem is not None:
            status = "error"
            text_detail = (skip_elem.text or "").strip()
            raw_msg = skip_elem.attrib.get("message") or text_detail or "skipped"
            msg = f"skipped: {raw_msg}" if not str(raw_msg).startswith("skipped") else str(raw_msg)
        else:
            status = "pass"
            msg = None

        if msg is not None:
            msg = _clean_paths(msg, clean_targets)

        # Check for collection failure
        is_collection_err = (
            err_elem is not None
            and (
                err_elem.attrib.get("message") == "collection failure"
                or not classname
                or (file_attr and name == Path(file_attr).stem)
                or name in [Path(f).stem for f in known_files]
            )
        )
        if is_collection_err:
            results["<collection>"] = {"status": "error", "message": msg}
            continue

        # File path resolution
        if file_attr:
            file_path = file_attr.replace("\\", "/")
        else:
            file_path = ""
            for mod, fpath in mod_to_file.items():
                if classname == mod or classname.startswith(mod + "."):
                    file_path = fpath
                    break
            if not file_path:
                parts = classname.split(".")
                file_path = "/".join(parts) + ".py"

        # Class part resolution
        class_part = ""
        for mod in mod_to_file:
            if classname.startswith(mod + "."):
                class_part = classname[len(mod) + 1:]
                break
        if not class_part and "." in classname and not file_attr:
            parts = classname.split(".")
            if len(parts) > 1 and parts[-1] and parts[-1][0].isupper():
                class_part = parts[-1]

        if class_part:
            node_id = f"{file_path}::{class_part}::{name}"
        elif name:
            node_id = f"{file_path}::{name}"
        else:
            node_id = file_path or "unknown"

        results[node_id] = {"status": status, "message": msg}

    return results


def _run_pytest(
    worktree_path: str,
    python_exe: str,
    test_files: list[str],
    timeout_seconds: int,
    src_layout: bool = False,
) -> dict[str, dict]:
    """
    Run pytest on the given list of test file paths (relative to worktree_path).
    Returns ``{node_id: {"status": "pass"|"fail"|"error", "message": null|str}}``.
    """
    if not test_files:
        return {}

    root = Path(worktree_path)
    report_path = ""

    def diagnostic(text: str) -> str:
        clean_targets: list[str | Path] = [root.resolve(), Path(python_exe).resolve()]
        if report_path:
            clean_targets.append(Path(report_path).resolve())
        return _clean_paths(text, clean_targets)

    # Check if pytest is available in python_exe
    try:
        check = subprocess.run(
            [python_exe, "-m", "pytest", "--version"],
            capture_output=True,
            timeout=10,
        )
        if check.returncode != 0:
            rel_py = _display_interpreter(python_exe, worktree_path)
            return {
                "<pytest>": {
                    "status": "error",
                    "message": f"pytest is not installed in {rel_py}",
                }
            }
    except Exception as exc:
        # Never interpolate the raw exception: FileNotFoundError embeds the absolute
        # interpreter path, and published evidence must carry repo-relative paths only. Report
        # the exception type, which is the part that helps, and let `doctor` show the path.
        # An interpreter that cannot be launched is also an interpreter that cannot provide
        # pytest, so the wording stays accurate to what was observed.
        rel_py = _display_interpreter(python_exe, worktree_path)
        return {
            "<pytest>": {
                "status": "error",
                "message": (
                    f"pytest is not installed in {rel_py} or cannot be run "
                    f"({type(exc).__name__})"
                ),
            }
        }

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tf:
        report_path = tf.name

    cmd = [
        python_exe, "-m", "pytest",
        "--tb=short",
        "--no-header",
        "-q",
        "-o", "junit_family=legacy",
        f"--junitxml={report_path}",
    ]
    if src_layout:
        cmd.extend(["-o", "pythonpath=src"])
    cmd.extend(test_files)

    try:
        completed = subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        if report_path:
            Path(report_path).unlink(missing_ok=True)
        return {"<suite timeout>": {"status": "error", "message": "test suite timed out"}}

    results: dict[str, dict] = {}
    try:
        xml_content = Path(report_path).read_text(encoding="utf-8")
        results = parse_junit_xml(xml_content, worktree_path, test_files)
    except Exception:
        message = diagnostic((completed.stdout + completed.stderr).decode("utf-8", errors="replace"))
        return {"<parse error>": {"status": "error", "message": message or "could not parse pytest report"}}
    finally:
        if report_path:
            try:
                Path(report_path).unlink(missing_ok=True)
            except OSError:
                pass

    if not results or completed.returncode not in (0, 1):
        if "<collection>" not in results:
            message = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").strip()
            results["<collection>"] = {
                "status": "error",
                "message": diagnostic(message) or "No tests collected from the frozen test files.",
            }

    return results


def _step_summary(side: str, results: dict) -> tuple[str, str]:
    """Progress status and message for one side's test run.

    Entries named ``<...>`` (``<pytest>``, ``<collection>``, ``<suite timeout>``, ``<parse error>``)
    record why tests could not run; they are not tests. Counting them as tests printed a green
    "1 test(s)" for a run where nothing ran.
    """
    real = {k: v for k, v in results.items() if not k.startswith("<")}
    problems = [v.get("message") or k for k, v in results.items() if k.startswith("<")]
    if problems and not real:
        return "failed", f"{side}: tests did not run — {problems[0]}"
    counts = {s: sum(1 for v in real.values() if v.get("status") == s) for s in ("pass", "fail", "error")}
    message = f"{side}: {len(real)} test(s) — {counts['pass']} passed, {counts['fail']} failed, {counts['error']} error(s)"
    if problems:
        return "failed", f"{message}; {problems[0]}"
    return "completed", message


def run_tests(
    base_worktree_path: str,
    head_worktree_path: str,
    python_exe: str,
    triage: dict,
    emit: Callable[[str, str, str], None],
    timeout_seconds: int = _DEFAULT_TIMEOUT,
    src_layout: bool = False,
) -> tuple[dict, Optional[str]]:
    """
    Run the frozen test suite against both worktrees.

    Returns ``(test_results_dict, frozen_suite_hash_hex)``.

    ``test_results_dict`` matches ``evidence.schema.json``::

        {
          "base": {<node_id>: {"status": "pass"|"fail"|"error", "message": ...}},
          "head": {<node_id>: {"status": "pass"|"fail"|"error", "message": ...}},
        }

    ``frozen_suite_hash_hex`` is ``None`` when triage skipped execution.
    """
    if triage.get("skipped", False):
        skip_reason = triage.get("skip_reason") or "docs-only diff"
        emit("test_base", "completed", f"skipped — {skip_reason}")
        emit("test_head", "completed", f"skipped — {skip_reason}")
        return {"base": {}, "head": {}}, None

    # Discover frozen test files from the BASE worktree
    base_test_files = _discover_test_files(base_worktree_path)
    frozen_rel_paths = [rel for rel, _ in base_test_files]
    frozen_suite_hash = _compute_frozen_suite_hash(base_test_files)

    # Run on base
    emit("test_base", "started", f"Running {len(frozen_rel_paths)} frozen test file(s) on base")
    base_results = _run_pytest(base_worktree_path, python_exe, frozen_rel_paths, timeout_seconds, src_layout)
    emit("test_base", *_step_summary("base", base_results))

    # Run same frozen file list on head
    emit("test_head", "started", f"Running {len(frozen_rel_paths)} frozen test file(s) on head")
    head_results = _run_pytest(head_worktree_path, python_exe, frozen_rel_paths, timeout_seconds, src_layout)
    emit("test_head", *_step_summary("head", head_results))

    return {"base": base_results, "head": head_results}, frozen_suite_hash
