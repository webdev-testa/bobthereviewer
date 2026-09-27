#!/usr/bin/env python3
"""Build the standalone demo repository used by every demo Act.

The demo used to live inside the tool repo, so a review of `demo/sample_project` also read
hundreds of the tool's own functions and the demo probe was never found. This builds a small
standalone git repo where each demo Act has a fixed tag, so the scenario tests and the demo
video both resolve the same commits from anywhere.

Usage:
    python scripts/make_demo_repo.py <out-dir> [--for-video]

Modes:
    default      copies this repo's `.bob/` and ignores `.bobreviewer/runs/`, so the acceptance
                 checks work before `bobreviewer init` is interactive.
    --for-video  a clean repo with no `.bob/`, so the video can show install + init from zero.

The tags are the answer key for each Act. `main` stays at `demo-base`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "demo" / "sample_project"

DEMO_BASE_DISCOUNT = '''"""discount.py — sample project module (demo-base version).

apply_discount rounds to 2 decimal places.
"""


def apply_discount(price: float, discount_rate: float) -> float:
    """Return price after applying discount_rate (0.0 - 1.0), rounded to 2 d.p."""
    return round(price * (1 - discount_rate), 2)
'''

DEMO_ROUNDING_DISCOUNT = '''"""discount.py — sample project module (demo-rounding-change version).

Changed: apply_discount now truncates to 2 decimal places using floor instead of rounding.
A subtle behavioural difference that passes every existing test (they only cover 0% and 50%
discounts) but changes the result for small discount rates.

  demo-base:            round(99.999..., 2)      = 100.0
  demo-rounding-change: floor(99.999...*100)/100 = 99.99
"""

import math


def apply_discount(price: float, discount_rate: float) -> float:
    """Return price after applying discount_rate (0.0 - 1.0), truncated to 2 d.p."""
    return math.floor(price * (1 - discount_rate) * 100) / 100
'''

# Act 3: a different body that returns exactly the same values as demo-base, so the frozen
# observations match while the structure changed.
DEMO_REFACTOR_DISCOUNT = '''"""discount.py — sample project module (demo-refactor version).

Structurally different from demo-base, behaviourally identical: the discount factor is
computed in a helper instead of inline. Frozen observations must match demo-base.
"""


def _factor(discount_rate: float) -> float:
    """Return the multiplier for a discount rate."""
    return 1 - discount_rate


def apply_discount(price: float, discount_rate: float) -> float:
    """Return price after applying discount_rate (0.0 - 1.0), rounded to 2 d.p."""
    return round(price * _factor(discount_rate), 2)
'''

TAX_TABLES = '''"""tax_tables.py — added by the demo-broken-import Act.

