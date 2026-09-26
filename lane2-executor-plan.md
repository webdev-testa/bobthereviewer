# Lane 2 — Executor, Progress, Saved Runs, and Local API: Implementation Plan

## Top-Level Overview

Lane 2 owns the execution layer of bobthereviewer: running frozen tests and probe inputs against two isolated worktree checkouts, capturing structured observations, streaming real-time progress, persisting completed runs, and serving a localhost-only API that the developer UI and the `bobreviewer decide` command consume.

The work starts from a clean repo (no code yet). The first deliverable is a single-case probe runner demonstrating the rounding-change scenario (before: `100.0`, after: `99.99`). Five demo scenarios, progress events, the saved-run store, and the local API follow. The runner coordinates with Lane 1's contracts exclusively and does not define its own output schema.

**Scope boundary:**
- Lane 2 produces `probe_results[]`, `test_results{}`, `frozen_suite_hash`, and progress events.
- Lane 1 owns writing and schema-validating `evidence.json` during CLI runs; Lane 2 writes `evidence.json` only inside the saved-run store after the run completes.
- Lane 2 does not own worktree creation/teardown (Lane 1 owns that).
- Lane 2 does not own the CLI entry point or triage classification (Lane 1 owns those).
- Lane 2's `POST /decide` endpoint is a thin pass-through; Lane 4 owns the decision validation service that it calls.

**Key design decisions locked:**
- Bootstrap script ships as `bobreviewer._bootstrap` and is invoked via the `python_env` interpreter from `config.json` (not `sys.executable`), so user projects with virtual envs work correctly.
- Each probe case execution is a fresh subprocess (maximum isolation, accepts startup cost).
- Local server: `http.server.BaseHTTPRequestHandler` (stdlib only, no new dependency).
- Concurrency model: background `threading.Thread` per active run; SSE endpoint polls a `queue.Queue`; no async framework.
- Expected-output comparison strips volatile fields (`run_id`, `generated_at`, all `*_executed_at` timestamps) before diffing.
- Probe canonical location: `.bobreviewer/probes/` (primary); `probes/` at repo root (legacy fallback). Both are scanned.

---

## Endpoint Contract (Agreed with Lanes 1 and 3)

These must be agreed before any frontend or server code is written. Lane 2 implements; Lane 3 consumes; Lane 1 reviews.

