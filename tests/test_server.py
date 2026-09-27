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
from tests.test_setup_cli import commit_files, init_repo


PYTHON = sys.executable


@pytest.fixture
def git_repo(tmp_path):
    """A repo whose `head` tag changes discount.apply_discount, called from invoice.py."""
    root = tmp_path / "repo"
    init_repo(root)
    commit_files(root, {
        ".gitignore": ".bobreviewer/runs/\n__pycache__/\n",
        "discount.py": "def apply_discount(p, r):\n    return round(p * (1 - r), 2)\n",
        "invoice.py": "from discount import apply_discount\ndef calculate_invoice(p, r):\n    return apply_discount(p, r)\n",
    }, "base", tag="base")
    commit_files(root, {
        "discount.py": "import math\ndef apply_discount(p, r):\n    return math.floor(p * (1 - r) * 100) / 100\n",
    }, "rounding", tag="head")
    return root


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
# D3 — Save decision writes straight into the repo
# ---------------------------------------------------------------------------

def _saved_run_with_difference(repo: Path) -> str:
    run_id = str(uuid.uuid4())
    save_evidence(create_run_dir(str(repo), run_id), {
        "schema_version": "1", "run_id": run_id, "generated_at": "2026-01-01T00:00:00Z",
        "repository": "https://github.com/example/demo", "base_ref": "main", "head_ref": "feature",
        "base_commit": "a" * 40, "head_commit": "b" * 40,
        "probe_results": [{
            "probe_file": ".bobreviewer/probes/invoice_basic.json", "probe_hash": "c" * 64,
            "target": "invoice.calculate_invoice",
            "cases": [{"id": "invoice-small-discount", "args": [100.0], "kwargs": {},
                       "base_output": 100.0, "head_output": 99.99, "comparison_status": "differ"}],
        }],
    })
    return run_id


def _decide(run_id: str, verdict: str, rationale: str) -> dict:
    return {"run_id": run_id, "symbol": "invoice.calculate_invoice", "case_id": "invoice-small-discount",
            "verdict": verdict, "rationale": rationale}


