"""Drive the real CLI against a loopback API; never use a real account or GitHub."""

from __future__ import annotations

import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

COMPANY = "a" * 24
REPO = "b" * 24
JOB = "c" * 24


def repo_row() -> dict[str, Any]:
    return {
        "id": REPO,
        "owner": "acme",
        "name": "api",
        "companyId": COMPANY,
        "branch": "main",
        "defaultBranch": "main",
        "private": True,
        "aiEnabled": False,
        "baseUrl": None,
        "needsBaseUrl": True,
        "lastScanJobId": JOB,
    }


def job_row() -> dict[str, Any]:
    return {
        "id": JOB,
        "repoId": REPO,
        "status": "done",
        "progress": 100,
        "stats": {"filesScanned": 4},
        "errors": [],
        "commitSha": "commit123",
        "collections": {
            "created": [{"id": "d" * 24, "name": "Payments"}],
            "updated": [],
            "unchanged": [],
            "removed": [],
        },
    }


@dataclass
class Api:
    url: str = ""
    rows: list[dict[str, Any]] = field(default_factory=lambda: [repo_row()])
    scope: str | None = COMPANY
    job: dict[str, Any] = field(default_factory=job_row)
    requests: list[tuple[str, str, dict[str, Any] | None]] = field(default_factory=list)
    errors: dict[str, tuple[int, str]] = field(default_factory=dict)
    queue_full: bool = False
    already_running: bool = False

    @property
    def env(self) -> dict[str, str]:
        return {"ELVA_BASE_URL": self.url, "ELVA_TOKEN": "qa-local-only", "ELVA_WORKSPACE": COMPANY}


