# bobthereviewer — User Guide

A step-by-step guide for using bobthereviewer on your project. No special knowledge needed:
if you can use `git` and run a command in a terminal, you can use this tool.

**What it does, in one sentence:** when you change code, it tells you what else that change
might affect, shows whether the program's answers actually changed, and lets a human record
whether the difference was meant to happen.

---

## Step 1 — Install (once per computer)

You need **Python 3.11+** and **git** installed.

```bash
uv tool install "git+https://github.com/webdev-testa/bobthereviewer@v0.1.0"
```

Check it works:

```bash
bobreviewer doctor --help
```

If the command is not found after installing, run `uv tool update-shell` and open a new
terminal window.

**Good to know:** this install is separate from your projects. It will not change anything
inside them.

## Step 2 — Set up your project (once per project)

Open a terminal inside your project folder, then:

```bash
cd path/to/your-project
bobreviewer init
```

`init` asks a few questions. Press **Enter** to accept each suggestion — it has usually
detected the right answer already. It creates:

- `.bobreviewer/config.json` — the settings it detected
- `.bobreviewer/probes/` — where your saved example inputs will live
- `.bobreviewer/decisions/` — where your recorded decisions will live
- `.bob/custom_modes.yaml` — the `/behavior-review` mode for Bob IDE
- `.github/workflows/bobreviewer.yml` — the automatic PR review

Then **commit those files** (reviews only use committed files):

```bash
git add -A
git commit -m "Set up bobthereviewer"
```

## Step 3 — Check everything is ready

```bash
bobreviewer doctor
```

You want the last line to say **"All checks passed"**.

If it complains that `pytest is not installed`, install it inside your project's own Python
environment (usually the `.venv` folder). Tests run in *your* Python, not the tool's.
`doctor` prints the exact command to run.

## Step 4 — Review a change

Make a change on a branch and commit it, as you normally would. Then:

```bash
bobreviewer run
```

It asks *"Compare `<branch>` with main?"* — press Enter to say yes. Or, to pick two versions
yourself:

```bash
bobreviewer run --before main --after my-feature-branch
```

You will see progress lines like:

```
✓ [triage]  Category: code
✓ [analyze] 3 changed function(s) found
✓ [done]    Run complete
```

The result tells you:

- **Changed functions** — the pieces of code your change touched
- **Callers outside the diff** — other places that use them, even in other files
- **Test results** — your existing tests, run on both the old and new version
- **Probe results** — the saved example inputs (Step 6), run on both versions

Every run is saved under `.bobreviewer/runs/` as real evidence files.

## Step 5 — Read the result honestly

The report may contain these words:

| Word | Meaning |
|---|---|
| `docs-only` | Only documentation changed, so nothing was executed |
| `differ` | The same input gave a different answer before and after |
| `match` | The answer was the same on both versions |
| `inconclusive` | The probe could not run — the reason is shown, not hidden |
| `No probes were selected` | You have not saved any example inputs yet, so no behaviour claim is made |

**No verdict is given.** The tool shows you what happened; a human decides what it means.
That is the whole point.

## Step 6 — Check a specific function with a probe (optional but powerful)

A **probe** is one function you care about, with a few example inputs. If a caller outside
your diff matters, commit a probe for it.

Create a file in `.bobreviewer/probes/`, for example `pricing_basic.json`:

```json
{
  "schema_version": "1",
  "target": "invoice.calculate_invoice",
  "cases": [
    { "id": "invoice-small-discount", "args": [105.26, 0.05], "kwargs": {} }
  ]
}
```

- `target` is the function, in the form `module.function`
- each case needs a short unique `id`, because decisions refer to it later

Commit the probe and run the review again. The tool runs the **exact same inputs** on the
old version and the new version, and compares the answers.

## Step 7 — Record your decision

For every `differ`, decide what it means:

```bash
bobreviewer decide --run-id <RUN_ID> \
  --symbol invoice.calculate_invoice \
  --case-id invoice-small-discount \
  --verdict unintended \
  --rationale "Invoices must round to cents"
```

- `<RUN_ID>` is printed when the run finishes (the folder name under `.bobreviewer/runs/`)
- `--verdict` is one of: `intended`, `unintended`, `unresolved`
- a rationale is required for `intended`

This writes a proposed decision file and prints the `git add`/`git commit` command for you.
**Commit it.** The decision only counts as approved once it is merged into your main branch —
that is what "approval" means here.

## Step 8 — Look at it in the browser (optional)

```bash
bobreviewer ui
```

Opens a local web page showing the same evidence, the map of your repository, and a
**Save decision** button that writes the decision file for you (it never commits for you).

## Step 9 — Let Bob do the review with you (optional)

In Bob IDE, type:

```
/behavior-review
```

Bob runs the review, explains the callers and differences, proposes probes for you to commit,
and asks for your verdict. It never picks the verdict for you.

## Step 10 — Let GitHub post the review on your pull request (optional)

Because `init` wrote `.github/workflows/bobreviewer.yml`, every pull request gets one comment
with the review and each difference's decision, updated on every push. Nothing to do: just
open the PR as usual.

---

## The whole loop, short version

```
bobreviewer init          # once per project
git add -A && git commit  # commit the setup files
bobreviewer doctor        # should say: All checks passed

# ... make your change and commit ...

bobreviewer run           # review it
bobreviewer decide ...    # record what each difference means
git add -A && git commit  # commit the decision
```

## If something looks wrong

- **`doctor` shows a red ✗** — fix that item first; it prints the command you need.
- **"No changed functions detected"** on a commit you expected to count — make sure you gave
  the right two versions (`--before` / `--after`), and remember the tool compares *committed*
  code only. Uncommitted edits are listed and left out.
- **Tests show an error about pytest** — install pytest in your project's own Python and run
  `doctor` again.
- Only committed code is ever reviewed; your uncommitted work stays yours.