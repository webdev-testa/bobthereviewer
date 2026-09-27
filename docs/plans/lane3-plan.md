# Lane 3 Plan — Report Renderer, Both Browser Modes, and Frontend Packaging

## Top-Level Overview

Lane 3 owns everything the human reads: the Markdown report, the static judge HTML, and the
developer browser UI. All three read from `evidence.json` only — they never parse git or run
probes themselves.

**Stack:** React 18 + TypeScript, Vite, Tailwind CSS v4, shadcn/ui (Radix), React Flow + ELK
for the caller map, Lucide icons. Project lives in `web/`.

**Two browser modes from one codebase:**

| Mode | How served | Who sees it | Extra controls |
|---|---|---|---|
| Judge / Static | Single inlined HTML file, no server | PR reviewers, hackathon judges | "Demo preview — not saved" decision preview only |
| Developer / Local | Served by Lane 2's FastAPI (`bobreviewer ui`) with `?token=` | Developer on their machine | Run history, New run, live progress, Save Decision |

Both modes share the same evidence display components. Mode is detected at runtime by the
presence of `?token=` in the URL (local) or its absence (static).

**Key constraints from the user (non-negotiable):**
- shadcn/ui components only (via CLI or MCP into `src/components/ui/`)
- Colors from theme tokens only — no hex, no magic pixel sizes
- Status always shown as icon + text + color (never color alone)
- Wording: "Behavior differs" / "Same on tested cases" / "Inconclusive" / "Needs a probe" /
  "Unknown edge" — never "safe", "no impact", "bug"
- Do not change `evidence.json` data shape without asking
- Components under ~30 lines, no `any`, match existing file style
- Light and dark mode must both work

**Integration boundary with other lanes:**
- Reads `evidence.json` (Lane 1 schema, Lane 2 writes it)
- Calls `POST /decide`, `GET /api/runs`, `GET /api/runs/{run_id}`,
  `GET /api/runs/{run_id}/progress` (Lane 2 server, Lane 4 validation)
- Static HTML is uploaded as a CI artifact (Lane 4 GitHub Actions)
- Built bundle committed to `src/bobreviewer/frontend/` (Lane 1 packages it)

---

## Sub-Tasks

---

### ST-1 — Vite + React project scaffold in `web/`

**Status:** [ ] pending

**Intent**
Bootstrap the `web/` project with the exact agreed stack so every sub-task after this starts
from a consistent, working base. Nothing is built yet beyond a "Hello world" that confirms
the toolchain works end-to-end.

**Expected Outcomes**
- `web/` exists with `package.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`
- `npm run dev` starts a dev server
- `npm run build` produces `web/dist/`
- `vite-plugin-singlefile` is installed and configured so `npm run build:judge` produces a
  single inlined `dist/judge.html` with no external requests
- `tailwind.config.ts` references the theme token set (success, warning, danger, info,
  neutral, muted) — no raw hex values
- Dark mode works via the `class` strategy
- `.gitignore` excludes `web/node_modules/` and `web/dist/`

**Todo List**
- [ ] `npm create vite@latest web -- --template react-ts`
- [ ] Install Tailwind CSS v4, configure `tailwind.config.ts` with theme tokens
- [ ] Install and configure `vite-plugin-singlefile` for the judge build target
- [ ] Install shadcn/ui: `npx shadcn@latest init` inside `web/`
- [ ] Install React Flow (`@xyflow/react`) and ELK (`elkjs`, `web-worker`)
- [ ] Install Lucide React
- [ ] Add two Vite build scripts: `build` (developer bundle) and `build:judge` (inlined single file)
- [ ] Add `web/node_modules/` and `web/dist/` to root `.gitignore`
- [ ] Confirm `npm run build:judge` produces a single self-contained HTML with no `<link>` or
  external `<script src>` tags

**Relevant Context**
- `vite-plugin-singlefile` inlines all JS and CSS into one HTML — required for L3-P0-2
- Judge build target: `vite build --config vite.judge.config.ts`
- Developer build target: standard Vite output, served by Lane 2's FastAPI as static files
- Theme tokens must cover: `success`, `warning`, `danger`, `info`, `neutral`, `muted` —
  map these to CSS custom properties consumed by Tailwind