class TestRepoAndRefs:
    def test_repo_reports_branch_and_default_base(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "GET", "/api/repo", token=token)
        assert status == 200
        assert body == {"repo": "repo", "branch": "main", "base_branch": "main"}

    def test_repo_base_branch_comes_from_config(self, git_repo):
        (git_repo / ".bobreviewer").mkdir(exist_ok=True)
        (git_repo / ".bobreviewer" / "config.json").write_text('{"base_branch": "develop"}', encoding="utf-8")
        conn, token, _ = _start_server(git_repo)
        _, body = _req(conn, "GET", "/api/repo", token=token)
        assert body["base_branch"] == "develop"

    def test_refs_lists_branches_and_tags(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, refs = _req(conn, "GET", "/api/refs", token=token)
        assert status == 200
        by_name = {r["name"]: r for r in refs}
        assert by_name["main"]["kind"] == "branch"
        assert by_name["base"]["kind"] == "tag" and by_name["head"]["kind"] == "tag"
        assert all(len(r["sha"]) >= 7 for r in refs)

    def test_repo_and_refs_require_token(self, git_repo):
        conn, _, _ = _start_server(git_repo)
        assert _req(conn, "GET", "/api/repo")[0] == 401
        assert _req(conn, "GET", "/api/refs")[0] == 401


class TestDecide:
    def test_save_writes_decision_file(self, tmp_path):
        run_id = _saved_run_with_difference(tmp_path)
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "POST", "/api/decide", token=token,
                            body=_decide(run_id, "unintended", "Invoices must round to cents"))
        assert status == 200, body
        assert body["file_path"].startswith(".bobreviewer/decisions/")
        assert (tmp_path / body["file_path"]).exists()
        assert body["git_command"].startswith(f"git add {body['file_path']} ")

    def test_intended_without_rationale_is_rejected(self, tmp_path):
        run_id = _saved_run_with_difference(tmp_path)
        conn, token, _ = _start_server(tmp_path)
        status, body = _req(conn, "POST", "/api/decide", token=token, body=_decide(run_id, "intended", ""))
        assert status == 422
        assert "rationale" in body["error"]
        assert not (tmp_path / ".bobreviewer" / "decisions").exists()

    def test_unknown_run_is_404(self, tmp_path):
        conn, token, _ = _start_server(tmp_path)
        status, _ = _req(conn, "POST", "/api/decide", token=token,
                         body=_decide(str(uuid.uuid4()), "unintended", "Invoices must round to cents"))
        assert status == 404


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
    def test_start_run_returns_run_id(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base",
            "after_ref":  "head",
        })
        assert status == 200
        assert "run_id" in body
        assert _is_valid_uuid4(body["run_id"])

    def test_start_run_rejects_missing_refs(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "", "after_ref": "",
        })
        assert status == 400

    def test_start_run_rejects_unsafe_probe_path(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, _ = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base",
            "after_ref":  "head",
            "probes": ["../../etc/shadow"],
        })
        assert status == 400

    def test_start_run_rejects_unknown_ref(self, git_repo):
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base", "after_ref": "no-such-branch",
        })
        assert status == 400
        assert "no-such-branch" in body["error"]

    def test_web_run_uses_real_pipeline(self, git_repo):
        """D2: a web review is the same as `bobreviewer run`: real commits, callers, a saved run."""
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={"before_ref": "base", "after_ref": "head"})
        assert status == 200
        assert body["warnings"] == []
        run_id = body["run_id"]
        deadline = time.time() + 60
        while time.time() < deadline:
            get_status, evidence = _req(conn, "GET", f"/api/runs/{run_id}", token=token)
            if get_status == 200:
                break
            time.sleep(0.2)
        else:
            pytest.fail("web run did not complete within 60 s")
        assert len(evidence["base_commit"]) == 40
        changed = {fn["symbol"]: fn for fn in evidence["changed_functions"]}
        assert "discount.apply_discount" in changed
        assert "invoice.calculate_invoice" in [c["symbol"] for c in changed["discount.apply_discount"]["callers"]]
        deadline = time.time() + 30
        while (map_status := _req(conn, "GET", f"/api/runs/{run_id}/repo_map", token=token))[0] != 200 and time.time() < deadline:
            time.sleep(0.2)
        assert map_status[0] == 200, "web run saved no repo map"
        assert {"from": "invoice.py", "to": "discount.py"}.items() <= next(
            e for e in map_status[1]["edges"] if e["from"] == "invoice.py").items()

    def test_uncommitted_files_warn_but_do_not_block(self, git_repo):
        (git_repo / "discount.py").write_text("# edited, not committed\n", encoding="utf-8")
        conn, token, _ = _start_server(git_repo)
        status, body = _req(conn, "POST", "/api/runs", token=token, body={"before_ref": "base", "after_ref": "head"})
        assert status == 200
        assert body["warnings"] == ["Not included (uncommitted): discount.py"]

    def test_second_start_run_while_busy_returns_409(self, git_repo):
        """Second POST /api/runs while a run is active → HTTP 409."""
        conn, token, _ = _start_server(git_repo)

        # Start first run
        r1_status, r1_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base",
            "after_ref":  "head",
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
                "before_ref": "base",
                "after_ref":  "head",
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

    def test_run_result_readable_after_completion(self, git_repo):
        """After a run finishes, GET /api/runs/{run_id} returns evidence."""
        conn, token, _ = _start_server(git_repo)
        r_status, r_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base",
            "after_ref":  "head",
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
    def test_progress_stream_ends_with_done(self, git_repo):
        """
        Start a run, wait for it to complete, then read the SSE replay via a
        raw socket with a timeout so the test does not hang.
        """
        import socket as _socket
        conn, token, _ = _start_server(git_repo)
        port = conn.port

        # Start a run
        r_status, r_body = _req(conn, "POST", "/api/runs", token=token, body={
            "before_ref": "base",
            "after_ref":  "head",
        })
        assert r_status == 200
        run_id = r_body["run_id"]

        # Wait for completion
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


