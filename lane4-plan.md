# Lane 4 — Bob Workflow, Decisions, and GitHub Actions: Implementation Plan

## Top-Level Overview

**Goal:** Make `bobthereviewer` useful inside Bob IDE as a natural conversation, record human decisions as versioned JSON files, surface approved history in future reviews, and connect the same CLI to GitHub Actions so every PR gets an evidence comment and uploadable artifacts.

**You own:**
- `.bob/` — Bob IDE custom workflow / mode / prompt configuration
- `app/decisions.py` — decision JSON writer, validator, and history lookup
- `.bobreviewer/decisions/` — runtime home for decision records (gitignored locally; committed on approved branches)
- `.github/workflows/bobreviewer.yml` — CI workflow: run CLI, upload artifacts, post/update PR comment
- `bob_sessions/D/` — your task-summary screenshots for submission
- `handoffs/D.md` — your running handoff document

**You consume (do not reimplement):**
- `evidence.json` schema — written by Lane 1 (`contracts/evidence.schema.json`)
- `render_markdown(evidence)` — written by Lane 3 (`app/report.py`); Lane 4 calls this to produce the PR comment body
- `generate_html(evidence)` — written by Lane 3 (`app/html_report.py`); Lane 4 uploads the result as a workflow artifact
- The CLI entry points `bobreviewer analyze` / `bobreviewer run` — written by Lane 1

**Acceptance criteria to satisfy:** L4-P0-1 through L4-P0-7, L4-P1-1, L4-P1-2, AC-08, AC-09, AC-12, AC-13, AC-16.

**Product principle:** AI proposes. Algorithms verify. Humans decide. Bob may ask questions and draft text — Bob cannot supply intent, approve decisions, or mark unrun checks as passed.

---

## Dependency Map

```
Lane 1 → contracts/evidence.schema.json  (schema; lock on Day 1)
Lane 1 → contracts/decision.schema.json  (schema; lock on Day 1)
Lane 1 → bobreviewer CLI                 (Lane 4 invokes as subprocess)
Lane 2 → real probe results in evidence.json
Lane 3 → app/report.py render_markdown() (Lane 4 calls for PR comment)
Lane 3 → app/html_report.py generate_html() (Lane 4 calls for HTML artifact)
Lane 4 → app/decisions.py               (owns this module entirely)
Lane 4 → .bob/                           (owns Bob IDE configuration)
Lane 4 → .github/workflows/             (owns CI workflow)
```

---

## Sub-Tasks

---

### Sub-Task 1 — Fixture Bootstrap and Bob IDE Verification

**Status:** `[ ] pending`

**Intent:**
Before writing any workflow logic, verify that the Bob IDE customization mechanism actually loads and that a CLI invocation from within Bob works end-to-end. Record the working mechanism — a YAML file alone does not prove a mode loads or a slash command is registered. Also wire up the fixture from Lane 1 so Bob can present evidence during development before real engine output is available.

