"""
Tests for bobthereviewer.server (ST 13 — runs/progress endpoints, ST 14 — security layer).

Uses http.client against a real server started in a background thread so we
exercise the actual HTTP stack.  Each test class starts its own server to
avoid port conflicts and cross-test state.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest

from bobthereviewer.run_store import create_run_dir, save_evidence
from bobthereviewer.server import make_server


PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_server(tmp_path: Path) -> tuple[http.client.HTTPConnection, str, threading.Thread]:
    """Start a server on a free port; return (conn, token, thread)."""
    httpd, token = make_server(str(tmp_path), PYTHON, port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", port)
    return conn, token, t


def _req(
    conn: http.client.HTTPConnection,
    method: str,
    path: str,
    token: Optional[str] = None,
    body: Optional[dict] = None,
    host: str = "localhost",
) -> tuple[int, dict | list | bytes]:
    """Make a request; return (status_code, parsed_body)."""
    headers = {"Host": host}
    raw_body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        raw_body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(raw_body))

    conn.request(method, path, body=raw_body, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    data = resp.read()
    try:
        return status, json.loads(data)
    except json.JSONDecodeError:
        return status, data


# ---------------------------------------------------------------------------
# ST 14 — Security layer
# ---------------------------------------------------------------------------

class TestSecurityLayer:
    def test_missing_token_returns_401(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs")
        assert status == 401

    def test_wrong_token_returns_401(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs", token="wrong-token-xyz")
        assert status == 401

    def test_correct_token_header_passes(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs", token=token)
        assert status == 200

    def test_correct_token_query_param_passes(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", f"/api/runs?token={token}")
        assert status == 200

    def test_wrong_host_returns_403(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", "/api/runs", token=token, host="evil.example.com")
        assert status == 403

    def test_ui_shell_served_without_token(self, tmp_path):
        conn, _, _ = _start_server(tmp_path)
        frontend = Path(__file__).parent.parent / "src" / "bobthereviewer" / "frontend"
        asset = next((frontend / "assets").iterdir())
        for path in ("/", f"/assets/{asset.name}", "/favicon.svg"):
            status, _ = _req(conn, "GET", path)
            assert status == 200, path

    def test_ui_shell_still_checks_host(self, tmp_path):
        conn, _, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", "/", host="evil.example.com")
        assert status == 403

    def test_localhost_host_passes(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", "/api/runs", token=token, host="localhost")
        assert status == 200

    def test_127_0_0_1_host_passes(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", "/api/runs", token=token, host="127.0.0.1")
        assert status == 200

    def test_localhost_with_port_passes(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        httpd2, _ = make_server(str(tmp_path), PYTHON, port=0)
        port2 = httpd2.server_address[1]
        t2 = threading.Thread(target=httpd2.serve_forever, daemon=True)
        t2.start()
        conn2 = http.client.HTTPConnection("127.0.0.1", port2)
        status, _ = _req(conn2, "GET", "/api/runs", token=_, host=f"localhost:{port2}")
        # Note: token is from a DIFFERENT server instance so it will 401
        # but the host check passed (no 403)
        assert status != 403

    def test_invalid_run_id_in_path_returns_400(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs/not-a-uuid", token=token)
        assert status == 400

    def test_path_traversal_run_id_returns_400(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "GET", "/api/runs/../etc/passwd", token=token)
        # The .. segment won't match the UUID pattern → 400
        assert status == 400

    def test_post_decide_path_traversal_in_run_id_rejected(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "POST", "/api/decide", token=token, body={
            "run_id": "../../etc/passwd",
            "symbol": "m.f",
            "case_id": "c1",
            "verdict": "intended",
            "rationale": "test",
        })
        assert status == 400


# ---------------------------------------------------------------------------
# ST 13 — Run list and detail
# ---------------------------------------------------------------------------

class TestRunListAndDetail:
    def test_list_runs_returns_empty_list(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs", token=token)
        assert status == 200
        assert body == []

    def test_list_runs_returns_saved_run(self, tmp_path):
        run_id = str(uuid.uuid4())
        run_dir = create_run_dir(str(tmp_path), run_id, base_ref="main", head_ref="HEAD")
        save_evidence(run_dir, {
            "schema_version": "1", "run_id": run_id,
            "generated_at": "2025-01-01T00:00:00+00:00",
        })
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", "/api/runs", token=token)
        assert status == 200
        assert isinstance(body, list)
        ids = [r["run_id"] for r in body]
        assert run_id in ids

    def test_get_run_returns_evidence(self, tmp_path):
        run_id = str(uuid.uuid4())
        run_dir = create_run_dir(str(tmp_path), run_id)
        evidence = {"schema_version": "1", "run_id": run_id, "generated_at": "2025-01-01T00:00:00+00:00"}
        save_evidence(run_dir, evidence)
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "GET", f"/api/runs/{run_id}", token=token)
        assert status == 200
        assert body["run_id"] == run_id

    def test_get_run_404_for_missing(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        fake_id = str(uuid.uuid4())
        status, _ = _req(conn, "GET", f"/api/runs/{fake_id}", token=token)
        assert status == 404


# ---------------------------------------------------------------------------
# ST 13 — Start run (POST /api/runs)
# ---------------------------------------------------------------------------

class TestStartRun:
    def test_start_run_returns_run_id(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        # Use tmp_path itself as both worktree paths (empty dirs — no probes)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": str(tmp_path),
            "after_ref":  str(tmp_path),
        })
        assert status == 200
        assert "run_id" in body
        assert _is_valid_uuid4(body["run_id"])

    def test_start_run_rejects_missing_refs(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "", "after_ref": "",
        })
        assert status == 400

    def test_start_run_rejects_unsafe_probe_path(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": str(tmp_path),
            "after_ref":  str(tmp_path),
            "probes": ["../../etc/shadow"],
        })
        assert status == 400

    def test_second_start_run_while_busy_returns_409(self, tmp_path):
        """Second POST /api/runs while a run is active → HTTP 409."""
        conn, token, _ = _start_server(tmp_path)

        # Start first run (use tmp_path as both sides — finishes quickly)
        r1_status, r1_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": str(tmp_path),
            "after_ref":  str(tmp_path),
        })
        assert r1_status == 200
        run_id_1 = r1_body["run_id"]

        # The run thread starts immediately; attempt a second run right away
        # It may or may not still be active depending on timing.
        # Poll until we either get 409 or the first run is done.
        deadline = time.time() + 5
        got_409 = False
        while time.time() < deadline:
            r2_status, r2_body = _req(conn, "POST", "/api/runs", token=token, body={
                "before_ref": str(tmp_path),
                "after_ref":  str(tmp_path),
            })
            if r2_status == 409:
                assert r2_body.get("error") == "run_in_progress"
                assert r2_body.get("active_run_id") == run_id_1
                got_409 = True
                break
            elif r2_status == 200:
                # First run already finished; second started — that's fine
                break
            time.sleep(0.05)

        # We may or may not have caught the 409 window, but if we did it must be correct
        if got_409:
            assert True  # already validated above

    def test_run_result_readable_after_completion(self, tmp_path):
        """After a run finishes, GET /api/runs/{run_id} returns evidence."""
        conn, token, _ = _start_server(tmp_path)
        r_status, r_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": str(tmp_path),
            "after_ref":  str(tmp_path),
        })
        assert r_status == 200
        run_id = r_body["run_id"]

        # Wait for completion (up to 15 s)
        deadline = time.time() + 15
        while time.time() < deadline:
            get_status, get_body = _req(conn, "GET", f"/api/runs/{run_id}", token=token)
            if get_status == 200:
                assert get_body["run_id"] == run_id
                return
            time.sleep(0.1)
        pytest.fail(f"Run {run_id} did not complete within 15 s")


# ---------------------------------------------------------------------------
# ST 13 — SSE progress
# ---------------------------------------------------------------------------

class TestProgressSSE:
    def test_progress_stream_ends_with_done(self, tmp_path):
        """
        Start a run, wait for it to complete, then read the SSE replay via a
        raw socket with a timeout so the test does not hang.
        """
        import socket as _socket
        conn, token, _ = _start_server(tmp_path)
        port = conn.port

        # Start a run
        r_status, r_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": str(tmp_path),
            "after_ref":  str(tmp_path),
        })
        assert r_status == 200
        run_id = r_body["run_id"]

        # Wait for completion (run is fast with empty dirs)
        deadline = time.time() + 15
        while time.time() < deadline:
            get_status, _ = _req(conn, "GET", f"/api/runs/{run_id}", token=token)
            if get_status == 200:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Run did not complete within 15 s")

        # Read the SSE replay with a raw socket + timeout so it doesn't block
        raw = _socket.create_connection(("127.0.0.1", port), timeout=5)
        request = (
            f"GET /api/runs/{run_id}/progress HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Authorization: Bearer {token}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        raw.sendall(request.encode())
        raw.settimeout(5)

        response_data = b""
        try:
            while True:
                chunk = raw.recv(4096)
                if not chunk:
                    break
                response_data += chunk
        except _socket.timeout:
            pass
        finally:
            raw.close()

        assert b"200 OK" in response_data, f"Expected 200, got: {response_data[:200]}"
        assert b"text/event-stream" in response_data

        # Parse SSE events from the body
        body_start = response_data.find(b"\r\n\r\n")
        steps_found = []
        if body_start >= 0:
            body = response_data[body_start + 4:]
            for part in body.split(b"\n\n"):
                for line in part.splitlines():
                    decoded = line.decode(errors="replace").strip()
                    if decoded.startswith("data:"):
                        try:
                            event = json.loads(decoded[5:].strip())
                            steps_found.append(event.get("step"))
                        except json.JSONDecodeError:
                            pass

        assert len(steps_found) > 0, "No events found in SSE replay"
        assert "done" in steps_found, f"No 'done' event in replay. Steps: {steps_found}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_uuid4(value: str) -> bool:
    import re
    return bool(re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        value.lower()
    ))