@pytest.fixture
def api() -> Iterator[Api]:
    state = Api()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def handle_request(self) -> None:
            body = None
            if self.command == "POST":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.command, self.path, body))
            assert self.headers.get("Authorization") == "Bearer qa-local-only"
            assert self.headers.get("X-Elva-Client") == "cli"
            status = 200
            data: dict[str, Any] | None = None
            if self.path in state.errors:
                status, message = state.errors[self.path]
                data = {"message": message}
            elif self.command == "GET" and self.path == f"/api/repos?companyId={COMPANY}":
                data = {"companyId": state.scope, "repos": state.rows}
            elif self.command == "POST" and self.path == "/api/repos":
                assert body is not None
                status = 201
                data = {
                    **repo_row(),
                    "branch": body.get("branch", "main"),
                    "aiEnabled": body["aiEnabled"],
                    "scanJobId": None if state.queue_full else JOB,
                    "scanQueueError": "queue_full" if state.queue_full else None,
                    "alreadyRunning": state.already_running,
                }
            elif self.command == "POST" and self.path == f"/api/repos/{REPO}/rescan":
                status = 202
                data = {"scanJobId": JOB, "alreadyRunning": state.already_running}
            elif self.command == "GET" and self.path == f"/api/catalog/jobs/{JOB}":
                data = state.job
            else:
                status, data = 404, {"message": "Unexpected test route"}
            encoded = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = handle_request  # noqa: N815
        do_POST = handle_request  # noqa: N815

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_list_is_scoped_and_serializable(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--json", "repo", "list", env=api.env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["company_id"] == COMPANY
    assert data["repositories"][0]["last_scan_job_id"] == JOB
    assert len(api.requests) == 1


@pytest.mark.parametrize("ai_flag,expected", [(None, False), ("--ai", True), ("--no-ai", False)])
def test_connect_resolves_clone_url_and_explicit_preferences(
    api: Api,
    run: Callable[..., subprocess.CompletedProcess[str]],
    ai_flag: str | None,
    expected: bool,
) -> None:
    api.rows = []
    args = [
        "--yes",
        "--json",
        "repo",
        "connect",
        "git@github.com:acme/api.git",
        "--branch",
        "release/v2",
    ]
    result = run(*args, *([ai_flag] if ai_flag else []), env=api.env)
    assert result.returncode == 0, result.stderr
    assert api.requests[-1] == (
        "POST",
        "/api/repos",
        {
            "owner": "acme",
            "name": "api",
            "branch": "release/v2",
            "aiEnabled": expected,
            "companyId": COMPANY,
        },
    )
    assert json.loads(result.stdout)["scan_job_id"] == JOB


def test_reconnect_preserves_branch_and_ai(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.rows[0].update(branch="develop", aiEnabled=True)
    result = run("--yes", "repo", "connect", "ACME/API", env=api.env)
    assert result.returncode == 0, result.stderr
    body = api.requests[-1][2]
    assert body and body["branch"] == "develop" and body["aiEnabled"] is True


@pytest.mark.parametrize("reference", ["acme/api", "https://github.com/acme/api.git", REPO.upper()])
def test_sync_wait_reports_collection_results(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], reference: str
) -> None:
    result = run("--yes", "--json", "repo", "sync", reference, "--wait", env=api.env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["job"]["collections"]["created"][0]["name"] == "Payments"
    assert data["job"]["commit_sha"] == "commit123"
    assert data["error"] is None
    assert "100% done" in result.stderr
    assert api.requests[1] == ("POST", f"/api/repos/{REPO}/rescan", {"companyId": COMPANY})


def test_already_running_reuses_job(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.already_running = True
    result = run("--yes", "--json", "repo", "sync", "acme/api", env=api.env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["already_running"] is True
    assert len(api.requests) == 2


@pytest.mark.parametrize("command", ["connect", "sync"])
def test_ci_requires_yes_before_mutation(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], command: str
) -> None:
    result = run("repo", command, "acme/api", env=api.env)
    assert result.returncode == 2, result.stderr
    assert "--yes" in result.stderr
    assert all(method == "GET" for method, _, _ in api.requests)


@pytest.mark.parametrize("broken_scope", ["missing", "wrong_row"])
def test_unscoped_api_refused_before_writes(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], broken_scope: str
) -> None:
    if broken_scope == "missing":
        api.scope = None
    else:
        api.rows[0]["companyId"] = "f" * 24
    result = run("--yes", "repo", "sync", REPO, env=api.env)
    assert result.returncode == 5, result.stderr
    assert "ELVA_REPO_SCOPE" in result.stderr
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    "message",
    [
        "Connect your GitHub account before using this feature.",
        "GitHub token revoked, please reconnect",
    ],
)
def test_github_auth_failure_does_not_refresh_elva(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], message: str
) -> None:
    api.errors[f"/api/repos?companyId={COMPANY}"] = (401, message)
    result = run("repo", "list", env=api.env)
    assert result.returncode == 3, result.stderr
    assert "ELVA_GITHUB_AUTH" in result.stderr
    assert "web app" in result.stderr
    assert "auth login" not in result.stderr
    assert len(api.requests) == 1