---

### ST-2 — Fake evidence fixture and TypeScript types

**Status:** [ ] pending

**Intent**
Define TypeScript types that exactly mirror `evidence.json` (from `contracts/evidence.schema.json`)
and create a hardcoded fixture. Every component is built against this fixture from day one —
no waiting for Lane 1/2 to produce a real file.

**Expected Outcomes**
- `web/src/types/evidence.ts` exports all types: `Evidence`, `ChangedFunction`, `CallerInfo`,
  `UnknownRef`, `ProbeResult`, `ProbeCase`, `TestResults`, `TriageInfo`, `DecisionRecord`
- `web/src/fixtures/evidence.fixture.ts` exports a fully-populated `Evidence` object that
  exercises all statuses: `differ`, `match`, `inconclusive`; callers both in-diff and outside;
  a `docs-only` skipped run; a prior decision record
- No `any` types anywhere in these files
- Types stay in sync with `contracts/evidence.schema.json` — a comment at the top of
  `evidence.ts` references the canonical schema location

**Todo List**
- [ ] Read `contracts/evidence.schema.json` (once available from Lane 1; stub from spec until then)
- [ ] Write `web/src/types/evidence.ts` with all types derived from the schema
- [ ] Write `web/src/types/api.ts` with types for the local server API responses
  (`RunSummary`, `DecideRequest`, `DecideResponse`, `ProgressEvent`)
- [ ] Write `web/src/fixtures/evidence.fixture.ts` with a rich fake `Evidence` object
- [ ] Verify: TypeScript compiler (`tsc --noEmit`) passes with no errors

**Relevant Context**
- Schema source of truth: `contracts/evidence.schema.json`
- `triage.category` enum: `docs-only | tests-only | config-deps | no-semantic-change | code`
- Case `status` enum: `match | differ | inconclusive`
- Exception output shape: `{"exception": "<type>", "message": "<str>"}`
- Progress event shape: `{run_id, step, status, message, timestamp}`

---

### ST-3 — Mode detection and data loading

**Status:** [ ] pending

**Intent**
Implement the runtime switch between static mode (evidence inlined at build time) and local
mode (evidence fetched from the Lane 2 API using `?token=`). This is the architectural seam
between the two browser modes — every other component stays mode-agnostic.

**Expected Outcomes**
- `web/src/lib/mode.ts` exports `isLocalMode(): boolean` — true when `?token=` is present
- `web/src/lib/local-api.ts` exports typed async functions for all API endpoints:
  `listRuns()`, `getRun(runId)`, `streamProgress(runId, onEvent)`, `postDecide(body)`
- In judge build: `evidence.json` data is injected by Vite at build time via a virtual module
  or `import`; no `fetch()` at runtime
- In local build: data is fetched from `/api/runs/{run_id}` using the token from the URL
- `local-api.ts` always passes `Authorization: Bearer <token>` on every request
- TypeScript strict — no `any`

**Todo List**
- [ ] Write `web/src/lib/mode.ts` — parse `?token=` from `window.location.search`
- [ ] Write `web/src/lib/local-api.ts` — typed fetch wrappers for all 5 API endpoints
- [ ] Write `web/src/lib/evidence-loader.ts` — returns the evidence for the current mode:
  inlined data (static) or fetched data (local)
- [ ] In `vite.judge.config.ts`, inject the evidence JSON as a build-time constant using
  Vite's `define` or a virtual module
- [ ] Write a `useEvidence` React hook that calls the loader and exposes
  `{ evidence, loading, error }`

**Relevant Context**
- Local server API: `GET /api/runs`, `GET /api/runs/{run_id}`, `POST /api/runs`,
  `GET /api/runs/{run_id}/progress` (SSE), `POST /api/decide`
- Token is in `?token=<value>` or `Authorization: Bearer <token>` — use URL param for the
  initial page load, then header for all subsequent API calls
- Lane 2 owns the server; this file is the only place in Lane 3 that knows the server exists

