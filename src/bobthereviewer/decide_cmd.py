"""bobthereviewer.decide_cmd — implementation of 'bobreviewer decide' CLI command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from bobthereviewer.decisions import validate_and_save, validate_and_build_decision
from bobthereviewer.snapshots import find_repo_root, SnapshotError


def _find_evidence_json(repo_root: Path, run_id: str, repo_dir: Path) -> Path | None:
    """Find evidence.json matching run_id in standard locations."""
    # 1. Check .bobreviewer/runs/<run_id>/evidence.json
    p = repo_root / ".bobreviewer" / "runs" / run_id / "evidence.json"
    if p.exists():
        return p

    # 2. Check output/evidence.json and direct files
    for out_candidate in [
        repo_root / "output" / "evidence.json",
        repo_dir / "output" / "evidence.json",
        repo_dir / "evidence.json",
    ]:
        if out_candidate.exists():
            try:
                data = json.loads(out_candidate.read_text(encoding="utf-8"))
                if data.get("run_id") == run_id:
                    return out_candidate
            except Exception:
                pass

    # 3. Search all runs under .bobreviewer/runs/
    runs_dir = repo_root / ".bobreviewer" / "runs"
    if runs_dir.exists():
        for run_dir in runs_dir.iterdir():
            if run_dir.is_dir():
                ev = run_dir / "evidence.json"
                if ev.exists():
                    try:
                        data = json.loads(ev.read_text(encoding="utf-8"))
                        if data.get("run_id") == run_id:
                            return ev
                    except Exception:
                        pass

    return None


class DecideError(Exception):
    """A decision that can't be recorded; ``status`` is the matching HTTP code."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def decide_from_run(
    repo_root: Path,
    run_id: str,
    symbol: str,
    case_id: str,
    verdict: str,
    rationale: str,
    repo_dir: Path | None = None,
) -> tuple[Path, str]:
    """Write a proposed decision for one probe case of a saved run.

    Shared by ``bobreviewer decide`` and the web UI's Save decision, so both
    validate and write identically. Returns the repo-relative file path and
    the git command to record it; never runs git itself.
    """
    evidence_file = _find_evidence_json(repo_root, run_id, repo_dir or repo_root)
    if not evidence_file:
        raise DecideError(f"evidence.json not found for run_id '{run_id}'.", 404)
    try:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DecideError(f"error reading evidence bundle: {exc}", 422) from exc

    probes = evidence.get("probe_results", [])
    has_case = lambda p: any(c.get("id") == case_id for c in p.get("cases", []))  # noqa: E731
    probe = next((p for p in probes if p.get("target") == symbol and has_case(p)), None)
    probe = probe or next((p for p in probes if has_case(p)), {})

    try:
        decision_data = validate_and_build_decision(
            run_id=run_id,
            symbol=symbol,
            probe_file=probe.get("probe_file", ""),
            case_id=case_id,
            verdict=verdict,
            rationale=rationale,
            evidence=evidence,
        )
        written_path, git_cmd = validate_and_save(decision_data, repo_root / ".bobreviewer" / "decisions")
    except ValueError as exc:
        raise DecideError(str(exc), 422) from exc
    except OSError as exc:
        raise DecideError(f"failed to write decision: {exc}", 500) from exc

    rel_path = written_path.relative_to(repo_root)
    git_cmd = git_cmd.replace(str(written_path).replace("\\", "/"), rel_path.as_posix())
    return rel_path, git_cmd


def run(args: argparse.Namespace) -> int:
    """Execute the 'decide' command."""
    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()

    try:
        repo_root = find_repo_root(repo_dir.resolve())
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        rel_path, git_cmd = decide_from_run(
            repo_root, args.run_id, args.symbol, args.case_id, args.verdict, args.rationale, repo_dir,
        )
    except DecideError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Decision written to: {rel_path}")
    print("To record this decision, run:")
    print(f"  {git_cmd}")

    return 0
