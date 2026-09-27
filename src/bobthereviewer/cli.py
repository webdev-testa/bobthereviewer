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
import subprocess
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory


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
    languages = evidence.get("analysis_limits", {}).get("languages")
    from bobthereviewer.adapters import format_analyzed_as
    print(f"  Analyzed as: {format_analyzed_as(languages)}")

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
        install_bob = True
        install_action = True

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
                ans_bob = input("Install Bob mode [Y/n]: ").strip().lower()
                install_bob = ans_bob in ("", "y", "yes")
                ans_act = input("Install GitHub Action [Y/n]: ").strip().lower()
                install_action = ans_act in ("", "y", "yes")
        result = init(
            repo_root,
            update_gitignore=True,
            config=config,
            install_bob_mode=install_bob,
            install_github_action=install_action,
        )
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
    snippet_file = repo_root / ".bobreviewer" / "bob-mode.yaml"
    if snippet_file.exists():
        bob_modes = repo_root / ".bob" / "custom_modes.yaml"
        if bob_modes.exists() and "slug: behavior-review" not in bob_modes.read_text(encoding="utf-8"):
            print("  note: paste .bobreviewer/bob-mode.yaml into .bob/custom_modes.yaml")
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

        # The repository map describes where this change sits in the whole project, so it is
        # stored beside the run. A map that cannot be built is noted, not fatal: the review
        # itself is still valid evidence.
        try:
            from bobthereviewer import repo_map as repo_map_module
            repo_map_module.save_for_run(repo_root, result.evidence, run_dir)
        except Exception as exc:  # noqa: BLE001 - a missing map must not void the review
            print(f"  note: repository map not written ({type(exc).__name__}: {exc})", file=sys.stderr)

        if output_dir is not None and output_dir.resolve() != run_dir.resolve():
            output_dir.mkdir(parents=True, exist_ok=True)
            for name in ("meta.json", "evidence.json", "report.md", "repo_map.json"):
                source = run_dir / name
                if source.exists():
                    shutil.copyfile(source, output_dir / name)
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

    if args.open:
        # Stay in the foreground as the UI server (Ctrl+C stops it), like running `bobreviewer ui`.
        from bobthereviewer import server
        return server.start(argparse.Namespace(repo_dir=str(repo_root), port=7842, run_id=run_id))

    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Write the whole-repository module map for one revision.

    Generated by code from the source tree and git history; nothing here is model-produced.
    """
    from bobthereviewer import repo_map as repo_map_module
    from bobthereviewer.snapshots import SnapshotError, find_repo_root
    import subprocess

    try:
        repo_root = find_repo_root(Path(args.repo_dir).resolve() if args.repo_dir else Path.cwd())
    except SnapshotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    ref = args.ref or "HEAD"
    try:
        resolved = subprocess.run(
            ["git", "rev-parse", ref], cwd=repo_root, capture_output=True, text=True,
        )
    except OSError as exc:
        print(f"error: cannot run git: {exc}", file=sys.stderr)
        return 1
    if resolved.returncode != 0:
        print(f"error: cannot resolve ref '{ref}'", file=sys.stderr)
        return 1
    sha = resolved.stdout.strip()

    # Read sources from the revision itself, not the working tree, so the map matches the SHA.
    with TemporaryDirectory(prefix="bobreviewer-map-") as tmp:
        checkout = Path(tmp) / "tree"
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", "-q", str(checkout), sha],
            cwd=repo_root, capture_output=True, text=True,
        )
        if added.returncode != 0:
            print(f"error: cannot check out {sha[:7]}: {added.stderr.strip()}", file=sys.stderr)
            return 1
        try:
            remote = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=repo_root, capture_output=True, text=True,
            ).stdout.strip() or "local"
            payload = repo_map_module.build(checkout, repo_root, remote, sha)
            repo_map_module.validate_map(payload)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(checkout)],
                           cwd=repo_root, capture_output=True, text=True)

    destination = Path(args.out) if args.out else repo_root / "repo_map.json"
    repo_map_module.write_map(payload, destination)

    print(f"repository map for {sha[:7]}")
    print(f"  modules : {len(payload['modules'])}")
    print(f"  edges   : {len(payload['edges'])}")
    print(f"  unknowns: {len(payload['unknowns'])}")
    print(f"  written to: {destination}")
    for limit in payload["limits"]:
        print(f"  limit: {limit}")
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
                       help="Show this run in the local web UI afterwards (serves until Ctrl+C)")
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

    # ---- map ----
    p_map = sub.add_parser("map", help="Write the whole-repository module map for one revision")
    p_map.add_argument("--ref", metavar="REF", default=None,
                       help="Revision to map (default: HEAD)")
    p_map.add_argument("--out", metavar="FILE", default=None,
                       help="Where to write repo_map.json (default: <repo>/repo_map.json)")
    p_map.add_argument("--repo-dir", metavar="DIR", default=None)

    # ---- ui ----
    p_ui = sub.add_parser("ui", help="Start the local developer UI server")
    p_ui.add_argument("--port", type=int, default=7842, metavar="PORT")
    p_ui.add_argument("--repo-dir", metavar="DIR", default=None)
    p_ui.add_argument("--no-browser", action="store_true",
                      help="Only print the URL; don't open a browser")

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
        "map":     cmd_map,
        "ui":      cmd_ui,
    }

    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
