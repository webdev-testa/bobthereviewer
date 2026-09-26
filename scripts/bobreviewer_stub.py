"""
scripts/bobreviewer_stub.py — Development stub for Lane 4.

Accepts --before REF --after REF and prints a hardcoded fixture evidence.json
to stdout. Used to unblock Bob workflow development before Lane 1's CLI is ready.

Usage:
    python scripts/bobreviewer_stub.py --before demo-base --after demo-rounding-change

Replace with the real CLI call once Lane 1 delivers bobreviewer run.
"""
import argparse
import json
import pathlib
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="bobthereviewer stub (development only)")
    parser.add_argument("subcommand", nargs="?", default="run",
                        help="Subcommand: run or analyze")
    parser.add_argument("--before", required=True, help="Base Git ref")
    parser.add_argument("--after", required=True, help="Head Git ref")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--probe", action="append", dest="probes", default=[],
                        help="Path to a probe file (repeatable)")
    parser.add_argument("--prior-report", default=None,
                        help="Path to a prior evidence.json for run linking")
    args = parser.parse_args()

    fixture_path = pathlib.Path(__file__).parent.parent / "fixtures" / "evidence.fixture.json"
    if not fixture_path.exists():
        print(f"ERROR: fixture not found at {fixture_path}", file=sys.stderr)
        sys.exit(1)

    evidence = json.loads(fixture_path.read_text(encoding="utf-8"))

    # Patch the refs so the output reflects what was requested
    evidence["base_ref"] = args.before
    evidence["head_ref"] = args.after

    # Write to output dir (mirrors what the real CLI does)
    output_dir = pathlib.Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    # Also print to stdout so Bob can capture it directly
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
