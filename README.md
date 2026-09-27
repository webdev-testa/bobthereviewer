# bobthereviewer

Find what a code change actually affects, and whether the difference was intentional.

Tests tell you whether the cases someone thought of still pass. `bobthereviewer` answers three
other questions about a change:

1. **What else might this change affect?** It traces callers of every changed function, including
   code outside the diff that no reviewer would open.
2. **Did the same inputs produce different outputs?** It runs your committed *probes* — example
   inputs for a function — on the old and the new revision, and compares the results.
3. **Was the difference intentional?** A person records a decision (intended, unintended or
   unresolved, with a reason). It becomes approved only when merged into your default branch.

AI proposes. Algorithms verify. Humans decide.

## Install

You need **Python 3.11+** and **git**. Install the tool once per computer, isolated from your
projects' dependencies (no Node.js needed; the web UI ships inside the package):

```bash
uv tool install "git+https://github.com/webdev-testa/bobthereviewer@v0.1.0"
```

No `uv` yet? On Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
(on macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`). If `bobreviewer` is then not
found, run `uv tool update-shell` and open a new terminal.

Alternatives: `pipx install "git+https://github.com/webdev-testa/bobthereviewer@v0.1.0"`, or
`pip install` the same URL inside a virtual environment.

Tests and probes run in **your project's own Python**: its `.venv` (or the one you configure)
needs `pytest`, and nothing from this tool.

## Quick start on the demo repo

The demo is a small pricing project whose tags are the demo scenarios.

```bash
git clone https://github.com/Khaw100/bobthereviewer-demo
cd bobthereviewer-demo
bobreviewer init --yes
git add -A
git commit -m "Set up bobthereviewer"
bobreviewer doctor
```

`init` detects the base branch, test folder and Python, and creates `.bobreviewer/config.json`,
the Bob mode and the GitHub Action (it never overwrites a file). Commit them: reviews only use
committed files. `doctor` should end with "All checks passed".

Review the rounding change, whose probe is already committed:

```bash
bobreviewer run --before demo-base --after demo-rounding-change-probed
```

It finds `invoice.calculate_invoice` in another file as a caller of the changed
`discount.apply_discount`, runs the probe on both revisions, and reports
`[differ] … before: 100.0 after: 99.99`. Every run is saved under `.bobreviewer/runs/<run_id>/`
(`evidence.json`, `report.md`, `repo_map.json`).

Record your decision on that difference (the run id is in the printed run folder):

```bash
bobreviewer decide --run-id <RUN_ID> --symbol invoice.calculate_invoice --case-id invoice-small-discount --verdict unintended --rationale "Invoices must round to cents"
```

It writes a proposed decision to `.bobreviewer/decisions/` and prints the `git add … && git commit`
command. Commit it and the next review shows the decision next to that case.

Open the same runs in the browser:

```bash
bobreviewer ui
```

The local web UI shows the verdict, what needs your attention, the evidence map, the repo map,
tests and limits. From there you can start a new review and save a decision straight into the
repo; the web never commits for you.

## Use it on your own repository

1. `bobreviewer init` (answer the questions, or `--yes`), then commit the created files.
2. Work on a branch as usual and commit.
3. Review: `bobreviewer run` (it asks "Compare <branch> with main?"), or `bobreviewer ui`, or
   `/behavior-review` in Bob IDE.
4. For a caller that needs checking, commit a probe (below) and review again.
5. For each difference, decide: `bobreviewer decide …` or **Save decision** in the web UI, then
   commit the decision file.
6. Open the pull request. The Action posts one comment with the review and each difference's
   decision, and updates that comment on every push.

### Probes

A probe is a JSON file in `.bobreviewer/probes/` naming one function and a few inputs:

```json
{
  "schema_version": "1",
  "target": "invoice.calculate_invoice",
  "cases": [
    { "id": "invoice-small-discount", "args": [105.26, 0.05], "kwargs": {} }
  ]
}
```

The same committed probe bytes run on both revisions. Case ids must be unique and stable, because
decisions refer to them.

## Commands

| Command | What it does |
|---|---|
| `bobreviewer init [--yes] [--repo-dir DIR]` | Set up `.bobreviewer/`, the Bob mode and the GitHub Action |
| `bobreviewer doctor [--repo-dir DIR]` | Check readiness without installing or running anything |
| `bobreviewer analyze [--before REF] [--after REF] [--output DIR]` | Analysis only, no test or probe execution |
| `bobreviewer run [--before REF] [--after REF] [--probe FILE] [--prior-report FILE] [--full] [--open] [--output DIR]` | Full analysis and execution, saved as a run |
| `bobreviewer decide --run-id ID --symbol SYMBOL --case-id ID --verdict {intended,unintended,unresolved} --rationale TEXT` | Record a decision for a probe case result |
| `bobreviewer map [--ref REF] [--out FILE]` | Write the whole-repository module map for one revision |
| `bobreviewer ui [--port PORT] [--no-browser]` | Start the local web UI (opens your browser) |

Every command also takes `--repo-dir DIR`. `run --prior-report <earlier evidence.json>` links a
fixed case back to the run where it differed; `run --open` continues into the web UI on that run.

## Bob IDE

`init` installs the **behavior-review** mode in `.bob/custom_modes.yaml` (or, when that file
already has other modes, writes `.bobreviewer/bob-mode.yaml` for you to paste in). In Bob IDE, type
`/behavior-review`: Bob runs the review, explains the callers and differences, proposes probes for
you to commit, asks for your verdict (it never picks one), and records it with `bobreviewer decide`.

## GitHub Action

`init` writes `.github/workflows/bobreviewer.yml`. On every pull request it runs the review on the
PR's base and head commits with your committed probes, posts or updates one comment, and uploads
`evidence.json`, `report.md` and `repo_map.json` as the artifact `bobreviewer-pr-<number>`. If the
tool fails, the comment says so; it never shows placeholder data.

## Limits

- **Behavior evidence is Python only.** Python gets callers, tests and probes on both revisions.
  TypeScript, JavaScript, Java, C# and Go get callers across files; Rust, C and C++ get same-file
  callers only (beta). Nothing is run for them, and every report says which languages were analyzed
  and how ("Analyzed as").
- Callers are traced **two calls away**; anything further is not shown.
- Dynamic calls (`getattr`, dispatch tables) can't be followed; they are listed as possible links,
  never assumed safe.
- A changed module constant counts as a change to functions in the same module that read it; reads
  from other modules are not traced.
- Probes prove only the inputs they try. Matching cases do not certify a function is correct.
- Only committed code is reviewed; uncommitted edits are listed and left out.

## Web UI libraries

| Library | License |
|---|---|
| react, react-dom | MIT |
| @xyflow/react (React Flow) | MIT |
| elkjs | EPL-2.0 OR GPL-3.0-or-later |
| radix-ui, shadcn | MIT |
| tailwindcss, @tailwindcss/vite, tailwind-merge, tw-animate-css | MIT |
| clsx | MIT |
| class-variance-authority | Apache-2.0 |
| lucide-react | ISC |
| web-worker | Apache-2.0 |

## License

MIT — see [LICENSE](LICENSE).
