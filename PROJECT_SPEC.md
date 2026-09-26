# bobthereviewer — Project Specification

## What We Are Building

**bobthereviewer** is a developer tool that answers three questions about a code change:

1. **What else might this change affect?** — Find functions that changed and trace their direct callers up to two hops, highlighting callers in files that were not themselves modified.
2. **Does it actually behave differently?** — Run the same frozen test suite and the same probe bytes against both the before and after revisions and show inputs and outputs side by side.
3. **Was that difference intentional?** — Let the developer record a JSON decision (intended / unintended / unresolved) with a rationale, then surface earlier approved decisions as context in future reviews without using them as automatic approval.

The tool is designed to catch what code review and passing tests can miss: a small, locally-correct change that silently shifts behavior in a caller that was never touched.

It runs from the terminal, works inside Bob IDE through ordinary CLI invocation, and posts findings to a GitHub pull request as a Markdown comment via GitHub Actions. A developer on their own project can set it up with `bobreviewer init`, check readiness with `bobreviewer doctor`, and browse past reviews locally with `bobreviewer ui`. Judges can explore a real report in a fully static HTML page without installing anything.

---

## What We Are Leaving Out

- Multi-language support — Python only for this version
- Whole-repository call graph — two-hop caller tracing on the changed functions only; whole-repo map is optional/stretch
- Autonomous code fixing — Bob helps draft a fix; the developer commits and reruns
- Database or backend — all persistent state is files in the repository; local run history is plain JSON files
- Dynamic dispatch resolution — calls through `getattr`, decorators, or frameworks are marked `unknown`
- External service dependencies in demo scenarios — all demo scenarios are fully reproducible offline
- Proving a change is safe — the tool reports what it observed; it does not certify correctness
- Hosted execution service — the local UI is a local-only server bound to localhost; it does not run on behalf of remote users
- Automatic staging, committing, or approving — the tool writes files and prints suggested git commands; the developer runs them

---

## Core Concepts

### Revisions

The user supplies two explicit Git refs on the CLI (`--before REF --after REF`). Defaults can be suggested by the tool based on project config (see `bobreviewer run`). **Demo scenarios use a stable immutable tag (`demo-base`) as the before ref so runs are reproducible regardless of branch movement.** The tool checks out each ref into a separate temporary Git worktree and runs all execution inside isolated subprocesses. The two revisions never share a process. After execution the worktrees are cleaned up, and the developer's checkout, index, working branch, and uncommitted files are left exactly as they were — including when execution fails. **Uncommitted edits are never reviewed**; if the working tree is dirty, the tool informs the user which files are uncommitted and what to do.

### Probes

