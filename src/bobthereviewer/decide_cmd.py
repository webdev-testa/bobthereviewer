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


def run(args: argparse.Namespace) -> int:
    """Execute the 'decide' command."""
    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()

    try:
        repo_root = find_repo_root(repo_dir.resolve())
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    evidence_file = _find_evidence_json(repo_root, args.run_id, repo_dir)
    if not evidence_file:
        print(
            f"error: evidence.json not found for run_id '{args.run_id}'.",
            file=sys.stderr,
        )
        return 1

    try:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"error reading evidence bundle: {exc}", file=sys.stderr)
        return 1

    # Find matching probe_file from probe_results if possible
    probe_file = ""
    for p in evidence.get("probe_results", []):
        for c in p.get("cases", []):
            if c.get("id") == args.case_id:
                probe_file = p.get("probe_file", "")
                break
        if probe_file:
            break

    try:
        decision_data = validate_and_build_decision(
            run_id=args.run_id,
            symbol=args.symbol,
            probe_file=probe_file,
            case_id=args.case_id,
            verdict=args.verdict,
            rationale=args.rationale,
            evidence=evidence,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    decisions_dir = repo_root / ".bobreviewer" / "decisions"
    try:
        written_path, git_cmd = validate_and_save(decision_data, decisions_dir)
    except Exception as exc:
        print(f"error: failed to write decision: {exc}", file=sys.stderr)
        return 1

    # Print results to stdout
    rel_path = written_path
    try:
        rel_path = written_path.relative_to(repo_root)
    except ValueError:
        pass
    print(f"Decision written to: {rel_path}")
    print("To record this decision, run:")
    print(f"  {git_cmd}")

    return 0
