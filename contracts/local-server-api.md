# contracts/local-server-api.md — Local Server API Contract

> **Owner:** Lane 2 implements · Lane 3 consumes · Lane 4 (decision validation service) is called by `POST /decide`
> Lane 1 coordinates all changes to this document.

## Overview

The local developer UI server (`bobreviewer ui`) is an HTTP/1.1 server bound exclusively to `localhost`. It serves the pre-built frontend and exposes a JSON API for run management and decision recording.

A per-launch random token is generated at startup and printed to the terminal. Every API request must include it.

## Security Constraints (all required)

| Rule | Enforcement |
|---|---|
| Bind address | `127.0.0.1` only — never `0.0.0.0` |
| Host header | Must be `localhost` or `127.0.0.1`; all other values → HTTP 403 |
| Token | `Authorization: Bearer <token>` header **or** `?token=<token>` query param; missing or wrong → HTTP 401 |
| `run_id` parameters | UUID format only (`[0-9a-f-]{36}`); any other value → HTTP 400 |
| File path parameters | Repo-relative paths only; absolute paths and `..` sequences → HTTP 400 |

## Authentication

```
Authorization: Bearer <token>
```
or
```
GET /api/runs?token=<token>
```

## Endpoints

### `GET /api/runs`

List all saved runs in `.bobreviewer/runs/`.

**Response:** `200 OK`
```json
[
  {
    "run_id": "<uuid>",
    "generated_at": "<ISO-8601>",
    "base_ref": "<ref>",
    "head_ref": "<ref>",
    "triage_category": "code | docs-only | tests-only | config-deps | no-semantic-change"
  }
]
```

---

### `GET /api/runs/{run_id}`

Return the full `evidence.json` for a given run.

**Path param:** `run_id` — UUID format only.

**Response:** `200 OK` — full `evidence.json` object.

**Errors:**
- `400` — invalid `run_id` format or path traversal
- `404` — run not found

---

### `POST /api/runs`

Start a new `bobreviewer run` in the background. Returns immediately with the new `run_id`; progress is streamed via SSE.

**Request body:**
```json
{
  "before_ref": "<ref>",
  "after_ref": "<ref>",
  "probes": ["<repo-relative probe path>"],
  "prior_run_id": "<uuid or null>"
}
```

**Response:** `202 Accepted`
```json
{ "run_id": "<uuid>" }
```

**Errors:**
- `400` — missing required fields or invalid path
- `422` — ref validation failed (ref does not exist)

---

### `GET /api/runs/{run_id}/progress`

Server-Sent Events stream of progress events for an active or completed run.

**Path param:** `run_id` — UUID format only.

**Event shape** (each event is a JSON object on a `data:` line):
```json
{
  "run_id": "<uuid>",
  "step": "triage | analyze | test_base | test_head | probe_base | probe_head | done | error",
  "status": "started | completed | failed",
  "message": "<human-readable string>",
  "timestamp": "<ISO-8601>"
}
```

**Response:** `200 OK` with `Content-Type: text/event-stream`.

**Errors:**
- `400` — invalid `run_id`
- `404` — run not found

---

### `POST /api/decide`

Save a decision for a probe case. Delegates validation to Lane 4's decision validation service.

**Request body:**
```json
{
  "run_id": "<uuid>",
  "symbol": "<fully.qualified.function.name>",
  "case_id": "<stable case id>",
  "verdict": "intended | unintended | unresolved",
  "rationale": "<string>"
}
```

**Response:** `200 OK`
```json
{
  "file_path": ".bobreviewer/decisions/<symbol>-<head_commit_short>.json",
  "git_command": "git add .bobreviewer/decisions/<file> && git commit -m 'decision: <symbol> — <verdict>'"
}
```

**Errors:**
- `401` — missing or invalid token
- `422` — validation error (e.g., `intended` with empty rationale)
  ```json
  { "error": "<human-readable message>" }
  ```
- `404` — `run_id` not found in saved runs

---

### `GET /`

Serve the developer UI frontend (static assets shipped with the Python package).

**Response:** `200 OK` — `text/html`

---

## Progress Event Contract

Progress events are emitted in two places:
1. **CLI stdout** — newline-delimited JSON during `bobreviewer run`
2. **SSE stream** — via `GET /api/runs/{run_id}/progress`

Both use the same event shape:

```json
{
  "run_id": "<uuid>",
  "step": "triage | analyze | test_base | test_head | probe_base | probe_head | done | error",
  "status": "started | completed | failed",
  "message": "<human-readable string>",
  "timestamp": "<ISO-8601>"
}
```

`step` enum values:
- `triage` — diff classification
- `analyze` — AST caller analysis
- `test_base` / `test_head` — pytest run on base/head worktree
- `probe_base` / `probe_head` — probe execution on base/head worktree
- `done` — run completed successfully
- `error` — run failed with a hard error
