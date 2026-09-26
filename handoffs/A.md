# Lane 1 — Handoffs and Integration Notes

This file is the live interface document for Lane 1. It records what each lane needs from Lane 1, what Lane 1 needs from each lane, the actual state of each interface, and next steps.

**Update this file whenever an interface changes, a check completes, or a dependency is resolved.**

---

## Status

| Slice | State | Check result |
|---|---|---|
| 1 — Contracts and fixtures | ✅ Complete | 35/35 tests pass |
| 2 — Revision snapshots | 🔲 Not started | — |
| 3 — Impact analysis + analyze command | 🔲 Not started | — |
| 4 — Triage + pipeline | 🔲 Not started | — |
| 5 — Setup + command integration | 🔲 Not started | — |

---

## Slice 1 — Contracts and fixtures

### What was delivered

| File | Purpose |
|---|---|
| `contracts/config.schema.json` | Project config — `.bobreviewer/config.json` |
| `contracts/probe.schema.json` | Probe files — supports `fixture: true` |
| `contracts/evidence.schema.json` | Evidence bundle — full schema with execution/comparison separation |
| `contracts/decision.schema.json` | Decision records — includes `case_id`; enforces rationale for `intended` |
| `contracts/progress-event.schema.json` | Progress events — step enum locked |
| `contracts/run-metadata.schema.json` | Run listing metadata — used by `GET /api/runs` |
| `contracts/local-server-api.md` | Local server API contract — endpoints, security constraints, change process |
| `src/bobthereviewer/contracts.py` | Python validators — `validate_probe`, `validate_evidence`, `validate_decision`, etc. |
| `tests/fixtures/probe_discount.json` | Labeled fixture probe (`fixture: true`) |
| `tests/fixtures/evidence_rounding_change.json` | Labeled fixture evidence bundle (`fixture: true`) |
| `tests/fixtures/decision_unintended.json` | Labeled fixture decision — `unintended` verdict |
| `tests/fixtures/decision_intended.json` | Labeled fixture decision — `intended` verdict with rationale |

### Key design decisions made in Slice 1

1. **`fixture: true`** — the marker is a top-level boolean in probe and evidence files. It is optional (absent = not a fixture). The validator accepts but does not require it. No special runner behaviour needed for validation; the field is advisory.

2. **`execution_status` vs `comparison_status`** — these are separate fields in `probe_case_result`. A target function raising an exception → `execution_status: "exception"`, `comparison_status` is still meaningful (matching exceptions are not a match). An import failure → `execution_status: "inconclusive"`, `comparison_status: null`.

3. **Absolute path rejection** — `validate_evidence()` walks the entire evidence dict and raises `ContractError` on any string value matching an absolute path pattern (Windows `C:\...` or POSIX `/...`). This is enforced at write time by Lane 1.

4. **`case_id` in decisions** — the decision schema now includes `case_id` to precisely link a decision to a specific probe case result, not just a probe file.

5. **`via` field on callers** — two-hop paths preserve intermediate edges as `via: [{symbol, file_path, line}]`. Direct calls use `via: null`.

6. **Triage `no-semantic-change`** — requires all Python files to have structurally identical ASTs (ignoring source-location attributes). Comment/formatting-only Python changes are `no-semantic-change`, not `docs-only`. Unknown file types and parse failures classify as `code`.

---

## Interface: Lane 1 → Lane 2

### What Lane 2 receives from Lane 1 (Slice 2, TBD)

```python
@dataclass
class WorktreeContext:
    # Identity
    repository_url: str          # remote origin URL (for evidence.repository)
    repo_root: Path              # absolute path to the repository root
    # Requested refs (as supplied by user)
    base_ref: str
    head_ref: str
    # Resolved full SHAs
    base_commit: str             # 40-char hex
    head_commit: str             # 40-char hex
    # Changed files (repo-relative paths)
    changed_files: list[str]
    # Temporary checkout paths (absolute, runtime-only — never enter evidence)
    base_path: Path
    head_path: Path
```

**Contract:** `base_path` and `head_path` are only valid inside the `with WorktreeManager(...) as ctx:` block. They are cleaned up on `__exit__`, including on exception. Absolute paths must not appear in any evidence field — callers must convert to repo-relative paths before writing.

### What Lane 2 returns to Lane 1

```python
@dataclass
class ExecutionResult:
    test_results: dict           # matches evidence test_results shape
    probe_results: list[dict]    # matches evidence probe_results shape
    frozen_suite_hash: str | None
    uncovered_callers: list[str] # symbols without probe coverage
    execution_notes: list[str]   # human-readable caveats
```

