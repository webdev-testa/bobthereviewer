# handoffs/D.md — Lane 4 Handoff

## Owner
Person D — Bob workflow, decisions, and GitHub Actions

## Branch
`feat/lane4-bob-decisions-ci`

## Bob IDE Configuration (Verified Mechanism)
- **Config file:** `.bob/custom_modes.yaml` in workspace root
- **Mechanism:** Custom mode with `slug: behavior-review` — automatically registers `/behavior-review` slash command in Bob IDE (confirmed from official Bob docs: project modes in `.bob/custom_modes.yaml` take precedence over global modes)
- **Slash command:** `.bob/commands/behavior-review.md` — provides invocation guidance and initial context
- **Verification:** Open Bob IDE, type `/behavior-review` in the chat panel — the mode should appear in the slash command menu. If it does not appear, check Settings → Modes → Edit Project Modes to confirm the YAML loaded.

## What Has Been Shipped

### Contracts (shared with all lanes)
- `contracts/probe.schema.json` — probe file schema
- `contracts/evidence.schema.json` — evidence bundle schema
- `contracts/decision.schema.json` — decision record schema

### Fixture
- `fixtures/evidence.fixture.json` — labeled `"fixture": true`; realistic shape covering all key evidence fields. Use this while waiting for real Lane 1/2 output.

### Core Module
- `app/decisions.py` — `validate_and_save()` and `lookup()`:
  - `validate_and_save(decision_data, output_dir)` → writes `.bobreviewer/decisions/<slug>-<sha7>.json`
  - `lookup(repo, file_path, symbol, default_branch, decisions_dir)` → returns approved records
  - Enforces rationale ≥ 10 non-whitespace chars for `intended` verdicts
  - Always writes `status: "proposed"`; approval derived from git reachability

### Bob IDE Workflow
- `.bob/custom_modes.yaml` — `behavior-review` mode with full 7-step workflow in `customInstructions`
- `.bob/commands/behavior-review.md` — `/behavior-review` slash command entry point

### CI
- `.github/workflows/bobreviewer.yml` — triggers on PR open/push, runs CLI, uploads `evidence.json` and `report.html` as named artifacts, posts/updates one PR comment with unique marker `<!-- bobreviewer-comment -->`

### Scripts
- `scripts/bobreviewer_stub.py` — development stub (prints fixture evidence JSON); replace with real CLI when Lane 1 delivers
- `scripts/generate_report.py` — reads `evidence.json`, calls Lane 3 renderers (with stub fallback), writes `report.md` and `report.html`

### Tests
- `tests/test_decisions.py` — validate_and_save and lookup unit tests
- `tests/test_probe_authoring.py` — probe JSON schema validation tests
- `tests/test_history.py` — history lookup with decoy-rejection and disclaimer text
- `tests/test_rerun.py` — differ→match resolution, hash-mismatch blocking

## What Other Lanes Can Use

| Consumer | What to call | Where it lives |
|---|---|---|
| Lane 3 (C) | Nothing required from Lane 4 | — |
| Lane 4 (D, self) | `from app.decisions import validate_and_save, lookup` | `app/decisions.py` |
| CI workflow | `python scripts/generate_report.py --evidence ... --out-md ... --out-html ...` | `scripts/generate_report.py` |

## What Lane 4 Needs From Other Lanes

| Lane | Needed | Status |
|---|---|---|
| Lane 1 (A) | `bobreviewer run` CLI entry point | ⏳ using stub until available |
| Lane 1 (A) | `contracts/` schemas (locked) | ✅ committed by Lane 4 as placeholder; A to review and adjust |
| Lane 3 (C) | `from app.report import render_markdown(evidence) -> str` | ⏳ stub fallback in generate_report.py |
| Lane 3 (C) | `from app.html_report import generate_html(evidence) -> str` | ⏳ stub fallback in generate_report.py |
| Lane 2 (B) | Real `evidence.json` with probe results | ⏳ using fixture |

## Remaining Items

- [ ] Replace stub CLI invocation in `.bob/custom_modes.yaml` with real `bobreviewer run` call (coordinate with Lane 1)
- [ ] Capture Bob task-summary screenshots in `bob_sessions/D/` for each milestone
- [ ] Populate `submission/decisions/` with Act 1 and Act 2 decision JSONs after demo runs
- [ ] Write `submission/task-summaries/D-milestone-*.md` files
- [ ] Run fresh-install check: `git clone → pip install -e . → bobreviewer run`
- [ ] Verify `/behavior-review` slash command actually loads in installed Bob IDE (Sub-Task 1 manual step)

## Known Issues / Open Questions

1. Lane 1 must confirm the final `bobreviewer run` command flags before replacing the stub
2. Lane 3 must confirm function signatures for `render_markdown` and `generate_html`
3. CI workflow uses `pip install -e ".[dev]"` — Lane 2 should confirm the sample project's dependency setup
