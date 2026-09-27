"""
bobthereviewer.server
==================
Localhost-only HTTP server that powers the developer UI.

Security constraints (all enforced in _check_security before any handler):
  - Binds to 127.0.0.1 only (never 0.0.0.0)
  - Host header must be localhost or 127.0.0.1 → HTTP 403
  - Bearer token required on /api/* (per-launch, generated with secrets) → HTTP 401;
    the UI shell (/, /assets/*, /favicon.svg, /icons.svg) is served without it
  - run_id path segments must match UUID4 format → HTTP 400
  - File-path body params: no .., no leading /, no null bytes → HTTP 400

Concurrency:
  - One active run at a time enforced by a threading.Lock + active_run_id flag
  - Active run executes in a daemon thread
  - SSE endpoint polls a per-run queue.Queue drained by the run thread
  - Late-connecting SSE clients replay from events.jsonl

Endpoints:
  GET  /api/runs                        → list saved runs
  GET  /api/runs/{run_id}               → evidence.json for run
  POST /api/runs                        → start a new run (returns {run_id} immediately)
  GET  /api/runs/{run_id}/progress      → SSE progress stream
  POST /api/decide                      → save a proposed decision (same code path as `bobreviewer decide`)
  GET  /                                → serve developer UI frontend
"""

from __future__ import annotations

import http.server
import json
import queue
import re
import secrets
import sys
import threading
import traceback
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

from bobthereviewer.run_store import (
    RunNotFoundError,
    create_run_dir,
    get_run,
    list_runs,
    save_evidence,
)
from bobthereviewer.decide_cmd import DecideError, decide_from_run
from bobthereviewer.progress import make_emitter, replay_events


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_VALID_HOST_RE = re.compile(r"^(localhost|127\.0\.0\.1)(:\d+)?$")

# Paths the browser loads for the UI shell itself; served without the token.
_STATIC_ROOT_FILES = ("", "/favicon.svg", "/icons.svg")


def _is_valid_uuid4(value: str) -> bool:
    return bool(_UUID4_RE.match(value.lower()))


def _is_safe_repo_path(value: str) -> bool:
    """Return False if path is absolute, contains .., or contains null bytes."""
    if "\x00" in value:
        return False
    if value.startswith("/") or value.startswith("\\"):
        return False
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        return False
    return True


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Server state (module-level; single process, single repo per server instance)
# ---------------------------------------------------------------------------

class _ServerState:
    """Mutable state shared between handler instances and the run thread."""

    def __init__(self) -> None:
        self.repo_dir: str = ""
        self.python_exe: str = ""
        self.token: str = ""
        # One-run-at-a-time
        self._lock = threading.Lock()
        self._active_run_id: Optional[str] = None
        # Per-run queues for SSE: run_id → Queue
        self._run_queues: dict[str, "queue.Queue[Optional[dict]]"] = {}

    def start_run(self, run_id: str) -> bool:
        """Acquire the active-run lock.  Returns True if acquired, False if busy."""
        with self._lock:
            if self._active_run_id is not None:
                return False
            self._active_run_id = run_id
            self._run_queues[run_id] = queue.Queue()
            return True

    def finish_run(self, run_id: str) -> None:
        with self._lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            q = self._run_queues.get(run_id)
            if q:
                q.put(None)  # sentinel: stream is done

    def active_run_id(self) -> Optional[str]:
        with self._lock:
            return self._active_run_id

    def get_queue(self, run_id: str) -> Optional["queue.Queue[Optional[dict]]"]:
        return self._run_queues.get(run_id)

    def put_event(self, run_id: str, event: dict) -> None:
        q = self._run_queues.get(run_id)
        if q:
            q.put(event)


# ---------------------------------------------------------------------------
# Custom HTTPServer subclass that carries per-instance state
# ---------------------------------------------------------------------------

