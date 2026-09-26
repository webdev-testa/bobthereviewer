# bobreviewer Local Server API Contract

**Owner:** Lane 1 defines; Lane 2 implements; Lane 3 consumes.  
**Transport:** HTTP/1.1, `127.0.0.1` only.  
**Auth:** Every request requires `Authorization: Bearer <token>` or `?token=<token>`. Token is generated per-launch and printed to the terminal.  
**Format:** All request and response bodies are `application/json`.

---

## Security constraints (all required, enforced by Lane 2)

| Constraint | Rule |
|---|---|
| Bind address | `127.0.0.1` only — not `0.0.0.0` |
| `Host` header | Must be `localhost` or `127.0.0.1`; any other value → HTTP 403 |
| Missing/wrong token | HTTP 401 |
| `run_id` parameter | UUID format only (`[0-9a-f-]{36}`); path traversal sequences → HTTP 400 |
| File path parameters | Repo-relative paths only; absolute paths and `..` sequences → HTTP 400 |

---

## Endpoints

### `GET /`
Serve the developer UI frontend (pre-built static assets shipped with the Python package).

---

### `GET /api/runs`
List all saved runs.

**Response 200:**
```json
[
  {
    "run_id": "<uuid>",
    "generated_at": "<ISO-8601>",
    "base_ref": "<ref>",
    "head_ref": "<ref>",
    "base_commit": "<full-sha>",
    "head_commit": "<full-sha>",
    "triage_category": "code | docs-only | tests-only | config-deps | no-semantic-change"
  }
]
```
Returns `[]` when no runs are saved. Each entry matches `contracts/run-metadata.schema.json`.

---

### `GET /api/runs/{run_id}`
Return the full `evidence.json` for the given run.

**Response 200:** The complete evidence bundle matching `contracts/evidence.schema.json`.  
**Response 400:** `run_id` is not a valid UUID or contains traversal sequences.  
**Response 404:** No run with this ID exists in `.bobreviewer/runs/`.

---

### `POST /api/runs`
Start a new review run. Returns immediately; progress is streamed via SSE.

**Request body:**
```json
{
  "before_ref": "<ref string>",
  "after_ref": "<ref string>",
  "probes": ["<repo-relative path>"],
  "prior_run_id": "<uuid or omit>"
}
```
`probes` may be an empty array. `prior_run_id` is optional.

**Response 202:**
```json
{ "run_id": "<uuid>" }
```

**Response 400:** Invalid ref format or path traversal in probe path.  
**Response 409:** A run is already active (one active run at a time).

---

### `GET /api/runs/{run_id}/progress`
Stream progress events for an active or completed run as Server-Sent Events.

**Response:** `Content-Type: text/event-stream`  
Each event is a JSON object matching `contracts/progress-event.schema.json`, serialised as:
```
data: {"run_id":"...","step":"analyze","status":"started","message":"...","timestamp":"..."}\n\n
```
The stream closes after a `done` or `error` event. Clients may reconnect; completed runs replay their full event history.

---

### `POST /api/decide`
Save a decision for a specific probe case result. Delegates to Lane 4's decision validation service.

**Request body:**
```json
{
  "run_id": "<uuid>",
  "symbol": "<fully.qualified.name>",
  "probe_file": "<repo-relative path>",
  "case_id": "<stable case id>",
  "verdict": "intended | unintended | unresolved",
  "rationale": "<string>"
}
```

**Response 200:**
```json
{
  "file_path": ".bobreviewer/decisions/<symbol>-<head_commit_short>.json",
  "git_command": "git add .bobreviewer/decisions/<file> && git commit -m \"chore: add decision for <symbol>\""
}
```

**Response 400:** `run_id` not found or case_id not found in saved evidence.  
**Response 422:** Validation error from Lane 4's service (e.g. `intended` verdict with empty rationale).
```json
{
  "error": "validation_failed",
  "detail": "<human-readable description>"
}
```

---

## One-active-run constraint

The server supports exactly one repository at a time and one active run at a time. Attempting to start a second run while one is active returns HTTP 409. This is a local developer tool, not a server.

---

## Change process

Any change to this contract requires Lane 1 approval before Lane 2 or Lane 3 implements it. New endpoints or modified response shapes must be reflected in this file before any lane builds against them.
