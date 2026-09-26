# bobthereviewer — Project Specification

## What We Are Building

**bobthereviewer** is a developer tool that answers three questions about a code change:

1. **What else might this change affect?** — Find functions that changed and trace their direct callers up to two hops, highlighting callers in files that were not themselves modified.
2. **Does it actually behave differently?** — Run the same frozen test suite and the same probe bytes against both the before and after revisions and show inputs and outputs side by side.
3. **Was that difference intentional?** — Let the developer record a JSON decision (intended / unintended / unresolved) with a rationale, then surface earlier approved decisions as context in future reviews without using them as automatic approval.

The tool is designed to catch what code review and passing tests can miss: a small, locally-correct change that silently shifts behavior in a caller that was never touched.

It runs from the terminal, works inside Bob IDE through ordinary CLI invocation, and posts findings to a GitHub pull request as a Markdown comment via GitHub Actions. Judges can explore a real report in a fully static HTML page without installing anything.

---

## What We Are Leaving Out

- Multi-language support — Python only for this version
- Whole-repository call graph — two-hop caller tracing on the changed functions only
- Autonomous code fixing — Bob helps draft a fix; the developer commits and reruns
- Live server for the web viewer — static HTML, session-only decision previews
- Database or backend — all persistent state is files in the repository
- Dynamic dispatch resolution — calls through `getattr`, decorators, or frameworks are marked `unknown`
- External service dependencies in demo scenarios — all demo scenarios are fully reproducible offline
- Proving a change is safe — the tool reports what it observed; it does not certify correctness

---

## Core Concepts

### Revisions

The user supplies two explicit Git refs on the CLI (`--before REF --after REF`). **Demo scenarios use a stable immutable tag (`demo-base`) as the before ref so runs are reproducible regardless of branch movement.** The tool checks out each ref into a separate temporary Git worktree and runs all execution inside isolated subprocesses. The two revisions never share a process. After execution the worktrees are cleaned up, and the developer's checkout, index, working branch, and uncommitted files are left exactly as they were — including when execution fails.

### Probes