---

### ST-4 — Shared evidence display components

**Status:** [ ] pending

**Intent**
Build the core read-only components that render an `evidence.json` — used identically in both
the judge page and the developer page. These are the most critical UI pieces for the hackathon
demo.

**Expected Outcomes**
- `TriageBadge` — shows triage category with icon + text + color token; shows skip reason if
  skipped; never color alone
- `ChangedFunctionList` — lists all changed functions with their file path
- `CallerRow` — single caller with symbol, file, line, in-diff flag, and needs-probe flag;
  outside-diff callers visually and textually distinct
- `UnknownRefRow` — unknown reference with file, line, reason; labeled "Unknown edge"
- `ProbeResultTable` — before/after outputs per case; status shown as
  "Behavior differs" / "Same on tested cases" / "Inconclusive" with icon + text
- `TestResultTable` — pass/fail/error per node ID on base and head side by side
- `DecisionBadge` — shows verdict and rationale from a decision record in the evidence bundle
- All components: no `any`, under ~30 lines, shadcn/ui primitives only, theme tokens only,
  light + dark mode tested

**Todo List**
- [ ] Install required shadcn components: `badge`, `table`, `card`, `tooltip`, `separator`
- [ ] Write `TriageBadge` — maps category to icon (Lucide) + label + token color
- [ ] Write `CallerRow` — `in_diff: false` callers get a distinct label "Outside diff"
- [ ] Write `UnknownRefRow` — always labeled "Unknown edge" per wording rules
- [ ] Write `ProbeResultTable` — status wording: "Behavior differs" (differ), "Same on
  tested cases" (match), "Inconclusive" (inconclusive), "Needs a probe" (needs_probe)
- [ ] Write `TestResultTable` — base vs head columns; fail/error rows highlighted
- [ ] Write `DecisionBadge` — shows verdict, rationale, and "This is prior context,
  not approval of the current change" when surfaced from history
- [ ] Write `ChangedFunctionList` — composes CallerRow, UnknownRefRow, ProbeResultTable
- [ ] Smoke-test all components against the fixture from ST-2

**Relevant Context**
- Status wording rules (from user): "Behavior differs", "Same on tested cases",
  "Inconclusive", "Needs a probe", "Unknown edge" — never "safe", "no impact", "bug"
- `needs_probe: true` on a caller means no probe covers it yet → show "Needs a probe"
- `unknown_references` → "Unknown edge"
- Icons: use Lucide only (`AlertTriangle`, `CheckCircle2`, `HelpCircle`, `GitBranch`, etc.)

---

### ST-5 — Caller evidence map (React Flow + ELK)

**Status:** [ ] pending

**Intent**
Render the caller relationship graph for a changed function. This is a key visual differentiator
for the hackathon — makes the impact of a change immediately obvious.

**Expected Outcomes**
- `CallerMap` component renders a directed graph: changed function at center, callers as
  surrounding nodes
- Callers outside the diff are visually distinct (different node shape or border style) AND
  carry a text label "Outside diff" (never color alone)
- ELK lays out nodes automatically — no manual x/y positioning
- Clicking a caller node highlights it and shows its file + line in a tooltip/panel
- Unknown references shown as dashed-edge nodes labeled "Unknown edge"
- Works in both judge and developer pages
- Accessible: nodes are keyboard-navigable; focused node shows file + line

**Todo List**
- [ ] Confirm React Flow + ELK work in the Vite build (no WASM issues in single-file build)
- [ ] Write `web/src/lib/build-graph.ts` — converts `ChangedFunction` to React Flow
  `nodes` + `edges` with ELK layout
- [ ] Write `CallerMap` component — wraps `<ReactFlow>` with ELK auto-layout
- [ ] Style: changed function node uses `info` token; outside-diff callers use `warning`
  token + "Outside diff" text label; unknown refs use dashed edge + "Unknown edge" label
- [ ] Add `<NodeDetail>` panel — shows symbol, file, line on node focus/click
- [ ] Test with the fixture: verify layout renders, outside-diff nodes have text labels