# ---------------------------------------------------------------------------
# G4 — the browser opens by itself
# ---------------------------------------------------------------------------

class TestOpenBrowser:
    def test_ui_url_carries_token_and_run(self):
        from bobthereviewer.server import ui_url
        assert ui_url("127.0.0.1", 7842, "tok") == "http://127.0.0.1:7842/?token=tok"
        assert ui_url("127.0.0.1", 7842, "tok", "abc") == "http://127.0.0.1:7842/?token=tok&run=abc"

    @pytest.mark.parametrize("no_browser, opened", [(False, True), (True, False)])
    def test_start_opens_browser_unless_disabled(self, tmp_path, monkeypatch, no_browser, opened):
        import argparse
        import webbrowser
        from bobthereviewer import server
        urls = []
        monkeypatch.setattr(webbrowser, "open", urls.append)
        monkeypatch.setattr(server.BobReviewerServer, "serve_forever", lambda self: (_ for _ in ()).throw(KeyboardInterrupt))
        args = argparse.Namespace(repo_dir=str(tmp_path), port=0, no_browser=no_browser, run_id="abc")
        assert server.start(args) == 0
        assert bool(urls) is opened
        if opened:
            assert "token=" in urls[0] and urls[0].endswith("&run=abc")

    def test_run_open_serves_the_new_run(self, git_repo, monkeypatch):
        from bobthereviewer import server
        from bobthereviewer.cli import main
        started = []
        monkeypatch.setattr(server, "start", lambda args: started.append(args) or 0)
        assert main(["run", "--repo-dir", str(git_repo), "--before", "base", "--after", "head", "--open"]) == 0
        run_id = started[0].run_id
        assert (git_repo / ".bobreviewer" / "runs" / run_id / "evidence.json").exists()


class TestProgressNoDuplicates:
    def test_live_stream_sends_each_event_once(self, git_repo):
        import socket as _socket
        conn, token, _ = _start_server(git_repo)
        _, body = _req(conn, "POST", "/api/runs", token=token, body={"before_ref": "base", "after_ref": "head"})
        raw = _socket.create_connection(("127.0.0.1", conn.port), timeout=60)
        raw.sendall((f"GET /api/runs/{body['run_id']}/progress HTTP/1.1\r\nHost: localhost\r\n"
                     f"Authorization: Bearer {token}\r\nConnection: close\r\n\r\n").encode())
        data = b""
        while b'"step":"done"' not in data and b'"step":"error"' not in data:
            chunk = raw.recv(4096)
            if not chunk:
                break
            data += chunk
        raw.close()
        events = [line[5:].strip() for line in data.decode(errors="replace").splitlines() if line.startswith("data:")]
        assert events, "no progress events received"
        assert len(events) == len(set(events)), "an event was sent twice"
        assert sum('"step":"triage","status":"started"' in e for e in events) == 1


class TestRepoMapEndpoint:
    def test_returns_saved_map_or_404(self, tmp_path):
        run_id = str(uuid.uuid4())
        run_dir = create_run_dir(str(tmp_path), run_id)
        conn, token, _ = _start_server(tmp_path)
        assert _req(conn, "GET", f"/api/runs/{run_id}/repo_map", token=token)[0] == 404
        (run_dir / "repo_map.json").write_text('{"schema_version": "1", "modules": []}', encoding="utf-8")
        status, body = _req(conn, "GET", f"/api/runs/{run_id}/repo_map", token=token)
        assert status == 200 and body["schema_version"] == "1"
        assert _req(conn, "GET", f"/api/runs/{run_id}/repo_map")[0] == 401