def test_partial_connection_on_queue_full(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.queue_full = True
    result = run("--yes", "--json", "repo", "connect", "acme/api", "--wait", env=api.env)
    assert result.returncode == 5, result.stderr
    data = json.loads(result.stdout)
    assert data["repository"]["id"] == REPO and data["scan_job_id"] is None
    assert data["error"]["code"] == "ELVA_REPO_QUEUE_FULL"
    assert "Repository connected" in result.stderr
    assert len(api.requests) == 2


@pytest.mark.parametrize(
    "state,exit_code,code",
    [
        ("failed", 5, "ELVA_REPO_SCAN_FAILED"),
        ("cancelled", 2, "ELVA_REPO_SCAN_CANCELLED"),
        ("skipped", 4, "ELVA_REPO_SYNC_INCOMPLETE"),
        ("missing_collections", 4, "ELVA_REPO_SYNC_INCOMPLETE"),
    ],
)
def test_unsuccessful_scans_are_not_success(
    api: Api,
    run: Callable[..., subprocess.CompletedProcess[str]],
    state: str,
    exit_code: int,
    code: str,
) -> None:
    if state == "skipped":
        api.job["collections"]["skipped"] = (
            "scan found no endpoints - existing collections preserved"
        )
    elif state == "missing_collections":
        api.job["collections"] = None
    else:
        api.job["status"] = state
    result = run("--json", "repo", "status", JOB, env=api.env)
    assert result.returncode == exit_code, result.stderr
    assert json.loads(result.stdout)["error"]["code"] == code


def test_timeout_is_resumable(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.job.update(status="scanning_code", progress=40)
    result = run(
        "--yes", "--json", "repo", "sync", REPO, "--wait", "--wait-timeout", "0.05", env=api.env
    )
    assert result.returncode == 5, result.stderr
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "ELVA_REPO_WAIT_TIMEOUT"
    assert data["scan_job_id"] == JOB
    # A short deadline can expire before the first poll. The job ID must still
    # work for resuming, regardless of whether a status snapshot was obtained.
    resumed = run("--json", "repo", "status", data["scan_job_id"], env=api.env)
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["job"]["status"] == "scanning_code"
    assert f"repo status {JOB}" in result.stderr
    assert not any("cancel" in path for _, path, _ in api.requests)


def test_wait_network_failure_preserves_job(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.errors[f"/api/catalog/jobs/{JOB}"] = (502, "Bad gateway")
    result = run("--yes", "--json", "repo", "sync", REPO, "--wait", env=api.env)
    assert result.returncode == 5, result.stderr
    assert json.loads(result.stdout)["scan_job_id"] == JOB
    assert f"repo status {JOB}" in result.stderr
    assert len(api.requests) == 3


@pytest.mark.parametrize("command", ["status", "sync"])
def test_foreign_scan_is_not_output(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], command: str
) -> None:
    api.job["repoId"] = "e" * 24
    result = run(
        "--yes",
        "--json",
        "repo",
        command,
        JOB if command == "status" else REPO,
        "--wait",
        env=api.env,
    )
    assert result.returncode in {2, 5}, result.stderr
    assert "commit123" not in result.stdout


@pytest.mark.parametrize("timeout", ["nan", "inf", "0", "-1"])
def test_invalid_timeout_never_calls_api(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], timeout: str
) -> None:
    result = run("--yes", "repo", "connect", "acme/api", "--wait-timeout", timeout, env=api.env)
    assert result.returncode == 2, result.stderr
    assert not api.requests


def test_human_results_include_warnings_without_terminal_controls(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.job["errors"] = [{"step": "static", "message": "Unsupported [parser]\x1b[2J"}]
    result = run("repo", "status", JOB, env={**api.env, "NO_COLOR": "1"})
    assert result.returncode == 0, result.stderr
    assert "Created: 1 (Payments)" in result.stdout
    assert "Unsupported [parser]" in result.stdout and "\x1b" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal interaction")
@pytest.mark.parametrize(
    "command,answer", [("connect", "n"), ("connect", "y"), ("sync", "n"), ("sync", "y")]
)
def test_interactive_confirmation(
    api: Api, workdir: Path, command: str, answer: str, interactive_env: dict[str, str]
) -> None:
    import pty
    import select

    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "elva_cli", "repo", command, "acme/api"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=workdir,
        env={**interactive_env, **api.env},
        start_new_session=True,
    )
    os.close(slave)
    try:
        output = b""
        deadline = time.monotonic() + 10
        while b"(y/N)" not in output:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output += os.read(master, 65536)
        assert b"generated collections" in output
        os.write(master, answer.encode() + b"\r")
        assert process.wait(timeout=10) == 0
        writes = [method for method, _, _ in api.requests if method == "POST"]
        assert len(writes) == (1 if answer == "y" else 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process signal")
def test_ctrl_c_only_stops_local_wait(api: Api, workdir: Path) -> None:
    api.job.update(status="scanning_code", progress=40)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELVA_")}
    process = subprocess.Popen(
        [sys.executable, "-m", "elva_cli", "--yes", "repo", "sync", REPO, "--wait"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=workdir,
        env={**env, **api.env},
    )
    try:
        deadline = time.monotonic() + 10
        while not any("/catalog/jobs/" in path for _, path, _ in api.requests):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        process.send_signal(signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 130, stderr.decode()
        assert JOB.encode() in stderr
        assert not any("cancel" in path for _, path, _ in api.requests)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