| Method | Path | Request body / params | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/runs` | — | `[{run_id, generated_at, base_ref, head_ref, triage_category, status}]` | 401 (no token), 403 (wrong host) |
| `GET` | `/api/runs/{run_id}` | — | full `evidence.json` dict | 400 (bad UUID), 401, 403, 404 |
| `POST` | `/api/runs` | `{before_ref, after_ref, probes?: [], prior_run_id?: str}` | `{run_id}` (immediate) | 400 (invalid ref or bad params), 401, 403, 409 (run already active) |
| `GET` | `/api/runs/{run_id}/progress` | — | SSE stream (`data: <json>\n\n` per event) | 400, 401, 403, 404 |
| `POST` | `/api/decide` | `{run_id, symbol, case_id, verdict, rationale}` | `{file_path, git_command}` | 400 (bad params), 401, 403, 404 (run not found), 422 (validation error) |
| `GET` | `/` | — | Developer UI HTML (static asset from package) | 404 if bundle not built |

**Security constraints (all required, verified in Sub-Task 14):**
- Bind address: `127.0.0.1` only.
- `Host` header must be `localhost` or `127.0.0.1`; all other values → HTTP 403.
- `run_id` URL segments: must match UUID4 regex; any `..` or `/` → HTTP 400.
- File-path body params: repo-relative only; absolute paths and `..` sequences → HTTP 400.
- All endpoints: `Authorization: Bearer <token>` or `?token=<token>`; missing or wrong token → HTTP 401.

**Progress event format (NDJSON to stdout for CLI; `data: <json>\n\n` for SSE):**
```json
{
  "run_id": "<uuid>",
  "step": "triage | analyze | test_base | test_head | probe_base | probe_head | done | error",
  "status": "started | completed | failed",
  "message": "<human-readable string>",
  "timestamp": "<ISO-8601>"
}
```

**Pending cross-lane contract — Lane 4 sign-off required:**

| Item | Proposed contract | Status |
|---|---|---|
| `validate_and_write_decision` function signature | `validate_and_write_decision(run_id, symbol, case_id, verdict, rationale, base_output, head_output, evidence_dict) -> tuple[str, str]` where the tuple is `(file_path, git_command)`; raises `DecisionValidationError` on validation failure | ⏳ Pending Lane 4 |
| Import path | `from bobreviewer.decisions import validate_and_write_decision` | ⏳ Pending Lane 4 |

Until Lane 4 confirms this signature, Sub-Task 15 (`POST /decide`) uses a type-compatible stub with the same shape. Sub-Tasks 2–14 are not blocked by this item.

---

## Sub-Tasks

---

### Sub-Task 1 — Package scaffold and contracts

**Status:** [ ] pending

**Intent:**
Before any runner code can be written or tested, the Python package must exist with its entry point declared and the shared contract schema files committed. This unblocks all other sub-tasks and allows Lane 1 to lock schemas.

**Expected Outcomes:**
- `pyproject.toml` declares the `bobreviewer` package and the `bobreviewer` console script entry point.
- `src/bobreviewer/__init__.py` exists (empty is fine).
- `contracts/probe.schema.json`, `contracts/evidence.schema.json`, `contracts/decision.schema.json`, and `contracts/config.schema.json` are committed with the exact shapes from the spec.
- `contracts/local-server-api.md` is committed with the endpoint table above.
- `pip install -e .` succeeds from the repo root.
- `python -c "import bobreviewer"` works.

**Todo List:**
1. Create `pyproject.toml` with `[project]` metadata, `[project.scripts]` entry point `bobreviewer = "bobreviewer.cli:main"`, and `[tool.pytest.ini_options]` pointing at `tests/`.
2. Create `src/bobreviewer/__init__.py` (empty).
3. Create `contracts/probe.schema.json` from the spec.
4. Create `contracts/evidence.schema.json` from the spec (include `triage` field added in updated spec).
5. Create `contracts/decision.schema.json` from the spec.
6. Create `contracts/config.schema.json` from the spec.
7. Create `contracts/local-server-api.md` with the endpoint table from this plan's "Endpoint Contract" section.
8. Create `tests/__init__.py` (empty).
9. Run `pip install -e .` to confirm the package installs.

**Relevant Context:**
- Spec section "Shared Contracts" — exact JSON shapes for all schema files.
- L4-P1-2: fresh-install requires `pip install -e .` then `bobreviewer run` to succeed.
- Updated spec adds `triage` object to `contracts/evidence.schema.json`.

---

### Sub-Task 2 — Bootstrap script (`bobreviewer._bootstrap`)

**Status:** [ ] pending

**Intent:**
The bootstrap script is the core isolation primitive. It runs *inside* the worktree subprocess, inserts the worktree root and optional `src/` subdir onto `sys.path`, imports the target function by dotted name, calls it with the supplied args/kwargs, and returns a JSON-encoded result to stdout. It must distinguish import-time failures from call-time exceptions so the caller can assign the correct evidence status.

**Expected Outcomes:**
- `src/bobreviewer/_bootstrap.py` exists and is runnable as `python -m bobreviewer._bootstrap`.
- Input: JSON passed on stdin with keys `target` (dotted name), `args` (list), `kwargs` (dict), `worktree_root` (absolute path string), `src_layout` (bool — if true, also insert `<worktree_root>/src` onto path).
- Output on stdout: one of:
  - `{"ok": true, "value": <any JSON-representable value>}`
  - `{"ok": false, "kind": "import_error", "exception": "<type>", "message": "<msg>"}`
  - `{"ok": false, "kind": "call_error", "exception": "<type>", "message": "<msg>"}`
- Exit code 0 in all cases above (caller interprets stdout); non-zero only on bootstrap infrastructure failure (e.g. malformed input JSON).
- The script does not import from the bobreviewer package itself — only stdlib (`sys`, `json`, `importlib`).

**Todo List:**
1. Create `src/bobreviewer/_bootstrap.py`.
2. Read the JSON payload from `sys.stdin`.
3. Insert `worktree_root` at `sys.path[0]`; if `src_layout` is true also insert `<worktree_root>/src` at `sys.path[1]`.
4. Split `target` on the last `.` to get `module_path` and `function_name`.
5. Wrap `importlib.import_module(module_path)` in a try/except for `ImportError` / `ModuleNotFoundError`; on failure write `kind: "import_error"` result to stdout and exit 0.
6. After import, wrap `getattr(module, function_name)(*args, **kwargs)` in a try/except for `Exception`; on failure write `kind: "call_error"` result to stdout and exit 0.
7. On success, serialise the return value with `json.dumps` and write `kind: "ok"` result to stdout.
8. Handle non-JSON-serialisable return value: write `kind: "call_error"` with `message: "return value is not JSON-serialisable"`.
9. Write a unit test that calls the bootstrap script as a subprocess with a fixture function and verifies each output shape including the `src_layout` path insertion.

**Relevant Context:**
- Spec: "The shared probe runner loads the target function from the worktree subprocess."
- The bootstrap must NOT import from `bobreviewer` itself — it runs with the worktree's Python.
- `python -m bobreviewer._bootstrap` requires bobreviewer to be installed in the environment running the tool (L4-P1-2 guarantees this).
- Updated spec: `config.json["python_env"]` is the interpreter command; it is resolved to an absolute path by Lane 1 before being passed to Lane 2.

---

### Sub-Task 3 — Host-side probe case executor

**Status:** [ ] pending

**Intent:**
The host-side executor wraps the subprocess launch. It accepts a worktree path, the resolved Python interpreter path, and a single probe case dict; spawns the bootstrap script as a subprocess with a timeout; parses stdout; and returns a typed result dict matching the evidence case schema.

**Expected Outcomes:**
- `src/bobreviewer/executor.py` exports `run_case(worktree_path, python_exe, target, case, timeout_seconds, src_layout) -> CaseExecutionResult`.
- `CaseExecutionResult` is a `dataclass` with fields: `output` (any JSON value or exception record), `status_kind` (`"ok"` | `"import_error"` | `"call_error"` | `"timeout"`), `executed_at` (ISO-8601 string).
- On `subprocess.TimeoutExpired`: returns `status_kind: "timeout"`, `output: null`.
- On bootstrap infrastructure failure (non-zero exit, unparseable stdout): returns `status_kind: "timeout"` with stderr in message.
- On `import_error`: `status_kind: "import_error"`, `output` = exception record.
- On `call_error`: `status_kind: "call_error"`, `output` = `{"exception": "<type>", "message": "<msg>"}`.
- On success: `status_kind: "ok"`, `output` = the return value.

**Todo List:**
1. Create `src/bobreviewer/executor.py`.
2. Define `CaseExecutionResult` as a `dataclass`.
3. Implement `run_case`: build command `[python_exe, "-m", "bobreviewer._bootstrap"]`, pass JSON payload via stdin, set `timeout=timeout_seconds`.
4. Parse stdout JSON and map bootstrap `kind` to `CaseExecutionResult.status_kind`.
5. Capture `subprocess.TimeoutExpired` → `status_kind: "timeout"`.
6. Capture all other subprocess errors → `status_kind: "timeout"` with stderr in message.
7. Write unit tests: happy path; call_error; import_error; timeout.

**Relevant Context:**
- Updated spec: use `python_env` from `config.json` (resolved absolute path) as the interpreter, not `sys.executable`.
- Spec L2-P0-3: import error → `inconclusive / import_error`. Mapping happens in Sub-Task 6.

---

### Sub-Task 4 — Nondeterminism check

**Status:** [ ] pending

**Intent:**
Each probe case runs twice per side. Diverging outputs within the same revision → `inconclusive / nondeterminism_detected`. This check precedes cross-side comparison.

**Expected Outcomes:**
- `src/bobreviewer/executor.py` exports `run_case_with_repeat_check(worktree_path, python_exe, target, case, timeout_seconds, src_layout) -> RepeatedRunResult`.
- `RepeatedRunResult`: `first: CaseExecutionResult`, `second: CaseExecutionResult`, `is_nondeterministic: bool`.
- Identical outputs → `is_nondeterministic: False`.
- Differing outputs → `is_nondeterministic: True`.
- If first run is `timeout` or `import_error`, skip second run; return `is_nondeterministic: False`.

**Todo List:**
1. Add `run_case_with_repeat_check` to `executor.py`.
2. If first run's `status_kind` is in `{"timeout", "import_error"}`, skip second run.
3. Otherwise, run a second time and compare `first.output == second.output`.
4. Set `is_nondeterministic: True` if they differ.
5. Write a unit test: fixture returning `random.random()` → `is_nondeterministic: True`.
6. Write a unit test: deterministic fixture → `is_nondeterministic: False`.

**Relevant Context:**
- Spec L2-P0-5: "probes run twice on each side; diverging outputs within the same revision → `inconclusive` with `reason: 'nondeterminism_detected'`."

---

### Sub-Task 5 — Probe selector (frozen probe selection rule)

**Status:** [ ] pending

**Intent:**
Determine which probe files to run and which bytes to use on each side before any execution starts. Must scan both canonical (`.bobreviewer/probes/`) and legacy (`probes/`) locations.

**Expected Outcomes:**
- `src/bobreviewer/probe_selector.py` exports `select_probes(base_worktree_path, head_worktree_path) -> list[SelectedProbe]`.
- `SelectedProbe` dataclass: `probe_path` (repo-relative str), `probe_bytes` (bytes), `probe_hash` (SHA-256 hex), `source` (`"base"` | `"head_new"`).
- Scan order: `.bobreviewer/probes/` first (canonical), then `probes/` (legacy). Paths from both dirs enter the same union.
- Four-case selection rule:
  - Base only → base bytes.
  - Head only (new probe) → head bytes, `source: "head_new"`.
  - Both sides, same hash → base bytes.
  - Both sides, different hash (edited probe) → base bytes, `source: "base"`.
- Output list is sorted by `probe_path` for stable ordering.

**Todo List:**
1. Create `src/bobreviewer/probe_selector.py`.
2. Define `SelectedProbe` dataclass.
3. Implement `_scan_probe_dir(worktree_path)` that returns `{relative_path: bytes}` by checking `.bobreviewer/probes/` then `probes/`; skip dirs that do not exist.
4. Implement `select_probes`: build path-keyed dicts for each side, union paths, apply four-case rule.
5. Return sorted list.
6. Write unit tests for all four cases using temp directories, including the dual-location scan.

**Relevant Context:**
- Updated spec: "A probe is a committed JSON file under `.bobreviewer/probes/` (canonical location) or `probes/` (legacy root-level location; both work)."
- `probe_hash` goes into `probe_results[].probe_hash` in evidence.

---

### Sub-Task 6 — Probe runner (assembles cases into evidence probe_results)

**Status:** [ ] pending

**Intent:**
Ties together selector, executor, and nondeterminism check. Emits progress events around each step. Produces the `probe_results[]` list that Lane 1 writes into `evidence.json`.

**Expected Outcomes:**
- `src/bobreviewer/probe_runner.py` exports `run_probes(base_worktree_path, head_worktree_path, python_exe, triage, emit, timeout_seconds, src_layout) -> list[dict]`.
- `triage` is the triage dict from Lane 1. If `triage["skipped"] == True`, emit a single skipped progress event and return an empty list.
- `emit` is the progress event callback (see Sub-Task 11).
- Status assignment rules (in precedence order):
  1. Either side nondeterministic → `inconclusive`, `reason: "nondeterminism_detected"`.
  2. Either side `import_error` → `inconclusive`, `reason: "import_error"`.
  3. Either side `timeout` → `inconclusive`, `reason: "timeout"`.
  4. Both succeeded, `base_output == head_output` → `match`. Exception note: matching exception records on both sides are **not** `match` — they are `differ`.
  5. Both succeeded, outputs differ → `differ`.
- Each case dict contains all required evidence fields including `base_executed_at`, `head_executed_at`, `inconclusive_reason`.

**Todo List:**
1. Create `src/bobreviewer/probe_runner.py`.
2. Add triage-skip guard: if `triage["skipped"]`, emit `step: "probe_base", status: "completed", message: "skipped (docs-only)"` and return `[]`.
3. Call `select_probes`; parse each probe file JSON.
4. For each probe, emit `step: "probe_base", status: "started"` then run base side; emit `step: "probe_base", status: "completed"`.
5. For each probe, emit `step: "probe_head", status: "started"` then run head side; emit `step: "probe_head", status: "completed"`.
6. Apply status assignment rules; build case dicts.
7. Build probe result dicts matching the evidence schema.
8. Integration test (after Sub-Task 7): assert `status == "differ"`, `base_output == 100.0`, `head_output == 99.99`.

**Relevant Context:**
- Spec: "Newly added probes are never grounds for skipping — they always run." This means even in a `docs-only` diff, if there are new probes, they run. The triage-skip guard must check for new probes before short-circuiting.
- Spec L2-P0-4: matching exceptions are not a match.

---

### Sub-Task 7 — Sample project and demo-base / demo-rounding-change Git tags

**Status:** [ ] pending

**Intent:**
The demo scenario is the only integration test that proves the whole Lane 2 stack works end-to-end. Creates the minimal sample project for Scenario 1 (rounding change) and the immutable `demo-base` annotated tag.

**Expected Outcomes:**
- `demo/sample_project/discount.py` has `apply_discount` that rounds to 2 d.p. on `demo-base` and loses that rounding on `demo-rounding-change`.
- `demo/sample_project/invoice.py` has `calculate_invoice` calling `apply_discount` — unchanged between tags.
- `demo/sample_project/tests/test_discount.py` passes on both tags.
- `demo/sample_project/.bobreviewer/probes/invoice_basic.json` is a valid probe targeting `invoice.calculate_invoice` with an input that yields `100.0` before and `99.99` after.
- `demo-base` is an annotated tag; `demo-rounding-change` is a second annotated tag.
- End-to-end `run_probes` call returns `status: "differ"`, `base_output: 100.0`, `head_output: 99.99`.

**Todo List:**
1. Create `demo/sample_project/discount.py`, `invoice.py`, `tests/test_discount.py`, `pyproject.toml`.
2. Create `demo/sample_project/.bobreviewer/probes/invoice_basic.json` as a valid probe (probe canonical location).
3. Commit and create annotated tag `demo-base` (`git tag -a demo-base -m "demo base revision"`).
4. Edit `discount.py` rounding so the probe diverges; keep tests passing.
5. Commit and create annotated tag `demo-rounding-change`.
6. Run the probe runner end-to-end and assert outputs.

**Relevant Context:**
- Updated spec: probes are now under `.bobreviewer/probes/` in the target project.
- Demo script Act 1 references `--probe .bobreviewer/probes/invoice_basic.json`.
- `demo-base` must be immutable — use annotated tag.

---

### Sub-Task 8 — Frozen test suite runner

**Status:** [ ] pending

**Intent:**
Runs pytest in a subprocess against each worktree using the base revision's test config. Captures pass/fail/error per node ID. Returns `test_results` dict and `frozen_suite_hash`.

**Expected Outcomes:**
- `src/bobreviewer/test_runner.py` exports `run_tests(base_worktree_path, head_worktree_path, python_exe, triage, emit, timeout_seconds) -> tuple[dict, str]`.
- If `triage["skipped"]`, emit skipped events and return empty `test_results` dict + empty hash.
- Returns `(test_results_dict, frozen_suite_hash_hex)`.
- Frozen test suite = test files in base worktree only.
- `frozen_suite_hash` = SHA-256 of sorted `(relative_path, file_bytes)` pairs.
- Subprocess invoked with the `python_exe` interpreter.
- Base-side failures are visible in output (not hidden).
- Progress events emitted: `test_base started/completed`, `test_head started/completed`.

**Todo List:**
1. Create `src/bobreviewer/test_runner.py`.
2. Add triage-skip guard.
3. Enumerate base worktree test files; compute `frozen_suite_hash`.
4. Emit `test_base started`; run pytest in subprocess against base worktree with frozen file list; parse output; emit `test_base completed`.
5. Emit `test_head started`; run same frozen file list against head worktree; parse output; emit `test_head completed`.
6. Return tuple.
7. Add `pytest-json-report` to `pyproject.toml` optional/dev dependencies.
8. Write test against sample project: confirm all pass on both tags for Scenario 1.

**Relevant Context:**
- Spec L2-P0-1, L2-P1-2.
- `python_exe` replaces `sys.executable` to support virtual envs.

---

### Sub-Task 9 — Prior-report linking

**Status:** [ ] pending

**Intent:**
When `--prior-report` is supplied, link new probe result entries to earlier `differ` entries by `probe_file + probe_hash`. Enables Act 1 rerun to show resolution of an earlier difference.

**Expected Outcomes:**
- `run_probes` accepts optional `prior_report: dict | None`.
- Cases from the prior report with `status: "differ"` on matching `(probe_file, probe_hash)` → `prior_difference_run_id` set to prior `run_id`.
- No prior report or no matching differ entry → `prior_difference_run_id: null`.
- Returns `prior_run_id` (the prior report's `run_id`) for Lane 1 to write into the top-level field.

**Todo List:**
1. Add `prior_report` parameter to `run_probes`.
2. Build lookup from `prior_report["probe_results"]` keyed by `(probe_file, probe_hash)`.
3. For each probe result, look up and set `prior_difference_run_id` if applicable.
4. Return `prior_run_id` alongside probe results.
5. Write tests: mock prior report with differ entry; confirm linking. Mock with match entry; confirm null.

**Relevant Context:**
- Spec L2-P1-1. Matching is by `probe_file + probe_hash` — not probe target name.

---

### Sub-Task 10 — Expected-output validator and remaining four demo scenarios

**Status:** [ ] pending

**Intent:**
Build the volatile-field-stripping comparator for L2-P0-8 and scaffold the remaining four demo scenarios with their tagged commits and expected output files.

**Expected Outcomes:**
- `src/bobreviewer/demo_validator.py` exports `compare_evidence(actual, expected) -> list[str]` (empty = match).
- Volatile fields stripped recursively before comparison: `run_id`, `generated_at`, `base_executed_at`, `head_executed_at`, `prior_run_id`.
- `demo/expected/` has five scenario files with volatile fields set to sentinel value `"<volatile>"`.
- Remaining four tags created: `demo-tax-update`, `demo-refactor`, `demo-broken-import`, `demo-tax-update-v2`.
- Parametrized pytest confirms all five scenarios match expected outputs.

**Todo List:**
1. Create `src/bobreviewer/demo_validator.py`.
2. Define volatile field list; implement recursive strip.
3. Generate and commit `demo/expected/scenario1.json` from a known-good Scenario 1 run.
4. Create `demo/sample_project/pricing.py` with `calculate_price`.
5. Scaffold and tag `demo-tax-update`, `demo-refactor`, `demo-broken-import`, `demo-tax-update-v2`.
6. Generate and commit expected files for Scenarios 2–5.
7. Write parametrized pytest for all five scenarios.

**Relevant Context:**
- Scenario 4: missing import must be absent in the base worktree.
- Scenario 5: requires a committed decision fixture (mock or coordinate with Lane 4).

---

### Sub-Task 11 — Progress event emitter

**Status:** [ ] pending

**Intent:**
Single `emit_progress()` function shared by all runner modules. During CLI runs it writes NDJSON to stdout. During server runs it writes to stdout *and* appends to a per-run `events.jsonl` file that the SSE endpoint can replay for late-connecting clients.

**Expected Outcomes:**
- `src/bobreviewer/progress.py` exports `make_emitter(run_id, events_path, mode) -> Callable`.
- `mode` is `"cli"` (stdout only) or `"server"` (stdout + append to `events_path`).
- Each emitted event matches the Progress Event Contract shape from the spec.
- Emitter is thread-safe (uses a lock when writing to file in server mode).
- A late-connecting SSE client can call `replay_events(events_path) -> list[dict]` to get all past events.

**Todo List:**
1. Create `src/bobreviewer/progress.py`.
2. Define the event dict shape; validate `step` and `status` against allowed enum values.
3. Implement `make_emitter`: closure over `run_id`, `events_path`, `mode`, and a `threading.Lock`.
4. `emit(step, status, message)`: builds the event dict with current ISO-8601 timestamp, writes NDJSON to stdout, optionally appends to `events_path` under lock.
5. Implement `replay_events(events_path) -> list[dict]`: reads `events.jsonl` line by line; skips malformed lines.
6. Write tests: emit a sequence of events in CLI mode and confirm stdout output; emit in server mode and confirm file contents; test replay.

**Relevant Context:**
- Spec Progress Event Contract: `step` enum `triage | analyze | test_base | test_head | probe_base | probe_head | done | error`; `status` enum `started | completed | failed`.
- CLI emits NDJSON (`{"step": ...}\n`); SSE emits `data: {"step": ...}\n\n`.
- `events.jsonl` lives at `.bobreviewer/runs/<run_id>/events.jsonl`.

---

### Sub-Task 12 — Saved-run store

**Status:** [ ] pending

**Intent:**
Persist completed runs atomically under `.bobreviewer/runs/<run_id>/`. Write `meta.json` at run start so interrupted runs are detectable on the next `bobreviewer ui` launch. Atomic `evidence.json` write prevents half-written files.

**Expected Outcomes:**
- `src/bobreviewer/run_store.py` exports:
  - `create_run_dir(repo_dir, run_id) -> Path` — creates the run directory, writes `meta.json` with `status: "running"`.
  - `save_evidence(run_dir, evidence_dict)` — writes to `evidence.json.tmp` then `os.replace()` to `evidence.json`; updates `meta.json` to `status: "completed"`.
  - `list_runs(repo_dir) -> list[dict]` — reads all `meta.json` files; any run dir with no `evidence.json` is reported as `status: "interrupted"`.
  - `get_run(repo_dir, run_id) -> dict` — reads and returns `evidence.json` for a given `run_id`; raises `RunNotFoundError` if absent.
- `meta.json` schema: `{run_id, started_at, status, base_ref, head_ref, triage_category}`.
- The `.bobreviewer/runs/` directory is git-ignored.
- `list_runs` is idempotent — it does not modify any files.

**Todo List:**
1. Create `src/bobreviewer/run_store.py`.
2. Implement `create_run_dir`: `mkdir -p`; write initial `meta.json`; create `events.jsonl` (empty).
3. Implement `save_evidence`: write to `.tmp`, `os.replace()`, update `meta.json`.
4. Implement `list_runs`: scan `<repo_dir>/.bobreviewer/runs/*/meta.json`; mark dirs missing `evidence.json` as `"interrupted"`.
5. Implement `get_run`: read `evidence.json`; raise `RunNotFoundError` (a custom `Exception` subclass) if not found.
6. Ensure `.bobreviewer/runs/` appears in `bobreviewer init`'s `.gitignore` block (coordinate with Lane 1).
7. Write tests: create run; save evidence; list shows completed; missing evidence shows interrupted; get_run raises on missing.

**Relevant Context:**
- Spec "Saved Runs": "Completed runs are stored under `.bobreviewer/runs/`… local to the developer's machine and is never committed."
- Atomic `os.replace()` is POSIX-atomic and works on Windows since Python 3.3.
- `meta.json` `status` field drives the run list UI in Lane 3.

---

### Sub-Task 13 — Local server: runs and progress endpoints

**Status:** [ ] pending

**Intent:**
The core server handler serving the runs list, individual run evidence, new run start (with one-at-a-time enforcement), and SSE progress stream. Uses `http.server.BaseHTTPRequestHandler` with hand-written routing.

**Expected Outcomes:**
- `src/bobreviewer/server.py` exports `make_server(repo_dir, token, port) -> HTTPServer`.
- `GET /api/runs` returns JSON list from `run_store.list_runs`.
- `GET /api/runs/{run_id}` returns evidence JSON from `run_store.get_run`.
- `POST /api/runs` validates `before_ref` and `after_ref` via Lane 1's ref-validation function; if a run is already active, returns HTTP 409 with `{error: "run_in_progress", active_run_id: ...}`; otherwise spawns a daemon thread, calls the existing probe + test runner pipeline, saves via `run_store.save_evidence`, returns `{run_id}` immediately.
- `GET /api/runs/{run_id}/progress` sends an SSE response: replays existing events from `events.jsonl`, then polls a `queue.Queue` for new events until the `done` or `error` sentinel is received.
- Active-run lock: a module-level `threading.Lock` + `active_run_id` variable; acquired at run start, released when the run thread finishes (success or error).

**Todo List:**
1. Create `src/bobreviewer/server.py`.
2. Implement `BobReviewerHandler(BaseHTTPRequestHandler)` with `do_GET` and `do_POST`.
3. Implement route dispatch: split `self.path` into path segments; call appropriate handler method.
4. Implement `handle_list_runs`, `handle_get_run`, `handle_start_run`, `handle_progress`.
5. For `handle_start_run`: validate refs; check lock; spawn thread; return `{run_id}`.
6. For `handle_progress`: set `Content-Type: text/event-stream`; replay `events.jsonl`; poll `queue.Queue` for live events; terminate on `done`/`error`.
7. Thread target: runs the full pipeline (triage → analyze → test → probe), calls `emit_progress` in `"server"` mode, calls `save_evidence`, releases lock.
8. Write tests: GET /api/runs returns list; GET /api/runs/{id} returns evidence; POST /api/runs while run active → 409; POST /api/runs with bad ref → 400.

**Relevant Context:**
- The active-run thread must be a daemon thread so it does not prevent server shutdown.
- `queue.Queue` is thread-safe and allows the SSE handler to block on `queue.get(timeout=1)` in a polling loop.
- Lane 1 wires `bobreviewer ui` CLI → calls `make_server` with resolved `repo_dir`.

---

### Sub-Task 14 — Local server: security layer

**Status:** [ ] pending

**Intent:**
All security constraints from L2-P0-9 and L2-P1-3/4 must be enforced at the handler boundary before any business logic runs. None of these constraints should live inside individual handler methods.

**Expected Outcomes:**
- A `_check_security(handler)` helper called first in every `do_GET` / `do_POST`.
- Token check: `Authorization: Bearer <token>` header or `?token=<token>` query parameter → HTTP 401 if absent or wrong.
- Host check: `Host` header must be `localhost` or `127.0.0.1` (with or without port) → HTTP 403 otherwise.
- `run_id` path segments: matched against `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` → HTTP 400 if non-matching.
- Body parameters `run_id`, any file path: reject `..`, leading `/`, null bytes → HTTP 400.
- Server binds to `("127.0.0.1", port)` only — never `0.0.0.0`.
- Token is generated at launch with `secrets.token_urlsafe(32)` and printed to terminal.

**Todo List:**
1. Add `_check_security` to `server.py`.
2. Add `_validate_run_id(run_id_str) -> bool` using the UUID4 regex.
3. Add `_validate_repo_path(path_str) -> bool`: reject `..`, absolute paths, null bytes.
4. Apply `_check_security` as the first call in `do_GET` and `do_POST`.
5. Generate token in `make_server` using `secrets.token_urlsafe(32)`.
6. Bind socket to `127.0.0.1`.
7. Write tests: request without token → 401; wrong host → 403; invalid run_id → 400; path traversal in body → 400; valid request passes through.

**Relevant Context:**
- Spec L2-P0-9: "requests without the per-launch token are rejected with HTTP 401."
- Spec L2-P1-3: "server rejects requests with a `Host` header that is not `localhost` or `127.0.0.1`."
- Spec L2-P1-4: "server rejects `run_id` and file path parameters that contain path traversal sequences."

---

### Sub-Task 15 — `POST /decide` endpoint

**Status:** [ ] pending

**Intent:**
Thin pass-through endpoint that reads observed values from the saved run (never from the request body), delegates validation to Lane 4's decision service, and returns the written file path and suggested git command.

**Expected Outcomes:**
- `POST /api/decide` accepts `{run_id, symbol, case_id, verdict, rationale}`.
- Reads `evidence.json` for the given `run_id` from the run store.
- Finds the case matching `(symbol, case_id)`: locates the probe result entry where `target == symbol` and the case `id == case_id`.
- Extracts `base_output` and `head_output` from that case.
- Calls Lane 4's `validate_and_write_decision(run_id, symbol, case_id, verdict, rationale, base_output, head_output, evidence_dict)`.
- On success: returns HTTP 200 `{file_path, git_command}`.
- On Lane 4 validation error: returns HTTP 422 `{error: "<message>"}`.
- On run not found: HTTP 404.
- On case not found: HTTP 400.
- Browser cannot supply `base_output` or `head_output` — they are always read from the saved evidence.

**Todo List:**
1. Add `handle_decide` to `server.py`.
2. Parse and validate request body JSON.
3. Load evidence from run store.
4. Find case by `(symbol, case_id)`.
5. Extract `base_output`, `head_output`.
6. Call Lane 4's decision service function (import it; if not yet available, stub it with a type-compatible mock).
7. Return appropriate response.
8. Write tests: valid request returns file_path; run not found → 404; case not found → 400; validation error → 422; attempt to supply observed values in body is ignored.

**Relevant Context:**
- Spec: "the decision-save endpoint delegates to Lane 4's shared decision validation service."
- Spec: "never accept replacement observed values from the browser."
- Lane 4's service is a Python function, not a separate server. Import path TBD with Lane 4; use a stub until available.

---

### Sub-Task 16 — Static asset serving (`GET /`)

**Status:** [ ] pending

**Intent:**
The server must serve the pre-built developer UI frontend that Lane 3 commits to `src/bobreviewer/frontend/`. This is a simple file-serving task; the frontend is a SPA that navigates client-side using the API.

**Expected Outcomes:**
- `GET /` serves `src/bobreviewer/frontend/index.html` from the installed package.
- `GET /assets/<file>` serves static assets from `src/bobreviewer/frontend/assets/`.
- If the frontend bundle is not yet built (directory absent or empty), returns HTTP 404 with a plain-text message: "Developer UI not built. Run `npm run build` in `frontend/`."
- The server does not serve files outside the `frontend/` directory.
- File paths are resolved relative to the installed package location using `importlib.resources` or `__file__`.

**Todo List:**
1. Add `handle_static` to `server.py`.
2. Locate `frontend/` using `pathlib.Path(__file__).parent / "frontend"`.
3. Map `GET /` → `index.html`; `GET /assets/<name>` → `assets/<name>`.
4. Reject any path with `..` or absolute segments before serving.
5. Return 404 with message if `index.html` absent.
6. Infer `Content-Type` from file extension (`.html`, `.js`, `.css`, `.json` minimum).
7. Write tests: index.html served; assets served; missing bundle → 404; path traversal → 400.

**Relevant Context:**
- Spec L1-P1-3: "opening the developer UI does not require Node on the end user's machine."
- Lane 3 ships the bundle committed to `src/bobreviewer/frontend/`; it is not built at install time.

---

## Integration Points with Other Lanes

| Dependency | Direction | What Lane 2 needs |
|---|---|---|
| `contracts/evidence.schema.json` (with `triage` field) | Lane 1 → Lane 2 | Exact field names and enum values; triage skip logic |
| `contracts/probe.schema.json` | Lane 1 → Lane 2 | Probe file validation before execution |
| `worktree_base_path`, `worktree_head_path` | Lane 1 → Lane 2 | Populated Path objects from worktree setup |
| `triage_result` dict | Lane 1 → Lane 2 | Result of triage classifier; determines skip/run |
| `python_exe` (resolved absolute path) | Lane 1 → Lane 2 | Interpreter to use for subprocess bootstrap |
| `ref_validate(repo_dir, ref) -> bool` | Lane 1 → Lane 2 | Used by `POST /api/runs` before starting a run |
| `probe_results[]`, `test_results{}`, `frozen_suite_hash` | Lane 2 → Lane 1 | Passed to Lane 1's evidence writer |
| Lane 4 decision validation function | Lane 4 → Lane 2 | Called by `POST /decide`; stub until available |
| Developer UI frontend bundle | Lane 3 → Lane 2 | Committed to `src/bobreviewer/frontend/`; served by Sub-Task 16 |
| Endpoint contract | Lane 2 ↔ Lane 3 | Agreed before coding; defined in "Endpoint Contract" section above |

---

## Checks That Prove the Plan is Complete

| Acceptance Criterion | Sub-Task |
|---|---|
| L2-P0-1: pytest per-node results captured | ST 8 |
| L2-P0-2: any JSON value or exception record captured | ST 2, 3 |
| L2-P0-3: import error → inconclusive / import_error | ST 2, 3, 6 |
| L2-P0-4: call-time exception → exception record, not inconclusive | ST 2, 3, 6 |
| L2-P0-5: nondeterminism detected by repeated run | ST 4 |
| L2-P0-6: new head probes run against both sides | ST 5 |
| L2-P0-7: edited head probe uses base bytes on both sides | ST 5 |
| L2-P0-8: all five scenarios match expected outputs | ST 10 |
| L2-P0-9: server binds localhost only; missing token → 401 | ST 13, 14 |
| L2-P0-10: runs list and run detail API working | ST 13 |
| L2-P0-11: progress events emitted; terminal and UI show active step | ST 11 |
| L2-P1-1: prior-report linking via prior_run_id + probe_hash | ST 9 |
| L2-P1-2: frozen_suite_hash present and changes with test file changes | ST 8 |
| L2-P1-3: wrong Host header → 403 | ST 14 |
| L2-P1-4: path traversal sequences → 400 | ST 14 |

### First Integration Check (smallest proof the stack works)

Write a test that:
1. Creates a run via `POST /api/runs` with valid `before_ref: "demo-base"`, `after_ref: "demo-rounding-change"`.
2. Receives a `run_id` immediately.
3. Streams `GET /api/runs/{run_id}/progress` and waits for `step: "done"`.
4. Calls `GET /api/runs/{run_id}` and asserts `probe_results[0].cases[0].status == "differ"`.
5. Attempts a second `POST /api/runs` while the first is active and asserts HTTP 409.
6. Calls `GET /api/runs/{run_id}` after the run is done and asserts the same result is reopenable.

This single test exercises: the server, the run lock, the progress stream, the saved-run store, the probe runner, and the rounding-change scenario end-to-end.