The base revision cannot import this module, so a probe targeting it must come out
`inconclusive` with reason `import_error` rather than a pass or a fail.
"""

RATES = {"ID": 0.11, "SG": 0.09}


def rate_for(region: str) -> float:
    """Return the tax rate for a region."""
    return RATES[region]
'''

PROBE_INVOICE = """{
  "schema_version": "1",
  "target": "invoice.calculate_invoice",
  "cases": [
    {
      "id": "invoice-small-discount",
      "args": [105.26, 0.05],
      "kwargs": {}
    }
  ]
}
"""

PROBE_PRICING = """{
  "schema_version": "1",
  "target": "pricing.calculate_price",
  "cases": [
    {
      "id": "price-100",
      "args": [100.0],
      "kwargs": {}
    }
  ]
}
"""

PROBE_TAX_TABLES = """{
  "schema_version": "1",
  "target": "tax_tables.rate_for",
  "cases": [
    {
      "id": "rate-id",
      "args": ["ID"],
      "kwargs": {}
    }
  ]
}
"""


def run(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"command failed: {' '.join(args)}\n{result.stdout}{result.stderr}")


def write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def commit(root: Path, message: str) -> None:
    run(["git", "add", "-A"], root)
    run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message], root)


def tag(root: Path, name: str, message: str) -> None:
    run(["git", "tag", "-a", name, "-m", message], root)


def set_discount(root: Path, content: str) -> None:
    write(root, "discount.py", content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the standalone demo repository.")
    parser.add_argument("out", help="folder to create the demo repo in")
    parser.add_argument("--for-video", action="store_true",
                        help="leave out .bob/ so the video can show install and init from zero")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.exists():
        sys.exit(f"refusing to overwrite existing folder: {out}")

    # 1. copy the sample project, without its captured probe (Bob writes that live)
    shutil.copytree(SAMPLE, out, ignore=shutil.ignore_patterns(".bobreviewer", "__pycache__"))
    if not args.for_video:
        shutil.copytree(REPO_ROOT / ".bob", out / ".bob")

    # 2. a baseline suite that passes on every tag
    write(out, "tests/test_discount.py", (SAMPLE / "tests" / "test_discount.py").read_text())
    write(out, "tests/__init__.py", "")

    gitignore = [".venv/", "venv/", "__pycache__/", "*.py[cod]", ".pytest_cache/"]
    if not args.for_video:
        gitignore.append(".bobreviewer/runs/")
    write(out, ".gitignore", "\n".join(gitignore) + "\n")

    run(["git", "init", "-q", "-b", "main"], out)
    run(["git", "config", "user.name", "Demo"], out)
    run(["git", "config", "user.email", "demo@example.invalid"], out)
    run(["git", "config", "commit.gpgsign", "false"], out)

    # 3. demo-base: rounding version, no probes
    set_discount(out, DEMO_BASE_DISCOUNT)
    commit(out, "demo-base: sample pricing project")
    tag(out, "demo-base", "demo-base — rounding version, no probes")

    # 4. demo-rounding-change: only discount.py changes
    set_discount(out, DEMO_ROUNDING_DISCOUNT)
    commit(out, "demo-rounding-change: apply_discount truncates instead of rounding")
    tag(out, "demo-rounding-change", "demo-rounding-change — floor instead of round")

    # 5. demo-rounding-change-probed: Bob's probe added on top
    write(out, ".bobreviewer/probes/invoice_basic.json", PROBE_INVOICE)
    commit(out, "demo-rounding-change-probed: add the invoice probe")
    tag(out, "demo-rounding-change-probed", "demo-rounding-change-probed — probe committed")

    # 6. demo-rounding-fix: rounding restored, probe kept
    set_discount(out, DEMO_BASE_DISCOUNT)
    commit(out, "demo-rounding-fix: restore rounding")
    tag(out, "demo-rounding-fix", "demo-rounding-fix — restored, probe unchanged")

    # 7. Act 3: behaviour-preserving refactor on top of the probed change
    run(["git", "checkout", "-q", "-b", "refactor", "demo-rounding-change-probed"], out)
    set_discount(out, DEMO_REFACTOR_DISCOUNT)
    commit(out, "demo-refactor: compute the factor in a helper")
    tag(out, "demo-refactor", "demo-refactor — structurally different, same values")

    # 8. Act 4: a module the base revision cannot import
    run(["git", "checkout", "-q", "-b", "broken-import", "demo-rounding-change-probed"], out)
    write(out, "tax_tables.py", TAX_TABLES)
    write(out, ".bobreviewer/probes/tax_tables_basic.json", PROBE_TAX_TABLES)
    commit(out, "demo-broken-import: add tax_tables and its probe")
    tag(out, "demo-broken-import", "demo-broken-import — base cannot import tax_tables")

    # 9. Act 2: intended tax change, branched from demo-base
    run(["git", "checkout", "-q", "-b", "tax-update", "demo-base"], out)
    pricing = (out / "pricing.py").read_text().replace("TAX_RATE = 0.10", "TAX_RATE = 0.11")
    write(out, "pricing.py", pricing)
    write(out, ".bobreviewer/probes/pricing_basic.json", PROBE_PRICING)
    commit(out, "demo-tax-update: raise the tax rate to 11 percent")
    tag(out, "demo-tax-update", "demo-tax-update — intended policy change")

    # 10. Act 5: the same area changed again, so the earlier decision is cited as history
    pricing2 = pricing.replace("TAX_RATE = 0.11", "TAX_RATE = 0.12")
    write(out, "pricing.py", pricing2)
    commit(out, "demo-tax-update-v2: raise the tax rate to 12 percent")
    tag(out, "demo-tax-update-v2", "demo-tax-update-v2 — cites the earlier decision")

    # 11. leave main on demo-base, as the acceptance check requires. The commits above advanced
    # main, and the Act branches were cut from demo-base, so main must be reset back to the tag.
    run(["git", "checkout", "-q", "-B", "main", "demo-base^{commit}"], out)
    run(["git", "checkout", "-q", "--", "."], out)

    print(f"demo repo built at {out}")
    if args.for_video:
        print("  mode: --for-video (no .bob/, no .bobreviewer/runs/ ignore line)")
    print("  main is at demo-base; 8 annotated tags created")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