A probe is a committed JSON file in `probes/` that describes a target function and a fixed set of inputs. The shared probe runner (part of the tool, outside the target project's code) loads the target function from the worktree subprocess and calls it with the supplied arguments. It captures the return value (any JSON-representable value: number, string, boolean, null, list, or object) or a structured exception record, and writes a result entry. The same committed probe bytes run against both revisions — a probe cannot change between sides. Probe and case IDs are stable identifiers used to link results across runs.

**Probe selection rule:** The frozen set is all probes present in the base revision plus any probes added in the head revision. If a probe file was edited or deleted in the head revision, the base version of that file is used on both sides.

### Tests

Existing pytest tests run as a separate evidence stream alongside probes. The frozen test suite is the set of test files present in the base revision, run with the base `pytest.ini` / `pyproject.toml` test configuration. New test files added in the head revision do not run in this frozen suite. Test results are captured as `pass`, `fail`, or `error` per node ID. Existing failures on the base revision remain visible — they are not hidden. A matching exception across both sides is not a passing test; it is recorded as `error` on both.

### Impact Analysis

The tool parses ASTs from **both revisions** and inspects all other repository files to find callers outside the diff. Call relationships from both sides are combined so that removed calls are not missed. An import statement alone does not establish that one function calls another — there must be a resolved call site in the AST. Callers in files that were not part of the diff are highlighted. Dynamic or unresolved references are surfaced in a separate `unknown_references` list with a reason for each. The caller entry includes the file path and line number of the call site.

### Evidence Bundle

After analysis and execution, the tool writes a single `evidence.json` file. This is the handoff between all four lanes and the single source of truth for the report, the Bob workflow, and the GitHub comment. The report, viewer, and Bob all read the same file — they do not implement their own parsing of git or probe output.

### Decision Records

A decision is a JSON file written into the repository under `.bobreviewer/decisions/`. It starts as `proposed` when written during development. The team's review and merge of the branch is what makes it `approved` — an approved decision is one that has been merged to the default branch and is present in a commit reachable from `HEAD` on that branch. A matching historical decision surfaces as context in a future review but never automatically approves a new change. **History matching uses repository + file path + symbol together — function name alone is not sufficient.** An `intended` verdict requires a non-empty human rationale.

---

## Command Interface

```
bobreviewer analyze --before REF --after REF [--output DIR]
```
Analysis-only run. Computes the impact map (changed functions and callers). Writes `evidence.json` with `changed_functions` populated but `test_results` and `probe_results` empty. Does not execute any code.

```
bobreviewer run --before REF --after REF [--probe FILE ...] [--prior-report FILE] [--output DIR]
```
Full run. Performs analysis, runs the frozen test suite, and runs probes. `--probe FILE` accepts a path to a committed probe file in the repository (not an arbitrary local path — the file must exist in both the repository and the current index). Multiple `--probe` flags are accepted. `--prior-report FILE` supplies a path to an earlier `evidence.json` so the new run can link rerun probe results to earlier difference records by run ID and probe hash. Writes a complete `evidence.json`.

All subcommands return exit code `0` on successful completion (including inconclusive results), non-zero on hard failure (unreadable ref, broken worktree setup, schema validation error).

---

## Four-Person Ownership

Work is designed to proceed in parallel. The critical path is: **shared contracts** → **first real comparison** → **Bob/human decision loop** → **CI and viewer** → **recording**. All four lanes can work simultaneously after contracts are locked; integration points are the evidence JSON and decision JSON boundaries.

### Lane 1 — Differ, Contracts, Snapshots, and CLI (Dev 1)

**Owns:**
- Shared contracts: probe JSON schema, evidence JSON schema, decision JSON schema — Lane 1 coordinates all schema changes; no other lane changes these without Lane 1 review
- Git worktree creation and teardown for both revisions; guarantee developer environment is unchanged after any exit path
- AST-based changed-function finder using both revision ASTs; combined caller tracer (two hops, resolved call sites only); separate `unknown_references` list with reasons
- CLI entry points: `bobreviewer analyze` and `bobreviewer run`
- Writing and schema-validating the final `evidence.json`

**Acceptance Criteria — P0 (must ship):**

| ID | Criterion |
|---|---|
| L1-P0-1 | `bobreviewer analyze --before demo-base --after HEAD` prints changed functions and their callers with file and line locations to stdout |
| L1-P0-2 | Callers in unchanged files are flagged; unresolved/dynamic references appear in a separate `unknown_references` list with a reason string |
| L1-P0-3 | Two temporary worktrees are created, populated, and removed; the developer's working tree, index, and branch are unchanged after both normal exit and failure exit |
| L1-P0-4 | `evidence.json` validates against the agreed schema; all required fields are present and enum values are valid |
| L1-P0-5 | CLI returns exit code 0 on analysis success and non-zero on hard failure; inconclusive probe results do not count as hard failures |
| L1-P0-6 | Removed call sites from the base revision appear in the combined caller list, not silently dropped |

**Acceptance Criteria — P1 (should ship):**

| ID | Criterion |
|---|---|
| L1-P1-1 | `--prior-report FILE` is accepted and the supplied run ID is written into the new `evidence.json` for linking |
| L1-P1-2 | Schema validation failure on `evidence.json` write produces a human-readable error, not a Python traceback |

**Verification:** Run `bobreviewer analyze --before demo-base --after demo-rounding-change` on the sample project; confirm `discount.apply_discount` appears as changed and `invoice.calculate_invoice` appears as a caller in an unchanged file with a file/line reference.

---

### Lane 2 — Executor and Demo Scenarios (Dev 2)

**Owns:**
- Subprocess-isolated pytest runner (frozen base test suite and config; both worktrees; identical invocation)
- Probe runner (shared Python runner outside target code; any JSON value output; structured exception capture)
- Inconclusive classification: import error and missing dependency → `inconclusive`; legitimate raised exception → `exception` (not `inconclusive`); nondeterminism detected by repeated run → `inconclusive`
- Repeated-run check: probes run twice on each side; if outputs differ between the two runs on the same revision, mark `inconclusive` with reason `nondeterminism_detected`
- Frozen probe selection logic (base probes + new head probes; base version of edited/deleted probes)
- Result schema population: before/after output pairs; exception details; inconclusive reasons; execution timestamps
- Frozen-suite hash in `evidence.json` (SHA-256 of the sorted list of frozen test file paths and their contents)
- All five demo scenarios in `demo/sample_project/` on committed tags

**Acceptance Criteria — P0:**

| ID | Criterion |
|---|---|
| L2-P0-1 | pytest runs in a subprocess against each worktree with the frozen base config; results captured as `pass`/`fail`/`error` per node ID; existing base failures visible on both sides |
| L2-P0-2 | Probe runner executes the same probe bytes against both worktrees; captures any JSON value (number, null, bool, list, object) or a structured `{"exception": "<type>", "message": "<msg>"}` record |
| L2-P0-3 | A probe that fails due to a missing dependency or broken import is marked `inconclusive` with `reason: "import_error"` and the verbatim error message; the tool does not crash |
| L2-P0-4 | A probe that raises a legitimate exception from the target function records `{"exception": ..., "message": ...}` on that side; matching exceptions on both sides are not treated as a match |
| L2-P0-5 | Repeated-run check runs each probe twice per side; diverging outputs within the same revision produce `inconclusive` with `reason: "nondeterminism_detected"` |
| L2-P0-6 | New probes committed on the head branch run against both worktrees |
| L2-P0-7 | An edited or deleted probe on the head branch uses the base version on both sides |
| L2-P0-8 | All five demo scenarios produce evidence bundles that match the expected outputs defined in `demo/expected/` |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L2-P1-1 | After a fix is committed, `bobreviewer run --prior-report <earlier-report>` produces a `probe_results` entry that links to the earlier run via `prior_run_id` and `probe_hash` |
| L2-P1-2 | Frozen-suite hash is present in `evidence.json` and changes when a test file changes |

**Demo Scenarios** (all in `demo/sample_project/`; all use `demo-base` as the before ref):

| # | Tag | Name | Setup | Expected result |
|---|---|---|---|---|
| 1 | `demo-rounding-change` | Unintended difference | `discount.py` changes rounding; `invoice.py` caller outside diff; existing tests pass | Probe shows `100.0` → `99.99`; verdict: `unintended` |
| 2 | `demo-tax-update` | Intended difference | Tax rate updated in `pricing.py` | Probe shows expected change; verdict: `intended` with rationale |
| 3 | `demo-refactor` | Behavior-preserving refactor | Internal implementation changed; public function callable under same name | Probe outputs identical; result status: `match`; developer records `intended` |
| 4 | `demo-broken-import` | Inconclusive | Probe target imports a module absent in the base worktree | Result: `inconclusive` with `reason: "import_error"`; no crash |
| 5 | `demo-tax-update-v2` | History lookup | A later change to `pricing.calculate_price` | Earlier approved decision from scenario 2 surfaces as context |

**Verification:** Run each scenario from a clean checkout; diff the produced `evidence.json` against `demo/expected/<scenario>.json`.

---

### Lane 3 — Report Renderer, Static Viewer, and Evidence Map (Dev 3)

**Owns:**
- `evidence.json` → Markdown report (terminal output and PR comment body)
- `evidence.json` → self-contained static HTML report (single file, no network requests, no server)
- Simple caller evidence map embedded in the HTML report (SVG or inline HTML; callers in unchanged files visually and textually distinct — do not use color alone)
- Session-only decision preview in the HTML viewer (clearly labeled "Demo preview — not saved"; no file writes)
- Keyboard accessibility: all interactive elements reachable by keyboard, visible focus indicators
- Readable on mobile viewport (≥ 320 px wide)
- Text labels alongside any color coding
- Pre-publish check: report must contain no local absolute paths and no secrets or tokens

**Acceptance Criteria — P0:**

| ID | Criterion |
|---|---|
| L3-P0-1 | `evidence.json` produces a Markdown report that renders correctly in a GitHub PR comment (headings, tables, code blocks) |
| L3-P0-2 | Static HTML file opens in a browser with no network requests (verified with DevTools) and no server |
| L3-P0-3 | HTML viewer shows: changed function, callers outside the diff with file and line, before/after probe outputs, test results, and any decision record present in the evidence bundle |
| L3-P0-4 | Evidence map shows caller relationships; callers in unchanged files are visually distinct AND carry a text label |
| L3-P0-5 | Session-only decision interactions are labeled "Demo preview — not saved" and do not write files |
| L3-P0-6 | Published HTML contains no local absolute paths and no secrets or tokens |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L3-P1-1 | HTML report links back to the CI run URL present in `evidence.json` |
| L3-P1-2 | All interactive elements are keyboard-accessible with visible focus |
| L3-P1-3 | Layout is usable at 320 px viewport width |

**Verification:** Open the pre-baked HTML from `submission/viewer/` in a browser with network disabled; navigate all sections by keyboard only; resize to 320 px; confirm no broken references.

---

### Lane 4 — Bob Integration, GitHub Actions, and Decisions (Dev 4)

**Owns:**
- Bob IDE workflow: conversational probe authoring (Bob guides the developer to produce a valid probe JSON through chat)
- Bob runs `bobreviewer run` as a subprocess and presents the evidence summary as a Markdown table in chat
- Decision JSON writer: produces the file at `.bobreviewer/decisions/<symbol>-<head_commit_short>.json`
- Decision history lookup: given repository + file path + symbol, finds earlier decisions on the default branch and surfaces them as chat context
- GitHub Actions workflow (`.github/workflows/bobreviewer.yml`): invokes the CLI, uploads `evidence.json` and the static HTML as workflow artifacts, posts or updates a PR comment with the Markdown report
- GitHub Actions secrets guidance and auth configuration

**Approval derivation:** A decision record's `status` field is written as `proposed` by the tool. A decision is treated as `approved` in history lookup only when the file containing it is present in a commit reachable from `HEAD` on the repository's default branch — determined by reading the merged file from the default branch, not by editing the `status` field in the working tree.

**Acceptance Criteria — P0:**

| ID | Criterion |
|---|---|
| L4-P0-1 | A Bob conversation can produce a valid probe JSON file (validates against the probe schema) |
| L4-P0-2 | Bob invokes `bobreviewer run` as a subprocess and presents a Markdown table of changed functions, caller highlights, and probe results in chat |
| L4-P0-3 | Bob writes a decision JSON file from a developer's stated verdict and rationale; `intended` verdict is rejected if rationale is empty |
| L4-P0-4 | History lookup matches on repository + file path + symbol; returns earlier decisions reachable from the default branch |
| L4-P0-5 | A prior approved decision is surfaced as context with explicit text: "This is prior context, not approval of the current change" |
| L4-P0-6 | GitHub Actions workflow posts a PR comment on PR open and updates the same comment on subsequent pushes |
| L4-P0-7 | `evidence.json` and the static HTML are uploaded as named workflow artifacts with a link in the PR comment |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L4-P1-1 | Bob presents a rerun result and annotates which probe cases changed from `differ` to `match` compared to the prior report |
| L4-P1-2 | Fresh-install check: a developer with only `git`, `python`, and `pip` can run `pip install -e .` and then `bobreviewer run` on the sample project successfully |

**Verification:** Open a PR on the demo repo; confirm the Actions workflow posts a comment with a table and an artifact link; follow the artifact link; confirm the HTML opens offline.

---

## Shared Contracts (Lock on Day 1)

Lane 1 coordinates all changes to these schemas. No other lane should produce or consume these structures without referencing the canonical schema files committed under `contracts/`. Required fields are marked `(required)`; enum values are exhaustive.

### `contracts/probe.schema.json`

```json
{
  "schema_version": "1",
  "target": "<fully.qualified.function.name>",
  "cases": [
    {
      "id": "<unique stable string>",
      "args": [],
      "kwargs": {}
    }
  ]
}
```

Required: `schema_version`, `target`, `cases`. Each case requires `id`, `args`, `kwargs`. Case IDs must be unique within a probe file and stable across revisions.

### `contracts/evidence.schema.json`

```json
{
  "schema_version": "1",
  "run_id": "<uuid>",
  "generated_at": "<ISO-8601>",
  "repository": "<remote-origin-url>",
  "base_ref": "<ref-string>",
  "head_ref": "<ref-string>",
  "base_commit": "<full-sha>",
  "head_commit": "<full-sha>",
  "prior_run_id": "<uuid or null>",
  "ci_run_url": "<url or null>",
  "frozen_suite_hash": "<sha256-hex>",
  "analysis_limits": {
    "max_hops": 2,
    "notes": ["<any caveats about incomplete analysis>"]
  },
  "changed_functions": [
    {
      "symbol": "<fully.qualified.name>",
      "file_path": "<repo-relative path>",
      "callers": [
        {
          "symbol": "<fully.qualified.name>",
          "file_path": "<repo-relative path>",
          "line": 42,
          "in_diff": false,
          "resolution": "resolved",
          "needs_probe": true
        }
      ],
      "unknown_references": [
        {
          "file_path": "<repo-relative path>",
          "line": 17,
          "reason": "<why this reference could not be resolved>"
        }
      ]
    }
  ],
  "test_results": {
    "base": {
      "<node_id>": {
        "status": "pass | fail | error",
        "message": "<error message or null>"
      }
    },
    "head": {
      "<node_id>": {
        "status": "pass | fail | error",
        "message": "<error message or null>"
      }
    }
  },
  "probe_results": [
    {
      "probe_file": "<repo-relative path>",
      "probe_hash": "<sha256-hex of probe file bytes>",
      "target": "<fully.qualified.function.name>",
      "prior_difference_run_id": "<uuid or null>",
      "cases": [
        {
          "id": "<stable case id>",
          "args": [],
          "kwargs": {},
          "base_output": "<any JSON value or exception record>",
          "head_output": "<any JSON value or exception record>",
          "status": "match | differ | inconclusive",
          "inconclusive_reason": "<string or null>",
          "base_executed_at": "<ISO-8601>",
          "head_executed_at": "<ISO-8601>"
        }
      ]
    }
  ],
  "decisions": [
    "<array of decision records loaded from .bobreviewer/decisions/ at run time>"
  ]
}
```

Required top-level: `schema_version`, `run_id`, `generated_at`, `repository`, `base_ref`, `head_ref`, `base_commit`, `head_commit`. `status` enum values: `match`, `differ`, `inconclusive`. An exception output is represented as `{"exception": "<ExceptionType>", "message": "<str>"}`.

### `contracts/decision.schema.json`

```json
{
  "schema_version": "1",
  "run_id": "<uuid of the run that produced this decision>",
  "repository": "<remote-origin-url>",
  "file_path": "<repo-relative path to the file containing the changed function>",
  "symbol": "<fully.qualified.function.name>",
  "base_commit": "<full-sha>",
  "head_commit": "<full-sha>",
  "probe_file": "<repo-relative path>",
  "probe_hash": "<sha256-hex>",
  "observed_before": "<any JSON value>",
  "observed_after": "<any JSON value>",
  "verdict": "intended | unintended | unresolved",
  "rationale": "<non-empty string when verdict is intended>",
  "status": "proposed",
  "timestamp": "<ISO-8601>"
}
```

Required: all fields. `verdict` enum: `intended`, `unintended`, `unresolved`. `rationale` must be a non-empty string when `verdict` is `intended`. `status` is always written as `proposed` by the tool; approval is determined by presence on the default branch, not by editing this field.

---

## How the Pieces Connect

```
bobreviewer analyze / run  (Lane 1 CLI)
  │
  ├─► Worktree checkout x2 (Lane 1) ──► isolated subprocess dirs
  │
  ├─► AST diff + combined caller trace (Lane 1) ──► changed_functions[], unknown_references[]
  │
  ├─► Frozen test runner (Lane 2) ──► test_results{}
  │
  ├─► Probe runner + repeated-run check (Lane 2) ──► probe_results[]
  │
  └─► evidence.json  (Lane 1 writes and validates; all lanes read)
          │
          ├─► Markdown report  (Lane 3) ─────────────────────────────┐
          │                                                           │
          ├─► Static HTML viewer + evidence map  (Lane 3)            │
          │                                                           ▼
          │                                           GitHub Actions (Lane 4)
          │                                           ├─► artifact upload
          │                                           └─► PR comment post/update
          │
          └─► Bob chat  (Lane 4)
                  └─► Decision JSON writer/reader  (Lane 4)
                          └─► .bobreviewer/decisions/
```

---

## Integration Milestones

Lanes work in parallel throughout. Milestones define integration checkpoints, not sequential phases. Each lane should have something runnable from day one.

### Milestone 0 — Contracts locked (all lanes unblocked)
*Lane 1 leads; all lanes participate*

- [ ] (L1) Schema files committed under `contracts/`; Python validator module published
- [ ] (L2) Probe runner stub: given a hardcoded probe JSON and a function in the sample project, returns a valid case result dict
- [ ] (L3) HTML template renders a hardcoded evidence JSON correctly in a browser
- [ ] (L4) Decision JSON file written by hand validates against the schema; history lookup stub finds it by symbol

### Milestone 1 — First real comparison (P0 core)
*Lanes 1 and 2 in parallel; Lanes 3 and 4 integrate against real evidence*

- [ ] (L1) `bobreviewer analyze` on scenario 1 produces a valid `evidence.json` with `changed_functions` and callers
- [ ] (L2) `bobreviewer run` on scenario 1 produces probe results showing `100.0 → 99.99` (differ)
- [ ] (L3) HTML viewer renders the scenario 1 `evidence.json` with evidence map
- [ ] (L4) Bob runs `bobreviewer run` as a subprocess and renders a Markdown table from the result

### Milestone 2 — Bob/human decision loop (P0 decisions)
*Lane 4 leads; Lane 1 and Lane 3 verify contract compliance*

- [ ] (L4) Bob guides probe authoring for an uncovered caller; probe file validates against schema
- [ ] (L4) Bob writes a decision JSON from a stated verdict and rationale
- [ ] (L4) History lookup finds the merged decision for scenario 2 and surfaces it with the required context disclaimer
- [ ] (L1) Rerun with `--prior-report` links result to earlier difference by `prior_run_id` + `probe_hash`

### Milestone 3 — CI and viewer complete (P0 delivery)
*Lanes 3 and 4 in parallel*

- [ ] (L3) Pre-baked static HTML passes the offline/no-network test and the accessibility checks
- [ ] (L3) Published HTML contains no absolute local paths and no secrets
- [ ] (L4) GitHub Actions posts PR comment with table and artifact link
- [ ] (L2) All five demo scenarios pass their expected-output checks

### Milestone 4 — Recording and submission
*All lanes*

- [ ] End-to-end demo walkthrough produces no errors
- [ ] `submission/` directory populated per the artifact table
- [ ] Demo recorded (terminal + browser)
- [ ] Fresh-install check passes: `git clone` → `pip install -e .` → `bobreviewer run` on sample project

---

## Demo Script

**Setup:** `demo/sample_project/` contains a small Python package (`discount.py`, `invoice.py`, `pricing.py`) and pytest tests. All before refs use the immutable tag `demo-base`. All scenario tags are committed before the demo.

### Act 1 — Unintended difference

1. `bobreviewer run --before demo-base --after demo-rounding-change`
2. Output: `discount.apply_discount` changed; `invoice.calculate_invoice` caller in unchanged file (with file/line)
3. Evidence map shows the connection; tests: all pass on both sides
4. `invoice.calculate_invoice` has no probe → Bob guides probe authoring; developer reviews and commits `probes/invoice_basic.json`
5. `bobreviewer run --before demo-base --after demo-rounding-change --probe probes/invoice_basic.json`
6. Report: before `100.0`, after `99.99` — **differ**
7. Developer states `unintended`; writes rationale; Bob drafts a fix; developer commits the fix as `demo-rounding-fix`
8. `bobreviewer run --before demo-base --after demo-rounding-fix --probe probes/invoice_basic.json --prior-report <earlier evidence.json path>`
9. Report: before `100.0`, after `100.0` — **match**; result linked to earlier difference record via `prior_run_id`

### Act 2 — Intended difference

1. `bobreviewer run --before demo-base --after demo-tax-update`
2. Probe shows expected output change in `pricing.calculate_price`
3. Developer states `intended`; writes rationale explaining the policy change; Bob writes decision JSON
4. Decision file committed to `.bobreviewer/decisions/`; merged to default branch → record is now `approved` in history lookup

### Act 3 — Behavior-preserving refactor

1. `bobreviewer run --before demo-base --after demo-refactor`
2. Public function callable under same name; same probe runs on both sides
3. Report: all probe cases **match**
4. Developer states `intended`; reviewer understands: outputs match for these inputs; broader correctness is not claimed

### Act 4 — Inconclusive

1. `bobreviewer run --before demo-base --after demo-broken-import`
2. Probe target imports a module absent in the base worktree
3. Report: **inconclusive** — `reason: "import_error"` — verbatim error message quoted
4. No crash; report explains the limitation

### Act 5 — History lookup

1. `bobreviewer run --before demo-base --after demo-tax-update-v2` (a later change to `pricing.calculate_price`)
2. Tool loads the earlier decision for `pricing.calculate_price` from Act 2 (matched by repository + file path + symbol)
3. Report surfaces: "Prior decision found: intended — [rationale text]. This is prior context, not approval of the current change."
4. Reviewer understands the earlier policy choice; the new change still requires independent review

---

## Submission Artifacts

Collect as you go — do not leave this to the last day:

| Artifact | Owner | Where |
|---|---|---|
| Bob task summaries (one per lane, per milestone) | Each dev | `submission/task-summaries/` |
| Real `evidence.json` from Act 1 (initial run) | Lane 2 | `submission/evidence/act1-initial.json` |
| Real `evidence.json` from Act 1 (rerun after fix) | Lane 2 | `submission/evidence/act1-rerun.json` |
| Decision JSON from Acts 1 and 2 | Lane 4 | `submission/decisions/` |
| Static HTML viewer pre-baked from Act 1 rerun | Lane 3 | `submission/viewer/` |
| Screen recording of the demo script | Any | `submission/demo/` |
| README describing how to reproduce | Lane 1 | `submission/README.md` |

---

## Non-Goals (Explicit)

- Proving a change is safe — the tool reports what it observed on the probed cases; it does not certify broader correctness
- Resolving dynamic dispatch (`getattr`, metaclasses, framework magic)
- Multi-language support
- Whole-repository call graph
- Autonomous code repair
- Persistent state in the web viewer
- External service dependencies in any demo scenario
- Editing `status: proposed` in a decision file to mark it approved — approval is derived from presence on the default branch