**Relevant Context**
- React Flow docs: `@xyflow/react`
- ELK layout: `elkjs` + `web-worker` for layout computation off the main thread
- `vite-plugin-singlefile` must inline the ELK worker — verify this works at build time
- L3-P0-4: "callers in unchanged files are visually distinct AND carry a text label"

---

### ST-6 — Judge page (static HTML, no server)

**Status:** [ ] pending

**Intent**
Compose all shared components into the judge-facing page. This is what hackathon judges open
offline. It must pass the "no network requests" check in DevTools.

**Expected Outcomes**
- `web/src/pages/JudgePage.tsx` renders the full evidence view using shared components
- Session-only decision preview: a local-state form labeled "Demo preview — not saved" that
  does not call any API and writes nothing to disk
- `npm run build:judge` produces `web/dist/judge.html` — a single file with all JS, CSS,
  and the evidence fixture inlined
- Opening `judge.html` in a browser with network disabled shows all sections correctly
- DevTools Network tab shows zero requests after initial load
- No local absolute paths or secrets in the HTML source

**Todo List**
- [ ] Write `web/src/pages/JudgePage.tsx` — compose TriageBadge, ChangedFunctionList,
  CallerMap, ProbeResultTable, TestResultTable, DecisionBadge
- [ ] Add session-only decision form: `<DecisionPreviewForm>` with a banner
  "Demo preview — not saved"; uses local React state only; no `fetch()`
- [ ] Confirm `vite.judge.config.ts` uses `vite-plugin-singlefile` and sets `base: ""`
- [ ] Run `npm run build:judge`; open `dist/judge.html` with file:// in browser;
  verify DevTools shows no network requests
