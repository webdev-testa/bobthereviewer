"""
bobthereviewer.cli
~~~~~~~~~~~~~~~~~~
Command-line entry point.  Wires all commands to their owning modules.

Commands:
  init     → bobthereviewer.setup.init        (Lane 1)
  doctor   → bobthereviewer.setup.doctor      (Lane 1)
  analyze  → bobthereviewer.pipeline          (Lane 1)
  run      → bobthereviewer.pipeline          (Lane 1) + executor (Lane 2, pending)
  decide   → bobthereviewer.decide_cmd        (Lane 4, pending)
  ui       → bobthereviewer.server            (Lane 2, pending)

When a lane's module is not yet available, the CLI prints a clear
"pending" message rather than raising an ImportError or crashing.

This module never imports from pending lanes at module level.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Progress printer for CLI
# ---------------------------------------------------------------------------

def _cli_progress(step: str, status: str, message: str) -> None:
    """Print a progress line to stderr."""
    icon = {"started": "…", "completed": "✓", "failed": "✗"}.get(status, " ")
    print(f"  {icon} [{step}] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_evidence_summary(evidence: dict) -> None:
    """Print a human-readable summary of an evidence bundle to stdout."""
    triage = evidence.get("triage", {})
    print(f"\nbobreviewer result")
    print(f"  run_id   : {evidence['run_id']}")
    print(f"  base     : {evidence['base_ref']}  ({evidence['base_commit'][:12]})")
    print(f"  head     : {evidence['head_ref']}  ({evidence['head_commit'][:12]})")
    print(f"  triage   : {triage.get('category', '?')}")

    if triage.get("skipped"):
        print(f"\n  ⚠  Execution skipped: {triage.get('skip_reason', '')}")

    changed = evidence.get("changed_functions", [])
    if not changed:
        print("\n  No changed functions detected.")
    else:
        print(f"\n  Changed functions ({len(changed)}):")
        for cf in changed:
            print(f"    {cf['symbol']}  ({cf['file_path']})")
            callers_outside = [c for c in cf.get("callers", []) if not c["in_diff"]]
            if callers_outside:
                print(f"      Callers outside diff:")
                for c in callers_outside:
                    via = " via " + c["via"][0]["symbol"] if c.get("via") else ""
                    print(f"        {c['symbol']}  {c['file_path']}:{c['line']}{via}")
            unknown = cf.get("unknown_references", [])
            if unknown:
                print(f"      Unknown references: {len(unknown)}")

    probe_results = evidence.get("probe_results", [])
    if probe_results:
        print(f"\n  Probe results:")
        for pr in probe_results:
            for case in pr.get("cases", []):
                status = case.get("comparison_status") or case.get("execution_status", "?")
                print(f"    [{status}] {pr['target']} case={case['id']}")
                if status == "differ":
                    print(f"           before: {case['base_output']}")
                    print(f"           after:  {case['head_output']}")


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    from bobthereviewer.setup import init, detect_config
    from bobthereviewer.snapshots import find_repo_root

    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()
    try:
        repo_root = find_repo_root(repo_dir.resolve())
        config = None
        if not (repo_root / ".bobreviewer/config.json").exists():
            config = detect_config(repo_root)
            print("Detected setup:")
            for key in ("base_branch", "test_dir", "python_env"):
                print(f"  {key}: {config[key]}")
            if sys.stdin.isatty() and not args.yes:
                for key, label in (("base_branch", "Base branch"),
                                   ("test_dir", "Test folder"),
                                   ("python_env", "Python command")):
                    config[key] = input(f"{label} [{config[key]}]: ").strip() or config[key]
        result = init(repo_root, update_gitignore=True, config=config)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"bobreviewer init — {result.config_path}")
    if result.created:
        print("  created:")
        for item in result.created:
            print(f"    + {item}")
    if result.preserved:
        print("  preserved (existing values kept):")
        for item in result.preserved:
            print(f"    = {item}")
    print("Next: bobreviewer run, then bobreviewer ui")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from bobthereviewer.setup import doctor

    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()
    try:
        result = doctor(repo_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("bobreviewer doctor")
    for check in result.checks:
        icon = {"ok": "✓", "missing": "✗", "warning": "⚠"}.get(check.status, "?")
        print(f"  {icon}  {check.name}: {check.detail}")

    if result.all_ok:
        print("\nAll checks passed.")
        return 0
    else:
        missing = [c for c in result.checks if c.status == "missing"]
        if missing:
            print(f"\n{len(missing)} required item(s) missing. See above for details.")
            return 1
        return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from bobthereviewer.pipeline import run_analysis_pipeline, ProbeSpec

    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()
    output_dir = Path(args.output) if args.output else None

    try:
        result = run_analysis_pipeline(
            repo_dir=repo_dir,
            base_ref=args.before,
            head_ref=args.after,
            execute=False,
            output_dir=output_dir,
            callback=_cli_progress,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_evidence_summary(result.evidence)
    if result.output_path:
        print(f"\n  evidence written to: {result.output_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from bobthereviewer.pipeline import run_analysis_pipeline, ProbeSpec
    from bobthereviewer.snapshots import find_repo_root, uncommitted_files, SnapshotError
    from bobthereviewer import run_store
    import shutil

    repo_dir = Path(args.repo_dir) if args.repo_dir else Path.cwd()

    # ---- Dirty working tree check ----
    try:
        repo_root = find_repo_root(repo_dir.resolve())
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        bob_files, other_files = uncommitted_files(repo_root)
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in bob_files:
        print(f"Not included (uncommitted): {path} — commit it to use it", file=sys.stderr)
    if other_files:
        print("Working tree has uncommitted changes; these are not included in the review:",
              file=sys.stderr)
        for path in other_files:
            print(f"  {path}", file=sys.stderr)
        if not sys.stdin.isatty():
            print("error: commit or stash these files before running non-interactively.",
                  file=sys.stderr)
            return 1
        try:
            answer = input("Continue without these changes? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            return 1
        if answer.strip().lower() not in ("y", "yes"):
            return 1

    # ---- Resolve default refs from config ----
    before_ref = args.before
    after_ref = args.after

    if not before_ref or not after_ref:
        config_path = repo_root / ".bobreviewer" / "config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not before_ref:
                before_ref = config.get("base_branch", "main")
            if not after_ref:
                after_ref = "HEAD"
            print(f"  resolved refs: --before {before_ref}  --after {after_ref}", file=sys.stderr)
        else:
            print("error: --before and --after are required when no config.json exists.",
                  file=sys.stderr)
            print("Run 'bobreviewer init' first.", file=sys.stderr)
            return 1

    if args.before is None and args.after is None and sys.stdin.isatty():
        from bobthereviewer.snapshots import _git
        try:
            branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
            answer = input(f"Compare {branch} with {before_ref}? [Y/n/other] ").strip().lower()
            if answer == "other":
                before_ref = input("Compare with ref: ").strip()
                if not before_ref:
                    print("error: a comparison ref is required.", file=sys.stderr)
                    return 1
            elif answer not in ("", "y", "yes"):
                return 1
        except (EOFError, KeyboardInterrupt):
            return 1
        except SnapshotError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    output_dir = Path(args.output) if args.output else None
    probe_files = list(args.probe) if args.probe else []
    prior_report = Path(args.prior_report) if args.prior_report else None

    prior_run_id = None
    if prior_report and prior_report.exists():
        try:
            prior_evidence = json.loads(prior_report.read_text(encoding="utf-8"))
            prior_run_id = prior_evidence.get("run_id")
        except (json.JSONDecodeError, OSError):
            pass

    probe_spec = ProbeSpec(
        probe_files=probe_files,
        prior_run_id=prior_run_id,
        prior_report_path=prior_report,
    )

    run_id = str(uuid.uuid4())
    run_dir = None
    try:
        run_dir = run_store.create_run_dir(str(repo_root), run_id, before_ref, after_ref)
        result = run_analysis_pipeline(
            repo_dir=repo_root,
            base_ref=before_ref,
            head_ref=after_ref,
            probe_spec=probe_spec,
            run_id=run_id,
            execute=True,
            force_run=args.full,
            callback=_cli_progress,
        )
        run_store.save_evidence(run_dir, result.evidence)
        if output_dir is not None and output_dir.resolve() != run_dir.resolve():
            output_dir.mkdir(parents=True, exist_ok=True)
            for name in ("meta.json", "evidence.json", "report.md"):
                shutil.copyfile(run_dir / name, output_dir / name)
        result.output_path = run_dir / "evidence.json"
    except Exception as exc:
        if run_dir is not None:
            run_store.fail_run(run_dir)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_evidence_summary(result.evidence)
    print(f"\n  run saved to: {run_dir}")
    if output_dir is not None:
        print(f"  extra copy: {output_dir}")

    if args.open and result.output_path:
        import webbrowser
        report_html = result.output_path.parent / "report.html"
        if report_html.exists():
            webbrowser.open(report_html.as_uri())
        else:
            print(f"\n  (--open: no report.html found alongside evidence.json)", file=sys.stderr)

    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    """Wire to Lane 4's decide implementation when available."""
    try:
        from bobthereviewer import decide_cmd  # type: ignore[import]
        return decide_cmd.run(args)
    except ImportError:
        print(
            "error: 'decide' requires Lane 4's implementation (bobthereviewer.decide_cmd).\n"
            "This integration is pending. See docs/handoffs/A.md for the required interface.",
            file=sys.stderr,
        )
        return 1