class BobReviewerServer(HTTPServer):
    """HTTPServer subclass that owns the mutable server state."""

    def __init__(self, server_address, handler_class, repo_dir: str, python_exe: str, token: str):
        super().__init__(server_address, handler_class)
        self.state = _ServerState()
        self.server_token = token
        self.repo_dir = repo_dir
        self.python_exe = python_exe


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class BobReviewerHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the bobthereviewer developer UI server."""

    # These are accessed via self.server (a BobReviewerServer instance)
    @property
    def server_token(self) -> str:
        return self.server.server_token  # type: ignore[attr-defined]

    @property
    def repo_dir(self) -> str:
        return self.server.repo_dir  # type: ignore[attr-defined]

    @property
    def python_exe(self) -> str:
        return self.server.python_exe  # type: ignore[attr-defined]

    @property
    def _state(self) -> _ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Suppress default access log to avoid cluttering terminal
        pass

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _check_security(self, require_token: bool = True) -> bool:
        """
        Check Host header, bearer token.
        Returns True if the request is allowed; writes error response and
        returns False otherwise.
        """
        # Host header check
        host = self.headers.get("Host", "")
        if not _VALID_HOST_RE.match(host):
            self._send_json(403, {"error": "forbidden host"})
            return False

        # The page's own <script>/<link> requests can't carry the token.
        if not require_token:
            return True

        # Token check: Authorization header or ?token= query param
        auth = self.headers.get("Authorization", "")
        token_from_header = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""

        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        token_from_query = qs.get("token", [""])[0]

        supplied_token = token_from_header or token_from_query
        if not secrets.compare_digest(supplied_token, self.server_token):
            self._send_json(401, {"error": "unauthorized"})
            return False

        return True

    def _validate_run_id_segment(self, run_id: str) -> bool:
        """Return True if valid; send 400 and return False otherwise."""
        if not _is_valid_uuid4(run_id):
            self._send_json(400, {"error": "invalid run_id format"})
            return False
        return True

    def _read_body_json(self) -> Optional[dict]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return None

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _route(self) -> tuple[str, list[str]]:
        """Parse path into (clean_path, segments)."""
        parsed = urllib.parse.urlparse(self.path)
        clean = parsed.path.rstrip("/")
        segments = [s for s in clean.split("/") if s]
        return clean, segments

    def _reject_path_traversal(self) -> bool:
        """
        Return True (and send 400) if the raw path contains traversal sequences.
        Must be called before routing so ``..`` in any position is caught.
        """
        raw = urllib.parse.urlparse(self.path).path
        if ".." in raw.split("/"):
            self._send_json(400, {"error": "path traversal not allowed"})
            return True
        return False

    def do_GET(self) -> None:
        clean, segments = self._route()
        is_static = clean in _STATIC_ROOT_FILES or segments[:1] == ["assets"]
        if not self._check_security(require_token=not is_static):
            return
        if self._reject_path_traversal():
            return

        if clean == "" or clean == "/":
            self._handle_static_index()
            return

        if clean in _STATIC_ROOT_FILES:
            self._handle_static_asset(clean)
            return

        if segments[:1] == ["api"] and segments[1:2] == ["runs"]:
            if len(segments) == 2:
                self._handle_list_runs()
            elif len(segments) == 3:
                run_id = segments[2]
                if not self._validate_run_id_segment(run_id):
                    return
                self._handle_get_run(run_id)
            elif len(segments) == 4 and segments[3] == "progress":
                run_id = segments[2]
                if not self._validate_run_id_segment(run_id):
                    return
                self._handle_progress(run_id)
            else:
                self._send_json(404, {"error": "not found"})
            return

        # Static assets under /assets/
        if segments[:1] == ["assets"]:
            self._handle_static_asset(clean)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._check_security():
            return
        if self._reject_path_traversal():
            return
        clean, segments = self._route()

        if segments == ["api", "runs"]:
            self._handle_start_run()
            return

        if segments == ["api", "decide"]:
            self._handle_decide()
            return

        self._send_json(404, {"error": "not found"})

    # ------------------------------------------------------------------
    # Run list / detail
    # ------------------------------------------------------------------

    def _handle_list_runs(self) -> None:
        runs = list_runs(self.repo_dir)
        self._send_json(200, runs)

    def _handle_get_run(self, run_id: str) -> None:
        try:
            evidence = get_run(self.repo_dir, run_id)
            self._send_json(200, evidence)
        except RunNotFoundError:
            self._send_json(404, {"error": "run not found"})

    # ------------------------------------------------------------------
    # Start run (POST /api/runs)
    # ------------------------------------------------------------------

    def _handle_start_run(self) -> None:
        body = self._read_body_json()
        if body is None:
            return

        before_ref = body.get("before_ref", "").strip()
        after_ref = body.get("after_ref", "").strip()
        probes = body.get("probes", [])
        prior_run_id = body.get("prior_run_id")

        if not before_ref or not after_ref:
            self._send_json(400, {"error": "before_ref and after_ref are required"})
            return

        # Validate prior_run_id if supplied
        if prior_run_id is not None and not _is_valid_uuid4(str(prior_run_id)):
            self._send_json(400, {"error": "invalid prior_run_id format"})
            return

        # Validate probe paths
        for p in probes:
            if not _is_safe_repo_path(p):
                self._send_json(400, {"error": f"unsafe probe path: {p!r}"})
                return

        # One-run-at-a-time enforcement
        run_id = str(uuid.uuid4())
        acquired = self._state.start_run(run_id)
        if not acquired:
            active = self._state.active_run_id()
            self._send_json(409, {"error": "run_in_progress", "active_run_id": active})
            return

        # Create run dir before returning so the progress endpoint can open events.jsonl
        run_dir = create_run_dir(
            self.repo_dir, run_id,
            base_ref=before_ref,
            head_ref=after_ref,
        )

        # Snapshot the server attributes for the thread (handler instance may be GC'd)
        repo_dir = self.repo_dir
        python_exe = self.python_exe
        state = self._state  # capture per-server state, not a module global

        def _run_thread() -> None:
            events_path = str(run_dir / "events.jsonl")
            emit = make_emitter(run_id=run_id, events_path=events_path, mode="server")

            def _put(event: dict) -> None:
                state.put_event(run_id, event)

            # Wrap emit so events also go to the SSE queue
            def _emit(step: str, status: str, message: str) -> None:
                emit(step, status, message)
                # Build the same event dict for the SSE queue
                event = {
                    "run_id": run_id,
                    "step": step,
                    "status": status,
                    "message": message,
                    "timestamp": _now_iso(),
                }
                _put(event)

            try:
                # ---- triage (stub: always "code", not skipped) ----
                _emit("triage", "started", "Classifying diff")
                triage = {"category": "code", "skipped": False, "skip_reason": None}
                _emit("triage", "completed", "Category: code")

                # ---- probe runner ----
                from bobthereviewer.probe_runner import run_probes
                from bobthereviewer.test_runner import run_tests

                # Resolve prior report if supplied
                prior_report = None
                if prior_run_id:
                    try:
                        prior_report = get_run(repo_dir, str(prior_run_id))
                    except RunNotFoundError:
                        pass

                # For now the server receives worktree paths as the refs themselves
                # (Lane 1 will eventually create actual worktrees; for integration
                # testing the refs are treated as directory paths to the project)
                base_wt = before_ref
                head_wt = after_ref

                probe_results, pr_run_id = run_probes(
                    base_wt, head_wt, python_exe,
                    triage, _emit,
                    prior_report=prior_report,
                )

                test_results, frozen_suite_hash = run_tests(
                    base_wt, head_wt, python_exe,
                    triage, _emit,
                )

                _emit("done", "completed", "Review complete")

                evidence = {
                    "schema_version": "1",
                    "run_id": run_id,
                    "generated_at": _now_iso(),
                    "repository": "",
                    "base_ref": before_ref,
                    "head_ref": after_ref,
                    "base_commit": "",
                    "head_commit": "",
                    "prior_run_id": pr_run_id,
                    "ci_run_url": None,
                    "frozen_suite_hash": frozen_suite_hash,
                    "triage": triage,
                    "analysis_limits": {"max_hops": 2, "notes": []},
                    "changed_functions": [],
                    "test_results": test_results,
                    "probe_results": probe_results,
                    "decisions": [],
                }
                save_evidence(run_dir, evidence)

            except Exception:
                _emit("error", "failed", traceback.format_exc())
            finally:
                state.finish_run(run_id)

        t = threading.Thread(target=_run_thread, daemon=True)
        t.start()

        self._send_json(200, {"run_id": run_id})

    # ------------------------------------------------------------------
    # SSE progress stream (GET /api/runs/{run_id}/progress)
    # ------------------------------------------------------------------

    def _handle_progress(self, run_id: str) -> None:
        # Check the run directory exists
        run_dir = Path(self.repo_dir) / ".bobreviewer" / "runs" / run_id
        events_path = run_dir / "events.jsonl"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _send_sse(event: dict) -> bool:
            """Send one SSE event.  Returns False on broken pipe."""
            try:
                data = json.dumps(event, separators=(",", ":"))
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        # Replay past events first (for late-connecting clients)
        for event in replay_events(str(events_path)):
            if not _send_sse(event):
                return
            if event.get("step") in ("done", "error"):
                return

        # Stream live events
        q = self._state.get_queue(run_id)
        if q is None:
            # Run is complete; nothing more to stream
            return

        while True:
            try:
                event = q.get(timeout=1)
            except queue.Empty:
                continue

            if event is None:  # sentinel
                return

            if not _send_sse(event):
                return

            if event.get("step") in ("done", "error"):
                return

    # ------------------------------------------------------------------
    # Decision endpoint (POST /api/decide)
    # ------------------------------------------------------------------

    def _handle_decide(self) -> None:
        body = self._read_body_json()
        if body is None:
            return

        run_id = body.get("run_id", "")
        symbol = body.get("symbol", "")
        case_id = body.get("case_id", "")
        verdict = body.get("verdict", "")
        rationale = body.get("rationale", "")

        if not all([run_id, symbol, case_id, verdict]):
            self._send_json(400, {"error": "run_id, symbol, case_id, and verdict are required"})
            return

        if not _is_valid_uuid4(run_id):
            self._send_json(400, {"error": "invalid run_id format"})
            return

        try:
            rel_path, git_command = decide_from_run(Path(self.repo_dir), run_id, symbol, case_id, verdict, rationale)
        except DecideError as exc:
            self._send_json(exc.status, {"error": str(exc)})
            return
        self._send_json(200, {"file_path": rel_path.as_posix(), "git_command": git_command})

    # ------------------------------------------------------------------
    # Static asset serving (GET /)
    # ------------------------------------------------------------------

    def _frontend_dir(self) -> Path:
        return Path(__file__).parent / "frontend"

    def _handle_static_index(self) -> None:
        index = self._frontend_dir() / "index.html"
        if not index.exists():
            msg = b"Developer UI not built. Run `npm run build` in `web/`."
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_static_asset(self, clean_path: str) -> None:
        # Reject path traversal
        if ".." in clean_path or clean_path.startswith("//"):
            self._send_json(400, {"error": "invalid path"})
            return

        rel = clean_path.lstrip("/")
        asset = self._frontend_dir() / rel
        try:
            asset = asset.resolve()
            frontend_resolved = self._frontend_dir().resolve()
            # Ensure the resolved path is still inside frontend/
            asset.relative_to(frontend_resolved)
        except (ValueError, OSError):
            self._send_json(400, {"error": "invalid path"})
            return

        if not asset.exists():
            self._send_json(404, {"error": "asset not found"})
            return

        ext = asset.suffix.lower()
        content_types = {
            ".html": "text/html",
            ".js":   "application/javascript",
            ".css":  "text/css",
            ".json": "application/json",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
        }
        ct = content_types.get(ext, "application/octet-stream")
        data = asset.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_server(
    repo_dir: str,
    python_exe: str,
    port: int = 5173,
) -> tuple["BobReviewerServer", str]:
    """
    Create and return ``(BobReviewerServer, token)``.

    The server binds to ``127.0.0.1:<port>`` only.
    ``token`` is a per-launch random token; callers must print it.
    Each call returns a completely independent server with its own state.
    """
    token = secrets.token_urlsafe(32)
    httpd = BobReviewerServer(
        ("127.0.0.1", port),
        BobReviewerHandler,
        repo_dir=repo_dir,
        python_exe=python_exe,
        token=token,
    )
    return httpd, token


# ---------------------------------------------------------------------------
# Lane 1 CLI integration — `cli.cmd_ui` calls `server.start(args)`
# ---------------------------------------------------------------------------

def start(args: Any = None, port: int | None = None) -> int:
    """Serve the local developer UI and block until interrupted.

    The CLI (Lane 1) owns argument parsing and calls this; the server owns binding,
    authentication and confinement. Binds to 127.0.0.1 only and prints the launch token the
    browser must present, so a page on another origin cannot drive the local API.
    """
    import argparse
    import os
    import webbrowser

    if args is None:
        args = argparse.Namespace()
    repo_dir = str(getattr(args, "repo_dir", None) or getattr(args, "repo", None) or os.getcwd())
    if port is None:
        port = int(getattr(args, "port", None) or 5173)

    configured = getattr(args, "python", None)
    if configured:
        python_exe = str(configured)
    else:
        candidate = Path(repo_dir) / ".venv" / "bin" / "python"
        python_exe = str(candidate) if candidate.exists() else sys.executable

    httpd, token = make_server(repo_dir, python_exe, port)
    host, bound_port = httpd.server_address[:2]
    url = f"http://{host}:{bound_port}/?token={token}"
    print(f"bobthereviewer ui — serving {repo_dir}")
    print(f"  open: {url}")
    print("  local only (127.0.0.1); press Ctrl+C to stop.")
    if getattr(args, "open", False):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a browser that will not open is not fatal
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        httpd.server_close()
    return 0