- [ ] Run pre-publish check: scan HTML for absolute paths (`C:\`, `/home/`, `/Users/`) and
  token-like strings; fail if found

**Relevant Context**
- L3-P0-2, L3-P0-5, L3-P0-6
- `vite-plugin-singlefile` config: `{ useRecommendedBuildConfig: true }`
- The evidence data for the judge page is the pre-baked Act 1 rerun evidence JSON, inlined
  at build time — this is the `submission/viewer/` artifact

---

### ST-7 — Developer page (local mode, API-connected)

**Status:** [ ] pending

**Intent**
Compose the developer-facing page that talks to the Lane 2 local server. This page adds run
history, new run controls, live progress, and the real Save Decision flow on top of the
shared evidence display.

**Expected Outcomes**
- `web/src/pages/DevPage.tsx` renders the run list sidebar + evidence panel
- Run list: shows all saved runs from `GET /api/runs`; clicking a run loads its evidence
  from `GET /api/runs/{run_id}`
- New run form: `before_ref` and `after_ref` inputs + Start button → `POST /api/runs` →
  shows live progress from SSE stream
- Progress display: step-by-step list (triage → analyze → test_base → test_head →
  probe_base → probe_head → done) with started/completed/failed status and message
- Save Decision button: appears on any probe case with `status: "differ"`; opens a form
  for verdict + rationale; calls `POST /api/decide`; on success shows file path and
  git command; rejects `intended` with empty rationale before sending
- All controls keyboard-accessible

**Todo List**
- [ ] Install shadcn components: `sidebar` (or custom), `dialog`, `select`, `input`,
  `button`, `progress`
- [ ] Write `RunList` component — calls `listRuns()`, renders sorted run summaries
- [ ] Write `ProgressPanel` component — consumes SSE stream via `streamProgress()`;
  renders step list with icon + text + color token per status
- [ ] Write `NewRunForm` component — inputs for refs, probe paths; calls `POST /api/runs`;
  switches to ProgressPanel on submit
- [ ] Write `SaveDecisionDialog` component — verdict select, rationale textarea;
  client-side validation (non-empty rationale for `intended`); calls `postDecide()`;
  shows `{file_path, git_command}` on success
- [ ] Write `DevPage.tsx` — composes RunList + evidence panel + SaveDecisionDialog
- [ ] Verify: with Lane 2 server running (or mocked), run history loads and decision
  save flow completes

**Relevant Context**
- L3-P0-7, L3-P0-8, L3-P0-9
- `streamProgress()` uses `EventSource` with the bearer token as a query param
- `SaveDecisionDialog` must validate rationale client-side before calling the API
  (mirrors the server-side check in Lane 4's validation service)
- The token comes from `?token=` in the URL — `local-api.ts` reads it once on load

---

### ST-8 — Markdown report renderer (Python)

**Status:** [ ] pending

**Intent**
Produce the Markdown string that appears in GitHub PR comments and on the terminal. This is
a pure Python function — no frontend involved.

**Expected Outcomes**
- `src/bobreviewer/report.py` exports `render_markdown(evidence: dict) -> str`
- Output renders correctly as a GitHub PR comment: headings, tables, fenced code blocks
- Shows: triage category, changed functions + callers with file/line, probe results
  (before → after per case), test result summary, decision record if present
- If triage skipped execution: report explicitly states what was skipped and why
- Prior decision context displayed with: "This is prior context, not approval of the
  current change"
- No local paths, no secrets in output

**Todo List**
- [ ] Write `src/bobreviewer/report.py` with `render_markdown(evidence: dict) -> str`
- [ ] Sections: header (run ID, refs, triage), changed functions table, caller table,
  probe results table, test results summary, decisions section
- [ ] Skipped execution: emit a clearly labeled "Execution skipped" section with reason
- [ ] Test: render the fixture evidence and manually verify GitHub Markdown rendering
  (paste into a GitHub comment preview or use a local Markdown renderer)

**Relevant Context**
- L3-P0-1: must render correctly in GitHub PR comments
- Output is consumed by Lane 4's GitHub Actions comment poster
- Wording rules apply here too: "Behavior differs", "Same on tested cases", etc.

---

### ST-9 — Frontend build output and Python package integration

**Status:** [ ] pending

**Intent**
Wire the Vite build output into the Python package so `bobreviewer ui` serves the frontend
without requiring Node on the end user's machine. The built assets are committed to the repo.

**Expected Outcomes**
- `npm run build` outputs the developer bundle to `src/bobreviewer/frontend/`
- `npm run build:judge` outputs the judge HTML to `src/bobreviewer/frontend/judge.html`
  (also copied to `submission/viewer/judge.html` as the submission artifact)
- `src/bobreviewer/frontend/` is committed to git (the built bundle is checked in)
- `pyproject.toml` includes `src/bobreviewer/frontend/` as package data
- A `build.sh` / `build.ps1` script in `web/` runs both builds and copies output to
  `src/bobreviewer/frontend/`
- Opening the developer UI does not require Node on the end user's machine (L3-P0-10)

**Todo List**
- [ ] Configure `vite.config.ts` `outDir` to `../src/bobreviewer/frontend/`
- [ ] Configure `vite.judge.config.ts` `outDir` to `../src/bobreviewer/frontend/` with
  filename `judge.html`
- [ ] Write `web/build.ps1` (PowerShell) that runs both builds
- [ ] Add `src/bobreviewer/frontend/` to `pyproject.toml` as `package-data`
- [ ] Add `src/bobreviewer/frontend/` to `.gitignore` exclusion — it IS committed,
  so ensure it is NOT in `.gitignore`
- [ ] Verify: `pip install -e .` then `bobreviewer ui` serves the frontend correctly
  without running `npm`

**Relevant Context**
- L3-P0-10, L1-P1-3
- Lane 1 owns `pyproject.toml` — coordinate the `package-data` addition with them
- Lane 4 CI staleness check compares `frontend/` mtime vs `web/src/` mtime — the
  build script must produce deterministic output so CI can detect staleness

---

### ST-10 — Accessibility, mobile, and pre-publish checks

**Status:** [ ] pending

**Intent**
Meet the accessibility and mobile requirements from the spec and the user's rules, and add
the pre-publish scan that blocks secrets and absolute paths from shipping in the judge HTML.

**Expected Outcomes**
- All interactive elements reachable by keyboard; visible focus ring on all focusable elements
- Layout usable at 320 px viewport width (no horizontal overflow, no clipped content)
- `web/scripts/check-judge-html.ts` script scans `dist/judge.html` for:
  absolute paths (`C:\`, `/home/`, `/Users/`) and token-like strings (40+ char hex);
  exits non-zero if found
- Light and dark mode both render correctly (no invisible text, no broken contrast)

**Todo List**
- [ ] Audit all interactive elements with keyboard-only navigation; add `focus-visible`
  ring styles via Tailwind to any missing elements
- [ ] Test at 320 px: use browser DevTools responsive mode; fix any overflow issues
- [ ] Write `web/scripts/check-judge-html.ts` — regex scan for absolute paths and
  token-like strings; run as `npm run check:judge`
- [ ] Add `npm run check:judge` to the `build:judge` pipeline so it runs automatically
- [ ] Verify dark mode: toggle `dark` class on `<html>`; check all components for contrast

**Relevant Context**
- L3-P0-6, L3-P1-2, L3-P1-3
- Tailwind dark mode strategy: `class` (set in `tailwind.config.ts`)
- Focus ring: use `focus-visible:ring-2 focus-visible:ring-offset-2` via shadcn defaults

---

## Component and File Map

```
web/
  src/
    types/
      evidence.ts        # TypeScript types mirroring evidence.schema.json
      api.ts             # Local server API response types
    fixtures/
      evidence.fixture.ts
    lib/
      mode.ts            # isLocalMode()
      local-api.ts       # Typed fetch wrappers for Lane 2 API
      evidence-loader.ts # Mode-aware data loader
      build-graph.ts     # evidence → React Flow nodes/edges with ELK
    components/
      ui/                # shadcn/ui components (CLI-managed)
      TriageBadge.tsx
      CallerRow.tsx
      UnknownRefRow.tsx
      ProbeResultTable.tsx
      TestResultTable.tsx
      DecisionBadge.tsx
      ChangedFunctionList.tsx
      CallerMap.tsx
      NodeDetail.tsx
      ProgressPanel.tsx
      RunList.tsx
      NewRunForm.tsx
      SaveDecisionDialog.tsx
      DecisionPreviewForm.tsx
    pages/
      JudgePage.tsx
      DevPage.tsx
    App.tsx              # Reads mode, renders JudgePage or DevPage
  scripts/
    check-judge-html.ts
  vite.config.ts         # Developer build → src/bobreviewer/frontend/
  vite.judge.config.ts   # Judge build → src/bobreviewer/frontend/judge.html
  tailwind.config.ts
  tsconfig.json
  package.json
  build.ps1

src/bobreviewer/
  report.py              # render_markdown(evidence) → str
  frontend/              # Committed built assets (not in .gitignore)
    index.html
    assets/
    judge.html
```

---

## Dependencies on Other Lanes

| What Lane 3 needs | From | When needed |
|---|---|---|
| `contracts/evidence.schema.json` final shape | Lane 1 | ST-2 (use spec stub until available) |
| `contracts/local-server-api.md` agreed | Lane 1 | ST-3 |
| Local server running for integration test | Lane 2 | ST-7 (can mock until then) |
| `POST /decide` implemented | Lane 2 + Lane 4 | ST-7 |
| Real `evidence.json` from Act 1 run | Lane 2 | ST-6 (judge page pre-bake) and ST-9 |

---

## Milestone Mapping

| Milestone | Lane 3 deliverable | Sub-tasks |
|---|---|---|
| M0 — Contracts locked | Judge HTML renders hardcoded evidence in browser | ST-1, ST-2, ST-3 (partial), ST-6 (partial) |
| M1 — First real comparison | Judge HTML renders real scenario 1 evidence + map; developer UI fetches same run | ST-4, ST-5, ST-6, ST-7 (partial) |
| M2 — Decision loop | Save Decision button calls `POST /decide`; success shows git command | ST-7 (complete) |
| M3 — CI, full UI, packaging | Bundle committed; judge HTML passes offline + accessibility checks | ST-8, ST-9, ST-10 |
| M4 — Submission | `submission/viewer/judge.html` pre-baked from Act 1 rerun | ST-9 |