def cmd_ui(args: argparse.Namespace) -> int:
    """Wire to Lane 2's local server when available."""
    try:
        from bobthereviewer import server  # type: ignore[import]
        return server.start(args)
    except ImportError:
        print(
            "error: 'ui' requires Lane 2's local server (bobthereviewer.server).\n"
            "This integration is pending. See docs/handoffs/A.md for the required interface.",
            file=sys.stderr,
        )
        return 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bobreviewer",
        description="Find what a code change actually affects and whether the difference was intentional.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ---- init ----
    p_init = sub.add_parser("init", help="Set up .bobreviewer/ in the repository")
    p_init.add_argument("--repo-dir", metavar="DIR", default=None,
                        help="Repository directory (default: current directory)")
    p_init.add_argument("--yes", action="store_true", help="Accept detected defaults without prompting")

    # ---- doctor ----
    p_doc = sub.add_parser("doctor", help="Check readiness without installing or running anything")
    p_doc.add_argument("--repo-dir", metavar="DIR", default=None)

    # ---- analyze ----
    p_ana = sub.add_parser("analyze", help="Analysis only — no test or probe execution")
    p_ana.add_argument("--before", required=True, metavar="REF")
    p_ana.add_argument("--after", required=True, metavar="REF")
    p_ana.add_argument("--output", metavar="DIR", default=None,
                       help="Directory to write evidence.json")
    p_ana.add_argument("--repo-dir", metavar="DIR", default=None)

    # ---- run ----
    p_run = sub.add_parser("run", help="Full analysis and execution")
    p_run.add_argument("--before", metavar="REF", default=None)
    p_run.add_argument("--after", metavar="REF", default=None)
    p_run.add_argument("--probe", metavar="FILE", action="append", default=None,
                       help="Repo-relative path to a committed probe file (may repeat)")
    p_run.add_argument("--prior-report", metavar="FILE", default=None,
                       help="Path to an earlier evidence.json for fix-loop linking")
    p_run.add_argument("--full", action="store_true",
                       help="Force execution even for docs-only diffs")
    p_run.add_argument("--open", action="store_true",
                       help="Open the result in a browser after the run")
    p_run.add_argument("--output", metavar="DIR", default=None)
    p_run.add_argument("--repo-dir", metavar="DIR", default=None)

    # ---- decide ----
    p_dec = sub.add_parser("decide", help="Record a decision for a probe case result")
    p_dec.add_argument("--run-id", required=True, metavar="ID")
    p_dec.add_argument("--symbol", required=True, metavar="SYMBOL")
    p_dec.add_argument("--case-id", required=True, metavar="ID")
    p_dec.add_argument("--verdict", required=True,
                       choices=["intended", "unintended", "unresolved"])
    p_dec.add_argument("--rationale", required=True, metavar="TEXT")
    p_dec.add_argument("--repo-dir", metavar="DIR", default=None)

    # ---- ui ----
    p_ui = sub.add_parser("ui", help="Start the local developer UI server")
    p_ui.add_argument("--port", type=int, default=7842, metavar="PORT")
    p_ui.add_argument("--repo-dir", metavar="DIR", default=None)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    dispatch = {
        "init":    cmd_init,
        "doctor":  cmd_doctor,
        "analyze": cmd_analyze,
        "run":     cmd_run,
        "decide":  cmd_decide,
        "ui":      cmd_ui,
    }

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