**Status:** Interface defined; implementation pending Lane 2. Lane 1 will wire this return value into `evidence.json` assembly in Slice 4.

---

## Interface: Lane 1 → Lane 3

Lane 3 reads `evidence.json` files from `.bobreviewer/runs/<run_id>/`. The schema is `contracts/evidence.schema.json`. Lane 3 does not need any other Lane 1 interface.

**What Lane 3 needs to know:**
- `fixture: true` at the top level means the evidence is illustrative data — the viewer should label it clearly
- `triage.skipped: true` means tests/probes were not run — the viewer must not show this as "passed"
- `probe_results[].cases[].execution_status` and `comparison_status` are separate fields
- `changed_functions[].callers[].via` contains intermediate edges for two-hop paths (null for direct)
- All `file_path` values are repo-relative; the viewer should not prepend anything

---

## Interface: Lane 1 → Lane 4

Lane 4's decision validation service is a Python function with this signature:

```python
def validate_and_build_decision(
    run_id: str,
    symbol: str,
    probe_file: str,
    case_id: str,
    verdict: str,
    rationale: str,
    evidence: dict,           # full evidence bundle for the run
) -> dict:                    # validated decision dict ready to write
    ...
```

It must raise a structured error (compatible with `ContractError`) when:
- verdict is `"intended"` and rationale is empty or whitespace-only
- `run_id` / `symbol` / `probe_file` / `case_id` do not match anything in the evidence
- verdict value is not in the allowed enum

Lane 1's `bobreviewer decide` command calls this function. Lane 2's `POST /decide` endpoint also calls it (via import, not HTTP). The function is implemented by Lane 4.

**Status:** Interface defined; implementation pending Lane 4. Lane 1 CLI will import it when available.

---

## Interface: Lane 1 ↔ Progress events

Progress events emitted during `analyze` and `run` steps use the shape in `contracts/progress-event.schema.json`. The step enum is locked:

| Step | Owner |
|---|---|
| `triage` | Lane 1 |
| `analyze` | Lane 1 |
| `test_base`, `test_head`, `probe_base`, `probe_head` | Lane 2 |
| `done`, `error` | Lane 1 (terminal events) |

**Adding a new step requires Lane 1 approval and a schema change.** Lane 3 renders step names from this enum; changes must be coordinated.

The pipeline callback signature:

```python
ProgressCallback = Callable[[str, str, str], None]
# Arguments: (step: str, status: str, message: str)
# step and status must be valid enum values
```

---

## Probe selection rules (for Lane 2)

Lane 2's executor selects probes from the worktrees using this rule, applied to committed content — not the current index:

1. Start with all probes in the base revision under `.bobreviewer/probes/` and `probes/` (legacy)
2. Add any probes present in the head revision but not the base (new probes)
3. For any probe edited or deleted in the head revision, use the base version on both sides
4. The bytes used on both sides must be identical for each probe
5. `fixture: true` probes are never excluded by selection rules, but the runner should label their results

A newly written probe must be committed into the selected head ref before it can be selected. Staged or uncommitted probes are not visible to worktree checkout.

---

## Open items requiring cross-lane agreement

| Item | Needed by | Status |
|---|---|---|
| `WorktreeContext` dataclass confirmed by Lane 2 | Slice 2 | ⏳ Pending Lane 2 review |
| `ExecutionResult` dataclass confirmed by Lane 2 | Slice 4 | ⏳ Pending Lane 2 review |
| `validate_and_build_decision` signature confirmed by Lane 4 | Slice 5 | ⏳ Pending Lane 4 review |
| Frontend asset path in package confirmed by Lane 3 | Slice 5 | ⏳ Pending Lane 3 review |
| Progress step enum changes (if any) | All | Any change requires Lane 1 approval |

---

## Next: Slice 2 — Revision snapshots

**Goal:** `WorktreeManager` context manager + ref resolver.

**Checks that define done:**
1. `WorktreeManager(repo, "demo-base", "demo-rounding-change")` creates two worktrees outside the repo root
2. Both worktrees contain the correct committed content for their respective refs
3. Worktrees are cleaned up on normal exit
4. Worktrees are cleaned up when an exception is raised inside the `with` block
5. The developer's branch, index, and uncommitted files are unchanged after (3) and (4)
6. `WorktreeContext.base_commit` and `head_commit` are full 40-char SHAs
7. `WorktreeContext.changed_files` contains repo-relative paths, not absolute paths
8. An unresolvable ref raises a clear error before any worktree is created
