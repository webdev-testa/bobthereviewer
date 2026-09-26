# bobthereviewer — Agent Instructions

Shared repo: **webdev-testa/pocbobbin**. Shell is **Windows PowerShell 5.1** — never chain
commands with `&&`; run them one per line.

## Branch

- Always start from the latest main: run `git fetch origin`, then
  `git checkout -b <type>/<short-description> origin/main`.
- `<type>` is one of: `feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `chore`, `style`.

## Commits

- Follow Conventional Commits: `type(scope): imperative summary`, max ~72 chars, no trailing period.
- Reuse existing scopes: `web`, `ui`, `cli`, `runner`, `triage`, `config`, `decisions`, `report`.
- Commit body: optional, at most one short paragraph for the non-obvious "why" a future reader
  can't get from the diff. Wrap lines at ~72 chars. No test output, no process narration, no lists.
- Never add AI attribution: no "Co-Authored-By", no "Generated with …" in commits or PRs.
  Commit as the user.
- Stage files explicitly. Never commit secrets or local paths (`C:\Users\…`, `/home/…`).
- `.gitignore` ignores `report.json`; published web data under `web/public/data` needs `git add -f`.

## Pull Requests

- Before opening or updating: `git fetch origin`, `git rebase origin/main`,
  `git push --force-with-lease` (only on your own branch).
- Create with: `gh pr create --title "type(scope): summary" --body "..."`.
- PR body: short paragraph on what and why, bullets only if the PR has several independent parts,
  one closing "Verified:" line with what you actually ran. Under 300 words, no headings.
- Only commit, push, open, or merge when explicitly asked.

## Merge (only when all CI checks are green)

- Squash only, with an explicit message:
  `gh pr merge <N> --squash --delete-branch --subject "type(scope): summary (#N)" --body "<one short paragraph>"`
- **Never merge PR #19** (a demo that must stay open).

## After Merging

```
git checkout main
git pull
git branch -d <branch>
git fetch --prune
gh repo sync kafiirgie/pocbobbin --source webdev-testa/pocbobbin --branch main
```

## Never

- Never force-push a branch someone else uses, skip hooks, or rewrite main's history.
- Never delete the folder or worktree you are working in.
- Never claim a check passed unless you ran it and saw it pass.