**Expected Outcomes:**
- The chosen Bob customization mechanism (mode file, prompt file, or hook) demonstrably loads in the installed Bob IDE — not just committed to disk.
- Bob can invoke `bobreviewer run` (or a stub script) as a subprocess from within a conversation and return its stdout to the chat.
- A fixture `evidence.json` (from Lane 1's `fixtures/evidence.fixture.json`) is readable by the Bob workflow and produces a Markdown table in chat.
- `handoffs/D.md` exists and records: which Bob config mechanism was used, how it was verified, and what the other lanes can rely on.

**Todo List:**
1. Read Bob IDE documentation to determine the correct customization mechanism: custom mode (`custom_modes.yaml`), slash command, or prompt file. Do not assume — verify the actual loaded state in the IDE.
2. Create the Bob config file under `.bob/` using the verified mechanism. Start minimal: a single system prompt that reads `PROJECT_SPEC.md` and `contracts/` on activation.
3. Test: open Bob, activate the configuration, run a basic prompt. Confirm the mode is active (not just the file saved).
4. Write a minimal stub script `scripts/bobreviewer_stub.py` that accepts `--before REF --after REF` and prints a hardcoded valid `evidence.json` to stdout. This unblocks Bob workflow development before Lane 1's CLI is ready.
5. In the Bob workflow, invoke the stub via `subprocess.run` (or Bob's shell tool) and capture stdout.
6. Pass the captured stdout (parsed as JSON) to `render_markdown` (or a local stub returning a static Markdown table) and display it in chat.
7. Capture a Bob task-summary screenshot; save to `bob_sessions/D/milestone-0-verification.png`.
8. Write `handoffs/D.md` with: Bob config file path, verification method, stub script path, and what Lane 3 needs to deliver for the real workflow (`render_markdown` signature).

**Relevant Context:**
- `PROJECT_SPEC.md` lines 196–223 — L4-P0-1 through L4-P0-7 criteria.
- `PROJECT_SPEC.md` lines 394–397 — Milestone 0: "D verifies that the chosen Bob customization mechanism actually loads."
- Bob IDE documentation (consult `search_ibm_docs` with library `bob` if uncertain about config schema).

---

### Sub-Task 2 — Bob Conversational Probe Authoring

**Status:** `[ ] pending`

**Intent:**
Implement the Bob conversation flow that guides a developer to produce a valid probe JSON file. Bob inspects the evidence for callers marked `needs_probe: true`, proposes a probe targeting that caller, and the developer commits the probe file before the next run. Bob must not auto-commit or auto-execute — it only proposes.

**Expected Outcomes:**
- Bob reads `changed_functions[*].callers` from evidence and identifies entries where `needs_probe === true`.
- Bob generates a candidate probe JSON matching `contracts/probe.schema.json`: correct `schema_version`, a valid `target` (fully qualified function name), and at least one `cases` entry with `id`, `args`, `kwargs`.
- The generated probe JSON validates against `contracts/probe.schema.json` when run through a validator (Python `jsonschema` or Pydantic).
- Bob presents the probe to the developer and asks for confirmation before writing the file.
- Bob instructs the developer to commit the file; Bob does not auto-commit.
- Acceptance criterion L4-P0-1: a Bob conversation can produce a valid probe JSON file.

**Todo List:**
1. In the Bob system prompt / workflow, add a step: after presenting the evidence summary, check `needs_bob_action` flag (or scan callers for `needs_probe: true`).
2. If a caller needs a probe, compose a probe JSON object using the caller's `symbol` and `file_path`. Use realistic but clearly placeholder `args` and `kwargs` (e.g., `args: [100.0, 0.05]` for a discount function).
3. Present the probe to the developer as a formatted code block with a clear "Please review these inputs, adjust if needed, and save this file to `probes/<name>.json`" instruction.
4. Add a validation step: read the generated probe dict through `contracts/probe.schema.json` using Python `jsonschema`; surface any validation errors to the developer rather than silently accepting invalid probes.
5. Write `tests/test_probe_authoring.py` — generate a probe dict using the same logic, validate it against the schema, assert no errors.
6. Capture a Bob screenshot showing the probe proposal; save to `bob_sessions/D/probe-authoring.png`.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 196–199 — L4-P0-1 criterion.
- `contracts/probe.schema.json` — probe file schema (Lane 1 owns; read only).
- `PROJECT_SPEC.md` lines 444–446 — Act 1 step 4: "Bob guides probe authoring; developer reviews and commits."

---

### Sub-Task 3 — Bob Evidence Summary and Markdown Table

**Status:** `[ ] pending`

**Intent:**
Bob invokes `bobreviewer run` as a real subprocess (replacing the stub), reads the `evidence.json` output, calls Lane 3's `render_markdown`, and presents the results as a Markdown table in chat. This is the core Bob → CLI → evidence → chat loop.

**Expected Outcomes:**
- Bob invokes the real `bobreviewer run --before <ref> --after <ref>` CLI (Lane 1's implementation) and captures stdout / the written `evidence.json`.
- Bob calls `from app.report import render_markdown` and presents the result in chat.
- The chat output includes: changed function, callers outside the diff (with `[outside diff]` label), test results (pass/fail counts), probe results (before/after values and status), and analysis limits.
- If `evidence.json` is missing or the CLI exits non-zero, Bob surfaces a clear error message — not a Python traceback.
- Acceptance criterion L4-P0-2: Bob invokes `bobreviewer run` as a subprocess and presents a Markdown table.

**Todo List:**
1. Replace the stub invocation in the Bob workflow with the real CLI call: `bobreviewer run --before {base_ref} --after {head_ref}`.
2. Capture the CLI exit code; if non-zero, surface the stderr output with a "CLI run failed" prefix in chat.
3. Locate the written `evidence.json` (default output dir or `--output` flag); read and parse it.
4. Call `render_markdown(evidence)` and post the result as a chat message.
5. Add a note in chat: "Analysis limits: {analysis_limits.notes}. These cases do not prove general equivalence."
6. Write `tests/test_bob_workflow.py` — mock the subprocess call, pass a fixture evidence JSON, assert `render_markdown` output appears in the assembled chat message.
7. Capture a Bob screenshot of the real CLI output in chat; save to `bob_sessions/D/evidence-summary.png`.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 199–201 — L4-P0-2 criterion.
- `app/report.py` `render_markdown` — Lane 3 delivers this; coordinate signature with Lane 3 early.
- `PROJECT_SPEC.md` lines 62–72 — CLI interface (`bobreviewer run` flags).

---

### Sub-Task 4 — Decision JSON Writer (`app/decisions.py`)

**Status:** `[ ] pending`

**Intent:**
Implement `app/decisions.py` with two public functions: `validate_and_save(decision_data, output_dir)` that validates and writes a decision JSON file, and `lookup(repo, file_path, symbol, default_branch)` that finds earlier approved decisions. Bob calls `validate_and_save` after the developer states their verdict; the CI viewer calls `lookup` for history context.

**Expected Outcomes:**
- `validate_and_save(decision_data: dict, output_dir: Path) -> Path` validates the dict against `contracts/decision.schema.json`, rejects `intended` verdicts with an empty/short rationale (< 10 non-whitespace characters), writes the file to `output_dir/<symbol>-<head_commit_short>.json`, and returns the written path.
- Calling with an `intended` verdict and an empty rationale raises a `ValueError` with a message the caller can show to the developer.
- `lookup(repo: str, file_path: str, symbol: str, default_branch: str = "main") -> list[dict]` reads all `.json` files under `.bobreviewer/decisions/`, filters by matching `repository`, `file_path`, and `symbol`, and returns only records whose file is present in a commit reachable from `HEAD` on the default branch (using `git log --name-only`). Returns an empty list if none found.
- The `status` field is always written as `"proposed"` — `lookup` derives approval from git reachability, never from the field value.
- `app/decisions.py` is importable; `app/__init__.py` exists.

**Todo List:**
1. Create `app/decisions.py`.
2. Implement `validate_and_save(decision_data: dict, output_dir: Path) -> Path`:
   - Validate against `contracts/decision.schema.json` using `jsonschema`.
   - Check: if `verdict == "intended"` and `len(rationale.strip()) < 10`, raise `ValueError("Intended verdict requires a meaningful rationale (at least 10 characters).")`.
   - Force `status = "proposed"` regardless of what was passed in.
   - Write to `output_dir / f"{symbol_slug}-{head_commit_short}.json"` where `symbol_slug` replaces `.` with `_`.
   - Return the written path.
3. Implement `lookup(repo, file_path, symbol, default_branch="main") -> list[dict]`:
   - Collect all `.json` files under `.bobreviewer/decisions/`.
   - Parse each; filter where `repository == repo AND file_path == file_path AND symbol == symbol`.
   - For each matching record, check git reachability: run `git log {default_branch} --name-only --pretty=format:""` and check whether the decision file's repo-relative path appears. Include only reachable records.
   - Return the filtered list.
4. Ensure `.bobreviewer/decisions/` is created by `validate_and_save` if it does not exist.
5. Write `tests/test_decisions.py`:
   - Test that a valid `intended` decision with rationale writes successfully.
   - Test that `intended` with empty rationale raises `ValueError`.
   - Test that `unintended` with empty rationale writes successfully.
   - Test that `lookup` returns an empty list when no decisions directory exists.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 56–57 — Decision approval model; git reachability.
- `contracts/decision.schema.json` — full field list including `rationale` constraint.
- `PROJECT_SPEC.md` lines 201–204 — L4-P0-3 and L4-P0-4 criteria.

---

### Sub-Task 5 — Bob Decision Loop (Verdict → File → History)

**Status:** `[ ] pending`

**Intent:**
Wire the decision writer into the Bob conversation. After presenting evidence, Bob asks for the developer's verdict, collects the rationale if `intended`, calls `validate_and_save`, confirms the written file path, and — when a probe case resolves an earlier delta — surfaces prior approved decisions as context with the required disclaimer.

**Expected Outcomes:**
- Bob presents three explicit choices in chat: `intended`, `unintended`, `unresolved`. Bob does not infer or default.
- If `intended` is chosen, Bob prompts for a rationale and rejects submission if it is too short (< 10 non-whitespace characters after trimming), asking again.
- After a valid verdict, Bob calls `validate_and_save` and confirms the written file path in chat: "Decision written to `.bobreviewer/decisions/<filename>.json`. Commit this file to record the decision."
- `lookup` is called before presenting evidence; if earlier approved decisions exist for the same `repository + file_path + symbol`, Bob surfaces them with the exact text: **"Prior decision found: [verdict] — [rationale]. This is prior context, not approval of the current change."**
- Acceptance criteria L4-P0-3, L4-P0-4, L4-P0-5.

**Todo List:**
1. In the Bob workflow, after presenting the evidence summary, call `lookup` with the current run's `repository`, `file_path`, and `symbol`.
2. If prior decisions are found, prepend a notice to the chat message using the required exact text.
3. Present the verdict choices as a numbered or bulleted list; ask the developer to state their choice.
4. If `intended`, prompt for rationale. Validate length; if < 10 characters, explain the requirement and ask again. Bob must not supply the rationale.
5. Call `validate_and_save(decision_data, Path(".bobreviewer/decisions"))`.
6. Confirm the written path in chat; remind the developer to commit the file.
7. If `unintended`, proceed to Sub-Task 6 (fix assistance). If `unresolved`, write the file and note that the review can be reopened.
8. Write `tests/test_decision_loop.py` — simulate a Bob-style conversation dict and assert the prior-context disclaimer text appears when a matching approved decision exists.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 201–211 — L4-P0-3 through L4-P0-5 criteria.
- `PROJECT_SPEC.md` lines 475–478 — Act 5: history lookup text requirement.
- `app/decisions.py` — Sub-Task 4 deliverable.

---

### Sub-Task 6 — Unintended Change: Fix Assistance and Rerun

**Status:** `[ ] pending`

**Intent:**
When a developer marks a difference as `unintended`, Bob drafts a fix (clearly labeled as a draft, ending with questions for the author), the developer commits the fix, and Bob reruns the same unchanged probe against the original base and new head. The rerun result links to the earlier delta via `prior_run_id` and `probe_hash`.

**Expected Outcomes:**
- When verdict is `unintended`, Bob generates a fix draft labeled: **"Draft — review before committing. Questions for you: [questions]."** Bob does not auto-commit.
- After the developer commits the fix, Bob invokes `bobreviewer run --before <base_ref> --after <fix_ref> --prior-report <earlier_evidence_path>` with the **unchanged probe** (same file, same bytes — not re-authored).
- The rerun `evidence.json` contains `prior_run_id` pointing to the earlier run's `run_id`.
- Probe cases that changed from `differ` to `match` are annotated in the chat: "✅ Resolved: case `<id>` changed from `differ` to `match` (linked to prior run `<run_id>`)."
- A changed probe hash cannot create a resolution link — if the probe file was modified, Bob notes "Probe hash mismatch — this result cannot be linked to the earlier delta."
- Acceptance criteria L4-P0-2 (rerun presentation), L4-P1-1 (rerun annotation).

**Todo List:**
1. In the Bob workflow, when `verdict == "unintended"`, generate a fix suggestion based on the `base_output` vs `head_output` delta. Clearly prepend: "**Draft — review before committing.**"
2. End the fix draft with at least two questions for the author (e.g., "Is this the only call site affected?" and "Should the rounding behavior be documented?").
3. After the developer confirms a fix commit, prompt for the new head ref.
4. Invoke `bobreviewer run --before {base_ref} --after {fix_ref} --prior-report {earlier_evidence_path}`.
5. Read the new `evidence.json`; check each probe case: if `prior_difference_run_id` is populated and `status == "match"`, annotate it as resolved in chat.
6. If `probe_hash` in the new run does not match the hash in the prior run, show a warning: "Probe was modified — resolution link not valid."
7. Write `tests/test_rerun.py` — pass two fixture evidence JSONs (before/after fix), assert the resolved-case annotation appears and the hash-mismatch warning fires when hashes differ.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 447–451 — Act 1 steps 7–9 (fix → rerun → match).
- `PROJECT_SPEC.md` lines 219–220 — L4-P1-1: annotate resolved probe cases.
- `evidence.schema.json` fields: `prior_run_id`, `probe_hash`, `prior_difference_run_id`.

---

### Sub-Task 7 — GitHub Actions Workflow

**Status:** `[ ] pending`

**Intent:**
Create `.github/workflows/bobreviewer.yml` that runs `bobreviewer run` on every PR push, uploads `evidence.json` and the static HTML as named artifacts, and posts (or updates) a single PR comment containing the Markdown report and an artifact link.

**Expected Outcomes:**
- The workflow triggers on `pull_request` events (opened, synchronize, reopened).
- It runs `bobreviewer run --before $BASE_SHA --after $HEAD_SHA` using the PR's base and head SHAs.
- `evidence.json` and the static HTML (from `generate_html`) are uploaded as named workflow artifacts: `behavior-review-evidence` and `behavior-review-html`.
- A PR comment is posted (or an existing comment from the same workflow is updated — not duplicated) containing the `render_markdown(evidence)` output and a link to the artifacts.
- If the CLI exits non-zero, the workflow posts a "Behavior review failed — see logs" comment and fails the job (does not silently pass).
- Installation/execution failures cannot masquerade as a passing report.
- Acceptance criteria L4-P0-6, L4-P0-7.

**Todo List:**
1. Create `.github/workflows/bobreviewer.yml`.
2. Add trigger: `on: pull_request: types: [opened, synchronize, reopened]`.
3. Add steps:
   - `actions/checkout@v4` with `fetch-depth: 0` (full history needed for worktrees).
   - `actions/setup-python@v5` with Python 3.11.
   - `pip install -e .` to install the package.
   - `bobreviewer run --before ${{ github.event.pull_request.base.sha }} --after ${{ github.sha }} --output output/` — capture exit code.
   - On non-zero exit: post failure comment and `exit 1`.
4. Add step: call a Python script `scripts/generate_report.py` that reads `output/evidence.json`, calls `render_markdown` and `generate_html`, writes `output/report.md` and `output/report.html`.
5. Upload artifacts: `actions/upload-artifact@v4` for `output/evidence.json` (name: `behavior-review-evidence`) and `output/report.html` (name: `behavior-review-html`).
6. Post PR comment using `actions/github-script` or `peter-evans/create-or-update-comment`:
   - Find existing comment with a unique marker string (e.g., `<!-- bobreviewer-comment -->`).
   - If found, update it; if not, create a new one.
   - Comment body: marker + contents of `output/report.md` + artifact download link.
7. Store the GitHub token as `${{ secrets.GITHUB_TOKEN }}` — no extra secret needed for the comment.
8. Add a `README` section (or note in `handoffs/D.md`) explaining any additional secrets needed (e.g., if `bobreviewer` needs credentials for private repos).

**Relevant Context:**
- `PROJECT_SPEC.md` lines 199–214 — L4-P0-6 and L4-P0-7 criteria.
- `PROJECT_SPEC.md` lines 374–385 — Architecture diagram showing CI lane.
- `PROJECT_SPEC.md` lines 222–223 — L4-P1-2: fresh-install check.

---

### Sub-Task 8 — History Lookup: Approved Decision Scenario (Act 5)

**Status:** `[ ] pending`

**Intent:**
Demonstrate the full approved-decision lookup path using the demo scenario: the Act 2 decision (tax policy change) is merged to the default branch; a later `demo-tax-update-v2` run surfaces it as prior context. Verify the exact repository + file path + symbol matching rule — a function with the same name in a different file must not borrow the decision.

**Expected Outcomes:**
- Running `bobreviewer run --before demo-base --after demo-tax-update-v2` surfaces the prior decision from Act 2 with the required disclaimer text.
- A different function in a different file with the same name does not receive the prior decision as context.
- The `lookup` function is exercised with a real merged decision file in the repository.
- Bob's chat output for this scenario is captured as a screenshot.
- Acceptance criteria AC-09, L4-P0-4, L4-P0-5.

**Todo List:**
1. Ensure the Act 2 decision JSON (`pricing.calculate_price` from `demo-tax-update`) is committed to `.bobreviewer/decisions/` and merged to `main` (simulated in the demo repo).
2. Create a second decision file for a function with the same name (`calculate_price`) but a different `file_path` (e.g., `sample_project/billing/pricing.py`) to verify the negative case.
3. Run the Act 5 scenario; confirm `lookup` returns exactly one record (the Act 2 decision), not the decoy.
4. Confirm the chat output contains: "Prior decision found: intended — [rationale]. This is prior context, not approval of the current change."
5. Write `tests/test_history.py` — populate a temp `.bobreviewer/decisions/` dir with two decision files (same symbol, different file paths); assert `lookup` returns only the matching one.
6. Capture a Bob screenshot of the history lookup output; save to `bob_sessions/D/history-lookup.png`.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 56–57 — Approval via git reachability from default branch.
- `PROJECT_SPEC.md` lines 204–207 — L4-P0-4 and L4-P0-5 criteria.
- `PROJECT_SPEC.md` lines 475–478 — Act 5 demo script.

---

### Sub-Task 9 — Submission, Screenshots, and Evidence Index

**Status:** `[ ] pending`

**Intent:**
Collect all required submission artifacts for Lane 4: Bob task-summary screenshots from each milestone in `bob_sessions/D/`, decision JSON files in `submission/decisions/`, and a final updated `handoffs/D.md`. D coordinates submission evidence from the whole team.

**Expected Outcomes:**
- `bob_sessions/D/` contains screenshots from at least: milestone-0 verification, probe authoring, evidence summary in chat, decision recording, history lookup, CI comment, and fresh-install check.
- `submission/decisions/` contains the Act 1 (unintended) and Act 2 (intended) decision JSON files.
- `handoffs/D.md` is complete with: all shipped items, public API for other lanes, remaining known issues.
- `submission/task-summaries/D-*.md` contains one task summary per milestone.
- Fresh-install check passes: `git clone → pip install -e . → bobreviewer run` on sample project, documented in `handoffs/D.md`.
- Acceptance criteria AC-16, L4-P1-2.

**Todo List:**
1. Review `bob_sessions/D/` — ensure screenshots are present for each milestone gate.
2. Copy Act 1 and Act 2 decision JSON files to `submission/decisions/`.
3. Write `submission/task-summaries/D-milestone-0.md` through `D-milestone-4.md` — one per milestone, referencing actual Bob conversations and observed results.
4. Run `git clone <repo> /tmp/fresh && cd /tmp/fresh && pip install -e . && bobreviewer run --before demo-base --after demo-rounding-change` in a clean environment; confirm success; document in `handoffs/D.md`.
5. Update `handoffs/D.md` with final API table: what Lane 3 must provide (`render_markdown`, `generate_html`), what Lane 1 must provide (CLI flags, `evidence.json` fields), and what Lane 4 delivers to the team.
6. Verify no `bob_sessions/D/` screenshots are missing or placeholder images.

**Relevant Context:**
- `PROJECT_SPEC.md` lines 482–495 — submission artifacts table.
- `PROJECT_SPEC.md` lines 219–223 — L4-P1-1 and L4-P1-2 criteria.

---

## Acceptance Criteria Map

| Criterion | Covered by Sub-Task(s) |
|---|---|
| L4-P0-1 Bob produces valid probe JSON | Sub-Task 2 |
| L4-P0-2 Bob invokes CLI, presents Markdown table | Sub-Tasks 3, 6 |
| L4-P0-3 Decision JSON written; intended requires rationale | Sub-Tasks 4, 5 |
| L4-P0-4 History lookup by repo + file path + symbol | Sub-Tasks 4, 8 |
| L4-P0-5 Prior decision surfaced with required disclaimer | Sub-Tasks 5, 8 |
| L4-P0-6 CI posts/updates PR comment | Sub-Task 7 |
| L4-P0-7 Evidence JSON + HTML uploaded as artifacts | Sub-Task 7 |
| L4-P1-1 Rerun annotates resolved probe cases | Sub-Task 6 |
| L4-P1-2 Fresh-install check | Sub-Task 9 |
| AC-08 Intended rejected without rationale; no web approval | Sub-Tasks 4, 5 |
| AC-09 Approved via merge; symbol+path match; decoy rejected | Sub-Task 8 |
| AC-12 Full Bob session: CLI → probe → evidence → fix → rerun | Sub-Tasks 1–6 |
| AC-13 CI runs CLI, uploads artifacts, updates one comment | Sub-Task 7 |
| AC-16 All four members' screenshots in bob_sessions/ | Sub-Task 9 |

---

## Cut Order (If Time Is Short)

Cut last → Cut first:
1. **Never cut:** Bob CLI invocation (Sub-Task 3), decision writer (Sub-Task 4), GitHub Actions comment (Sub-Task 7) — these are the core P0 deliverables.
2. **Cut later:** Rerun delta annotation (Sub-Task 6 step 5–6) — rerun still works, just without the annotation.
3. **Cut if necessary:** History lookup negative-case test (Sub-Task 8 step 2) — keep the positive case, skip the decoy.
4. **Do not cut:** Bob IDE verification (Sub-Task 1) — an unverified mode is not a working workflow.
5. **Cut last of P1:** Fresh-install check (Sub-Task 9 step 4) — important but last item.

---

## Resolved Decisions

1. **Bob config mechanism:** To be verified in Sub-Task 1 against installed Bob IDE docs — do not assume.
2. **Decision approval:** Derived from `git log <default_branch> --name-only` reachability; never by editing the `status` field.
3. **Rationale minimum:** 10 non-whitespace characters after trimming (from spec section 4).
4. **PR comment deduplication:** Find-and-update by unique HTML comment marker `<!-- bobreviewer-comment -->`.
5. **Lane 3 dependency:** Lane 4 calls `render_markdown` and `generate_html` from `app/report.py` and `app/html_report.py` — coordinate the function signatures with Lane 3 early.

## Remaining Open Questions

1. **Bob config file location:** Does the installed Bob IDE read from `.bob/` in the workspace root, or from a user-level directory? Verify before Sub-Task 1.
2. **CI Python environment:** Does the sample project use a `requirements.txt`, `pyproject.toml` extras, or a `conda` env? Lane 2 needs to confirm so the Actions workflow installs correctly.
3. **Artifact retention:** What artifact retention period is needed for the judge to download the HTML viewer? GitHub default is 90 days — sufficient, but confirm.