A probe is a committed JSON file under `.bobreviewer/probes/` (canonical location) or `probes/` (legacy root-level location; both work). It describes a target function and a fixed set of inputs. The shared probe runner (part of the tool, outside the target project's code) loads the target function from the worktree subprocess and calls it with the supplied arguments. It captures the return value (any JSON-representable value: number, string, boolean, null, list, or object) or a structured exception record, and writes a result entry. The same committed probe bytes run against both revisions — a probe cannot change between sides. Probe and case IDs are stable identifiers used to link results across runs.

**Probe selection rule:** The frozen set is all probes present in the base revision plus any probes added in the head revision. If a probe file was edited or deleted in the head revision, the base version of that file is used on both sides.

### Tests

Existing pytest tests run as a separate evidence stream alongside probes. The frozen test suite is the set of test files present in the base revision, run with the base `pytest.ini` / `pyproject.toml` test configuration. New test files added in the head revision do not run in this frozen suite. Test results are captured as `pass`, `fail`, or `error` per node ID. Existing failures on the base revision remain visible — they are not hidden. A matching exception across both sides is not a passing test; it is recorded as `error` on both.

### Change Triage

Before executing tests and probes, the tool classifies the diff into one of these categories:

| Category | Description |
|---|---|
| `docs-only` | Every changed file is documentation (`.md`, `.rst`, `.txt`) or a comment-only Python change; no imports or logic changed |
| `tests-only` | Every changed file is a test file; no production code changed |
| `config-deps` | Changed files include package manifests, lock files, CI configuration, or environment files |
| `no-semantic-change` | Changed lines are whitespace, formatting, or type annotations only |
| `code` | Any other change, including newly added probe files or unknown file types |

**Execution rules:**
- `docs-only`: tests and probes are **skipped by default**; report explicitly states what was skipped and why; `--full` forces execution
- `tests-only`, `config-deps`, `no-semantic-change`, `code`, unknown file types: always take the normal execution path
- A diff that contains both docs and code changes is classified as `code`
- Newly added probes are never grounds for skipping — they always run

The report must say what was skipped and why. A skipped execution must never appear as "passed."

### Impact Analysis

The tool parses ASTs from **both revisions** and inspects all other repository files to find callers outside the diff. Call relationships from both sides are combined so that removed calls are not missed. An import statement alone does not establish that one function calls another — there must be a resolved call site in the AST. Callers in files that were not part of the diff are highlighted. Dynamic or unresolved references are surfaced in a separate `unknown_references` list with a reason for each. The caller entry includes the file path and line number of the call site.

### Evidence Bundle

After analysis and execution, the tool writes a single `evidence.json` file to `.bobreviewer/runs/<run_id>/evidence.json`. This is the handoff between all four lanes and the single source of truth for the report, the Bob workflow, the GitHub comment, and the local UI. The report, viewer, Bob, and the local server all read the same file — they do not implement their own parsing of git or probe output.

### Saved Runs

Completed runs are stored under `.bobreviewer/runs/` (one directory per `run_id`). This directory is git-ignored; it is local to the developer's machine and is never committed. Each run directory contains `evidence.json` and optionally a pre-rendered `report.html`. The local UI browses these saved runs.

### Project Config

`bobreviewer init` creates `.bobreviewer/config.json` in the target repository. This file is committed. It records the project's base branch, test folder, Python environment command, and optional preferences. Running `init` again preserves existing settings and modes; it only fills in fields that are absent.

### Decision Records

A decision is a JSON file written into the repository under `.bobreviewer/decisions/`. It starts as `proposed` when written during development. The team's review and merge of the branch is what makes it `approved` — an approved decision is one that has been merged to the default branch and is present in a commit reachable from `HEAD` on that branch (determined by `git show <default-branch>:.bobreviewer/decisions/<file>`, not by editing the `status` field in the working tree). A matching historical decision surfaces as context in a future review but never automatically approves a new change. **History matching uses repository + file path + symbol together — function name alone is not sufficient.** An `intended` verdict requires a non-empty human rationale. The tool writes the decision file, prints the file path, and prints a suggested `git add / git commit` command. It never stages or commits anything.

---

## Command Interface

All subcommands return exit code `0` on successful completion (including inconclusive and skipped results), non-zero on hard failure (unreadable ref, broken worktree setup, schema validation error, dirty working tree on `run`).

```
bobreviewer init [--repo-dir DIR]
```
One-time setup for a target repository. Detects the base branch, test folder, and Python environment. Writes `.bobreviewer/config.json` if absent; preserves existing values if present. Optionally adds `.bobreviewer/` to `.gitignore` for the `runs/` subdirectory, installs the Bob workflow file, and generates the project's GitHub Actions workflow from the Action template. Prints a summary of what was created and what was skipped.

```
bobreviewer doctor [--repo-dir DIR]
```
Checks readiness: git availability, Python version, test runner detection, config presence, probe file validity. Prints a structured report of what is ready, what is missing, and what to do next. Does not install anything, run tests, or modify any file.

```
bobreviewer analyze --before REF --after REF [--output DIR] [--repo-dir DIR]
```
Analysis-only run. Classifies the diff (triage), computes the impact map (changed functions and callers). Writes `evidence.json` with `changed_functions` and `triage` populated but `test_results` and `probe_results` empty. Does not execute any code.

```
bobreviewer run [--before REF] [--after REF] [--probe FILE ...] [--prior-report FILE] [--full] [--open] [--output DIR] [--repo-dir DIR]
```
Full run. Performs triage, analysis, runs the frozen test suite, and runs probes. `--before` and `--after` default to values derived from `config.json` (base branch and `HEAD`) when not supplied; the tool prints the resolved refs before starting and notes that uncommitted edits are not included. `--probe FILE` accepts a repo-relative path to a committed probe file; the file must exist in the repository index. Multiple `--probe` flags are accepted. `--prior-report FILE` is a path to an earlier `evidence.json`; the new run links rerun probe results to earlier difference records by `run_id` and `probe_hash`. `--full` forces execution even for `docs-only` diffs. `--open` opens the result in the default browser after the run completes. Saves the completed run to `.bobreviewer/runs/<run_id>/`. Writes a complete `evidence.json`.

```
bobreviewer decide --run-id ID --symbol SYMBOL --case-id ID --verdict VERDICT --rationale TEXT [--repo-dir DIR]
```
Writes a decision JSON file for a specific probe case result in a saved run. Validates the verdict and rationale, reads the observed values from the saved `evidence.json`, writes `.bobreviewer/decisions/<symbol>-<head_commit_short>.json`, and prints the file path plus a suggested git command. Rejects `intended` with an empty rationale. Never stages, commits, or modifies any file other than the decision JSON.

```
bobreviewer ui [--port PORT] [--repo-dir DIR]
```
Starts the local developer UI server. Binds exclusively to `localhost`. Generates a per-launch random token; all API calls must include this token as a bearer token or query parameter. Prints the URL and token to the terminal. Serves the same pre-built frontend assets as the static judge page (shipped with the Python package). Stops when the terminal process is killed; does not run as a daemon.

---

## Four-Person Ownership

Work is designed to proceed in parallel. The critical path is: **shared contracts** → **first real comparison** → **Bob/human decision loop** → **CI, viewer, and local UI** → **recording**. All four lanes can work simultaneously after contracts are locked; integration points are the evidence JSON, the decision JSON, and the local server API.

### Lane 1 — Contracts, Triage, Setup, CLI Wiring, and Package (Dev 1)

**Owns:**
- Shared contracts: probe JSON schema, evidence JSON schema, decision JSON schema, config JSON schema, local server API contract — Lane 1 coordinates all schema and API changes; no other lane changes these without Lane 1 review
- Git worktree creation and teardown for both revisions; guarantee developer environment is unchanged after any exit path
- AST-based changed-function finder using both revision ASTs; combined caller tracer (two hops, resolved call sites only); separate `unknown_references` list with reasons
- Change triage classifier; execution skip logic for `docs-only`; report annotation for skipped executions
- `bobreviewer init` and `bobreviewer doctor` commands
- CLI entry points for all commands (`init`, `doctor`, `analyze`, `run`, `decide`, `ui`); wiring each command to its owning lane's function
- Writing and schema-validating `evidence.json`; saving runs to `.bobreviewer/runs/`
- Python package declarations: `pyproject.toml`, entry points, bundled frontend assets and probe runner, package build and version pinning; CI staleness check for bundled assets

**Acceptance Criteria — P0 (must ship):**

| ID | Criterion |
|---|---|
| L1-P0-1 | `bobreviewer analyze --before demo-base --after HEAD` prints changed functions and their callers with file and line locations to stdout |
| L1-P0-2 | Callers in unchanged files are flagged; unresolved/dynamic references appear in a separate `unknown_references` list with a reason string |
| L1-P0-3 | Two temporary worktrees are created, populated, and removed; the developer's working tree, index, and branch are unchanged after both normal exit and failure exit |
| L1-P0-4 | `evidence.json` validates against the agreed schema; all required fields are present and enum values are valid |
| L1-P0-5 | CLI returns exit code 0 on analysis and run success and non-zero on hard failure; inconclusive and skipped results do not count as hard failures |
| L1-P0-6 | Removed call sites from the base revision appear in the combined caller list, not silently dropped |
| L1-P0-7 | `bobreviewer init` creates `.bobreviewer/config.json` with detected values; re-running `init` preserves all existing fields |
| L1-P0-8 | `bobreviewer doctor` prints a structured readiness report; it does not install, run, or write anything |
| L1-P0-9 | A `docs-only` diff skips tests and probes by default; the report states what was skipped and why; `--full` forces execution |
| L1-P0-10 | A diff containing any non-docs changed file is classified `code` and takes the normal execution path regardless of other files |
| L1-P0-11 | Running `bobreviewer run` on a repository with uncommitted edits prints a clear message identifying the dirty files and exits non-zero |

**Acceptance Criteria — P1 (should ship):**

| ID | Criterion |
|---|---|
| L1-P1-1 | `--prior-report FILE` is accepted and the supplied run ID is written into the new `evidence.json` for linking |
| L1-P1-2 | Schema validation failure on `evidence.json` write produces a human-readable error, not a Python traceback |
| L1-P1-3 | `pip install bobthereviewer` followed by `bobreviewer init` and `bobreviewer run` on the sample project completes without requiring Node or any build step |
| L1-P1-4 | CI fails if the bundled frontend assets in the Python package are older than the source assets in `frontend/` |

**Verification:** Run `bobreviewer analyze --before demo-base --after demo-rounding-change` on the sample project; confirm `discount.apply_discount` appears as changed and `invoice.calculate_invoice` appears as a caller in an unchanged file with a file/line reference.

---

### Lane 2 — Executor, Progress, Saved Runs, and Local API (Dev 2)

**Owns:**
- Subprocess-isolated pytest runner (frozen base test suite and config; both worktrees; identical invocation)
- Probe runner (shared Python runner outside target code; any JSON value output; structured exception capture)
- Inconclusive classification: import error and missing dependency → `inconclusive`; legitimate raised exception → `exception` (not `inconclusive`); nondeterminism detected by repeated run → `inconclusive`
- Repeated-run check: probes run twice on each side; if outputs differ between the two runs on the same revision, mark `inconclusive` with reason `nondeterminism_detected`
- Frozen probe selection logic (base probes + new head probes; base version of edited/deleted probes)
- Result schema population: before/after output pairs; exception details; inconclusive reasons; execution timestamps
- Frozen-suite hash in `evidence.json` (SHA-256 of the sorted list of frozen test file paths and their contents)
- Real-time progress stream: structured events emitted to stdout during a run (see Progress Event Contract); the local UI and terminal both consume this stream
- Saving completed runs to `.bobreviewer/runs/<run_id>/`; serving the saved run list and individual run data via the local server API
- Local server API endpoints for runs (list, get, start new run, stream progress); the decision-save endpoint delegates to Lane 4's shared decision validation service
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
| L2-P0-9 | The local server binds only to `localhost`; requests without the per-launch token are rejected with HTTP 401 |
| L2-P0-10 | The runs list API returns all saved run IDs and their metadata; the run detail API returns the full `evidence.json` for a given run ID |
| L2-P0-11 | Progress events are emitted during a run; the terminal and the local UI both show which step is running |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L2-P1-1 | After a fix is committed, `bobreviewer run --prior-report <earlier-report>` produces a `probe_results` entry that links to the earlier run via `prior_run_id` and `probe_hash` |
| L2-P1-2 | Frozen-suite hash is present in `evidence.json` and changes when a test file changes |
| L2-P1-3 | The server rejects requests with a `Host` header that is not `localhost` or `127.0.0.1` |
| L2-P1-4 | The server rejects `run_id` and file path parameters that contain path traversal sequences |

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

### Lane 3 — Report Renderer, Both Browser Modes, and Frontend Packaging (Dev 3)

**Owns:**
- `evidence.json` → Markdown report (terminal output and PR comment body)
- `evidence.json` → self-contained static HTML report (single file, no network requests, no server) — the **judge/public page**
- Local developer UI frontend (browser application served by the Lane 2 local server) — the **developer page**
- Both browser modes share the same evidence display component; they differ in whether the decision-save and run-start controls are present
- Simple caller evidence map embedded in both browser views (SVG or inline HTML; callers in unchanged files visually and textually distinct — do not use color alone)
- Judge page: session-only decision preview clearly labeled "Demo preview — not saved"; no API calls; no file writes
- Developer page: browsable run history; ref selector to start a new run; real-time progress display; Save Decision button (calls the `POST /decide` API endpoint owned by Lane 2, which delegates to Lane 4's decision validation service); links to CI run artifacts
- Keyboard accessibility: all interactive elements reachable by keyboard, visible focus indicators
- Readable on mobile viewport (≥ 320 px wide)
- Text labels alongside any color coding
- Pre-publish check: static report must contain no local absolute paths and no secrets or tokens
- Frontend build: produce a single distributable bundle (no Node required at install time); the bundle is committed to `src/bobthereviewer/frontend/` and shipped with the Python package; build is run by the developer and checked in CI for staleness

**Acceptance Criteria — P0:**

| ID | Criterion |
|---|---|
| L3-P0-1 | `evidence.json` produces a Markdown report that renders correctly in a GitHub PR comment (headings, tables, code blocks) |
| L3-P0-2 | Static judge HTML file opens in a browser with no network requests (verified with DevTools) and no server |
| L3-P0-3 | Both browser views show: changed function, callers outside the diff with file and line, before/after probe outputs, test results, and any decision record present in the evidence bundle |
| L3-P0-4 | Evidence map shows caller relationships; callers in unchanged files are visually distinct AND carry a text label |
| L3-P0-5 | Judge page decision interactions are labeled "Demo preview — not saved" and make no API calls |
| L3-P0-6 | Published static HTML contains no local absolute paths and no secrets or tokens |
| L3-P0-7 | Developer page displays the list of saved runs and lets the user open an individual run's evidence |
| L3-P0-8 | Developer page shows real-time progress events during an active run |
| L3-P0-9 | Developer page Save Decision button calls the local server API; a success response writes the decision file and shows the suggested git command |
| L3-P0-10 | The frontend bundle is pre-built and committed; opening the developer UI does not require Node on the end user's machine |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L3-P1-1 | HTML report links back to the CI run URL present in `evidence.json` |
| L3-P1-2 | All interactive elements are keyboard-accessible with visible focus |
| L3-P1-3 | Layout is usable at 320 px viewport width |
| L3-P1-4 | Developer page ref selector validates that the entered refs exist before starting a run |

**Verification:** Open the pre-baked judge HTML from `submission/viewer/` in a browser with network disabled; navigate all sections by keyboard only; resize to 320 px; confirm no broken references. Then start `bobreviewer ui`, open the developer page, browse to the saved Act 1 run, and confirm the evidence display matches the static page.

---

### Lane 4 — Decision Logic, Bob Instructions, Action Templates, and CI (Dev 4)

**Owns:**
- Shared decision validation service: a Python function (not a server) that accepts verdict, rationale, and observed values; validates them against the decision schema; returns either a validated decision dict or a structured error; used by both the `bobreviewer decide` CLI command and the local server's `POST /decide` endpoint
- Decision JSON writer: called by `bobreviewer decide`; writes the file at `.bobreviewer/decisions/<symbol>-<head_commit_short>.json`; prints file path and suggested git command
- Decision history lookup: `git show <default-branch>:.bobreviewer/decisions/<file>` for all files matching repository + file path + symbol; returns earlier approved decisions as structured data; used by `bobreviewer run` evidence assembly and Bob chat
- Bob IDE workflow: Bob instructions for conversational probe authoring, `bobreviewer run` invocation (as a subprocess), Markdown table rendering of results, and guided decision recording
- GitHub Actions Action template: a reusable Action that installs a specified version of bobthereviewer and the target project's dependencies, runs `bobreviewer run`, uploads artifacts, and posts or updates a PR comment; designed to work in any Python project, not just our own demo
- CI check: workflow step that verifies the bundled frontend assets are not stale compared to `frontend/` source

**Approval derivation:** A decision record's `status` field is always written as `proposed` by the tool. A decision is treated as `approved` in history lookup only when its file is present in a commit reachable from `HEAD` on the repository's default branch — determined by `git show <default-branch>:.bobreviewer/decisions/<file>`.

**Acceptance Criteria — P0:**

| ID | Criterion |
|---|---|
| L4-P0-1 | A Bob conversation can produce a valid probe JSON file (validates against the probe schema) |
| L4-P0-2 | Bob invokes `bobreviewer run` as a subprocess and presents a Markdown table of changed functions, caller highlights, and probe results in chat |
| L4-P0-3 | The decision validation service rejects an `intended` verdict with an empty rationale and returns a structured error |
| L4-P0-4 | `bobreviewer decide` writes a valid decision JSON, prints the file path, and prints a suggested git command; it does not stage or commit anything |
| L4-P0-5 | History lookup matches on repository + file path + symbol; returns earlier decisions reachable from the default branch |
| L4-P0-6 | A prior approved decision is surfaced as context with explicit text: "This is prior context, not approval of the current change" |
| L4-P0-7 | The GitHub Actions template installs a pinned version of bobthereviewer, runs the target project's dependency install, runs `bobreviewer run`, and uploads `evidence.json` and the static HTML as named artifacts |
| L4-P0-8 | The GitHub Actions template posts a PR comment on PR open and updates the same comment on subsequent pushes |

**Acceptance Criteria — P1:**

| ID | Criterion |
|---|---|
| L4-P1-1 | Bob presents a rerun result and annotates which probe cases changed from `differ` to `match` compared to the prior report |
| L4-P1-2 | Fresh-install check: a developer with only `git`, `python`, and `pip` can run `pip install bobthereviewer`, `bobreviewer init`, and `bobreviewer run` on the sample project successfully |
| L4-P1-3 | CI staleness check fails when `frontend/` source is newer than the committed bundle in `src/bobthereviewer/frontend/` |

**Verification:** Open a PR on the demo repo; confirm the Actions workflow posts a comment with a table and an artifact link; follow the artifact link; confirm the judge HTML opens offline.

---

## Shared Contracts (Lock on Day 1)

Lane 1 coordinates all changes to these schemas. No other lane should produce or consume these structures without referencing the canonical schema files committed under `contracts/`. Required fields are noted; enum values are exhaustive. The local server API contract is also defined here; Lane 2 implements it and Lane 3 consumes it.

### `contracts/config.schema.json`

```json
{
  "schema_version": "1",
  "base_branch": "<default branch name, e.g. main>",
  "test_dir": "<repo-relative path to test folder>",
  "python_env": "<command to run python, e.g. python or .venv/bin/python>",
  "probe_dir": "<repo-relative path to probe folder, defaults to .bobreviewer/probes>"
}
```

Required: `schema_version`, `base_branch`. All other fields have defaults. `init` preserves any fields already present.

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
  "triage": {
    "category": "docs-only | tests-only | config-deps | no-semantic-change | code",
    "skipped": true,
    "skip_reason": "<human-readable string or null>"
  },
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

Required top-level: `schema_version`, `run_id`, `generated_at`, `repository`, `base_ref`, `head_ref`, `base_commit`, `head_commit`. `triage.category` enum: `docs-only`, `tests-only`, `config-deps`, `no-semantic-change`, `code`. Case `status` enum: `match`, `differ`, `inconclusive`. An exception output is `{"exception": "<ExceptionType>", "message": "<str>"}`.

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

### `contracts/local-server-api.md`

The local server API is HTTP/1.1 on `localhost` only. All endpoints require `Authorization: Bearer <token>` or `?token=<token>`. The token is generated per launch and printed to the terminal. All responses are JSON.

**Security constraints (all required):**
- Bind address: `127.0.0.1` only
- `Host` header must be `localhost` or `127.0.0.1`; all other values → HTTP 403
- `run_id` parameters: UUID format only; path traversal sequences → HTTP 400
- File path parameters: repo-relative paths only; absolute paths and `..` sequences → HTTP 400

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/runs` | List saved runs. Returns `[{run_id, generated_at, base_ref, head_ref, triage_category}]` |
| `GET` | `/api/runs/{run_id}` | Return full `evidence.json` for the given run ID |
| `POST` | `/api/runs` | Start a new run. Body: `{before_ref, after_ref, probes: [], prior_run_id?}`. Returns `{run_id}` immediately; progress via SSE |
| `GET` | `/api/runs/{run_id}/progress` | Server-Sent Events stream of progress events for an active or completed run |
| `POST` | `/api/decide` | Save a decision. Body: `{run_id, symbol, case_id, verdict, rationale}`. Delegates to Lane 4's decision validation service. On success: `{file_path, git_command}`. On validation error: HTTP 422 with structured error |
| `GET` | `/` | Serve the developer UI frontend (static assets shipped with the package) |

### Progress Event Contract

Progress events are emitted as newline-delimited JSON to stdout during a CLI run and as Server-Sent Events from the `/api/runs/{run_id}/progress` endpoint. Each event has the shape:

```json
{
  "run_id": "<uuid>",
  "step": "triage | analyze | test_base | test_head | probe_base | probe_head | done | error",
  "status": "started | completed | failed",
  "message": "<human-readable string>",
  "timestamp": "<ISO-8601>"
}
```

---

## How the Pieces Connect

```
bobreviewer init / doctor  (Lane 1)
  └─► .bobreviewer/config.json

bobreviewer analyze / run  (Lane 1 CLI)
  │
  ├─► Triage classifier (Lane 1) ──► triage{}
  │
  ├─► Worktree checkout x2 (Lane 1) ──► isolated subprocess dirs
  │
  ├─► AST diff + combined caller trace (Lane 1) ──► changed_functions[], unknown_references[]
  │
  ├─► Frozen test runner (Lane 2) ──► test_results{}
  │
  ├─► Probe runner + repeated-run check (Lane 2) ──► probe_results[]
  │
  └─► evidence.json  (Lane 1 writes and validates)
          │  saved to .bobreviewer/runs/<run_id>/
          │
          ├─► Markdown report  (Lane 3)  ─────────────────────────────────┐
          │                                                                │
          ├─► Static judge HTML  (Lane 3)                                 │
          │                                                                ▼
          ├─► Local server (Lane 2) ──► Developer UI (Lane 3)    GitHub Actions (Lane 4)
          │      │                                                ├─► artifact upload
          │      └─► POST /decide ──► Decision validation         └─► PR comment update
          │                           service (Lane 4)
          │                               └─► .bobreviewer/decisions/
          │
          └─► Bob chat  (Lane 4)
                  └─► Decision validation service (Lane 4)
                          └─► .bobreviewer/decisions/

bobreviewer decide  (Lane 1 CLI ──► Lane 4 validation service ──► decision file)
bobreviewer ui      (Lane 1 CLI ──► Lane 2 server ──► Lane 3 frontend)
```

---

## Integration Milestones

Lanes work in parallel throughout. Milestones define integration checkpoints, not sequential phases. Each lane should have something runnable from day one. Agree on the local server API contract before the frontend and server are built independently (part of Milestone 0).

### Milestone 0 — Contracts locked (all lanes unblocked)
*Lane 1 leads; all lanes participate*

- [ ] (L1) Schema files committed under `contracts/`; Python validator module published; local server API contract written and agreed
- [ ] (L1) `bobreviewer init` creates a valid `config.json` on the sample project; `bobreviewer doctor` runs and prints a readiness report
- [ ] (L2) Probe runner stub: given a hardcoded probe JSON and a function in the sample project, returns a valid case result dict
- [ ] (L3) Judge HTML template renders a hardcoded evidence JSON correctly in a browser with no network requests; developer UI shell renders the same evidence via a hardcoded local server response
- [ ] (L4) Decision JSON file written by hand validates against the schema; decision validation service rejects empty rationale for `intended`

### Milestone 1 — First real comparison (P0 core)
*Lanes 1 and 2 in parallel; Lanes 3 and 4 integrate against real evidence*

- [ ] (L1) `bobreviewer analyze` on scenario 1 produces a valid `evidence.json` with `changed_functions`, callers, and triage category
- [ ] (L2) `bobreviewer run` on scenario 1 produces probe results showing `100.0 → 99.99` (differ); run saved to `.bobreviewer/runs/`
- [ ] (L3) Judge HTML renders the scenario 1 `evidence.json` with evidence map; developer UI fetches and renders the same run from the local server
- [ ] (L4) Bob runs `bobreviewer run` as a subprocess and renders a Markdown table from the result

### Milestone 2 — Decision loop (P0 decisions)
*Lane 4 leads; Lanes 1, 2, and 3 integrate*

- [ ] (L4) Bob guides probe authoring for an uncovered caller; probe file validates against schema
- [ ] (L4) `bobreviewer decide` writes a valid decision JSON, prints file path and git command, rejects empty rationale
- [ ] (L4) History lookup finds the merged decision for scenario 2 and surfaces it with the required context disclaimer
- [ ] (L1) Rerun with `--prior-report` links result to earlier difference by `prior_run_id` + `probe_hash`
- [ ] (L2) `POST /decide` on the local server calls the validation service and returns `{file_path, git_command}` on success
- [ ] (L3) Developer UI Save Decision button calls `POST /decide`; success shows the file path and git command

### Milestone 3 — CI, full UI, and packaging (P0 delivery)
*All lanes in parallel*

- [ ] (L3) Pre-baked judge HTML passes the offline/no-network test and the accessibility checks; no secrets or absolute paths
- [ ] (L3) Frontend bundle built and committed to `src/bobthereviewer/frontend/`
- [ ] (L4) GitHub Actions template installs bobthereviewer, runs the sample project, posts PR comment, uploads artifacts
- [ ] (L2) All five demo scenarios pass their expected-output checks
- [ ] (L2) Local server security checks pass: wrong-host rejected, path traversal rejected, missing token rejected
- [ ] (L1) `pip install -e .` followed by `bobreviewer run` on sample project completes without Node

### Milestone 4 — Recording and submission
*All lanes*

- [ ] End-to-end demo walkthrough produces no errors
- [ ] `submission/` directory populated per the artifact table
- [ ] Demo recorded (terminal + browser)
- [ ] Fresh-install check passes: `git clone` → `pip install bobthereviewer` → `bobreviewer init` → `bobreviewer run`

---

## Demo Script

**Setup:** `demo/sample_project/` contains a small Python package (`discount.py`, `invoice.py`, `pricing.py`) and pytest tests. All before refs use the immutable tag `demo-base`. All scenario tags are committed before the demo.

### Act 1 — Unintended difference

1. `bobreviewer run --before demo-base --after demo-rounding-change`
2. Output: triage: `code`; `discount.apply_discount` changed; `invoice.calculate_invoice` caller in unchanged file (with file/line)
3. Evidence map shows the connection; tests: all pass on both sides
4. `invoice.calculate_invoice` has no probe → Bob guides probe authoring; developer reviews and commits `.bobreviewer/probes/invoice_basic.json`
5. `bobreviewer run --before demo-base --after demo-rounding-change --probe .bobreviewer/probes/invoice_basic.json`
6. Report: before `100.0`, after `99.99` — **differ**
7. Developer states `unintended`; writes rationale; Bob drafts a fix; developer commits the fix as `demo-rounding-fix`
8. `bobreviewer run --before demo-base --after demo-rounding-fix --probe .bobreviewer/probes/invoice_basic.json --prior-report <earlier run path>`
9. Report: before `100.0`, after `100.0` — **match**; result linked to earlier difference record via `prior_run_id`

### Act 2 — Intended difference

1. `bobreviewer run --before demo-base --after demo-tax-update`
2. Probe shows expected output change in `pricing.calculate_price`
3. Developer states `intended`; writes rationale explaining the policy change; Bob writes decision JSON via `bobreviewer decide`
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
| Static judge HTML pre-baked from Act 1 rerun | Lane 3 | `submission/viewer/` |
| Screen recording of the demo script | Any | `submission/demo/` |
| README describing how to reproduce | Lane 1 | `submission/README.md` |

---

## Non-Goals (Explicit)

- Proving a change is safe — the tool reports what it observed on the probed cases; it does not certify broader correctness
- Resolving dynamic dispatch (`getattr`, metaclasses, framework magic)
- Multi-language support
- Whole-repository call graph (optional/stretch only)
- Autonomous code repair
- Persistent state in the judge/public web viewer
- External service dependencies in any demo scenario
- Editing `status: proposed` in a decision file to mark it approved — approval is derived from presence on the default branch
- Hosted execution service — the local server runs only on the developer's own machine and is not accessible to remote users
- Automatic staging, committing, or merging of any file — the tool prints suggested commands; the developer executes them
