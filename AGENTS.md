# bobthereviewer — Agent Instructions

## Repository Operations

Shared repo: **webdev-testa/bobthereviewer**. Shell is **Windows PowerShell 5.1** — never chain
commands with `&&`; run them one per line.

### Branch

- Always start from the latest main: run `git fetch origin`, then
  `git checkout -b <type>/<short-description> origin/main`.
- `<type>` is one of: `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `chore`, `style`.

### Commits

- Follow Conventional Commits: `type(scope): imperative summary`, max ~72 chars, no trailing period.
- Reuse existing scopes: `web`, `ui`, `cli`, `runner`, `triage`, `config`, `decisions`, `report`.
- Commit body: optional, at most one short paragraph for the non-obvious "why" a future reader
  can't get from the diff. Wrap lines at ~72 chars. No test output, no process narration, no lists.
- Never add AI attribution: no "Co-Authored-By", no "Generated with …" in commits or PRs.
  Commit as the user.
- Stage files explicitly. Never commit secrets or local paths (`C:\Users\…`, `/home/…`).
- `.gitignore` ignores `report.json`; published web data under `web/public/data` needs `git add -f`.

### Pull Requests

- Before opening or updating: `git fetch origin`, `git rebase origin/main`,
  `git push --force-with-lease` (only on your own branch).
- Create with: `gh pr create --title "type(scope): summary" --body "..."`.
- PR body: short paragraph on what and why, bullets only if the PR has several independent parts,
  one closing "Verified:" line with what you actually ran. Under 300 words, no headings.
- Only commit, push, open, or merge when explicitly asked.

### Merge (only when all CI checks are green)

- Squash only, with an explicit message:
  `gh pr merge <N> --squash --delete-branch --subject "type(scope): summary (#N)" --body "<one short paragraph>"`

### After Merging

```
git checkout main
git pull
git branch -d <branch>
git fetch --prune
```

### Never

- Never force-push a branch someone else uses, skip hooks, or rewrite main's history.
- Never delete the folder or worktree you are working in.
- Never claim a check passed unless you ran it and saw it pass.

---

## Project Purpose

`bobthereviewer` is a developer workflow tool that answers three questions about a code change:
1. What else might this change affect? (caller tracing)
2. Did the same inputs produce different outputs? (probe execution)
3. Was the difference intentional? (human decision record)

## Lane Ownership

| Lane | Person | Owns |
|---|---|---|
| A | Dev 1 | `contracts/` (schema authority), `src/bobthereviewer/{contracts,analysis,snapshots,triage,pipeline,cli,setup}.py` |
| B | Dev 2 | `src/bobthereviewer/{executor,_bootstrap,probe_selector,probe_runner,test_runner,progress,run_store,server}.py`, `demo/sample_project/` |
| C | Dev 3 | `src/bobthereviewer/report.py`, `web/`, the built bundle in `src/bobreviewer/frontend/` |
| D | Dev 4 | `src/bobthereviewer/{decisions,decide_cmd}.py`, `.bob/`, `.github/workflows/`, `submission/` coordination |

All Python code lives in `src/bobthereviewer/`. Plans and handoffs are in `docs/`.

## Shared Contracts

All schema changes go through Lane 1 (A). The canonical schemas live in `contracts/`:
- `contracts/probe.schema.json`
- `contracts/evidence.schema.json`
- `contracts/decision.schema.json`
- `contracts/config.schema.json`
- `contracts/local-server-api.md`

No lane should produce or consume these structures without referencing the canonical schema files.

## Fixtures

`tests/fixtures/evidence.fixture.json` — labeled `"fixture": true`.
This is NOT real evidence. It exists to unblock development before the engine produces real output.
Never use fixture data as demo evidence in a submission.

## Key Principles

- AI proposes. Algorithms verify. Humans decide.
- Never mark a check as passed without observed results.
- Never equate missing probes, unknown references, or an impact-only run with safety.
- Approved decisions come from git reachability on the default branch — not from the `status` field.
- All probe execution uses identical committed probe bytes on both revisions.
- Published evidence must omit secrets and local absolute paths.

## Running Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Bob IDE Workflow

Activate the behavior-review mode by typing `/behavior-review` in the Bob IDE chat panel.
The mode is defined in `.bob/custom_modes.yaml`.
