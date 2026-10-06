"""Real CLI processes against a synthetic API, including default workspace selection."""

from __future__ import annotations

import http.server
import json
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Iterator
    from pathlib import Path

COMPANY = "a" * 24
OTHER = "d" * 24
CONTRACT = "b" * 24
COLLECTION = "c" * 24
ROOT = f"/api/companies/{COMPANY}/api-contracts"
DOC = f"{ROOT}/{CONTRACT}"
SPEC = 'openapi: 3.0.3\ninfo: {title: Payments, version: "1"}\npaths: {}\n'


@dataclass
class Api:
    url: str = ""
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    errors: dict[str, tuple[int, str]] = field(default_factory=dict)
    contract: dict[str, Any] = field(
        default_factory=lambda: {
            "id": CONTRACT,
            "company": COMPANY,
            "name": "Partner API",
            "status": "draft",
            "version": "v1.0",
            "collections": [],
            "publishing": {},
        }
    )
    outcomes: list[dict[str, Any]] = field(
        default_factory=lambda: [{"platform": "postman", "status": "published"}]
    )
    review: dict[str, Any] = field(
        default_factory=lambda: {
            "scorable": True,
            "overallScore": 82,
            "overallGrade": "B",
            "operationCount": 1,
            "rubricCoverage": 1,
            "scores": {"Security": {"percentage": 75, "grade": "B", "coverage": 1}},
            "checks": [
                {
                    "id": "sec-https-only",
                    "category": "Security",
                    "status": "Fail",
                    "comments": "Use HTTPS [recommended]",
                }
            ],
        }
    )

    @property
    def env(self) -> dict[str, str]:
        return {"ELVA_BASE_URL": self.url, "ELVA_TOKEN": "qa-local"}


@pytest.fixture
def api() -> Iterator[Api]:
    state = Api()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def handle_request(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body: Any = (
                raw.decode() if self.path == "/api/review" else json.loads(raw) if raw else None
            )
            state.calls.append((self.command, self.path, body))
            if self.path.startswith("/api/review"):
                assert self.headers.get("Authorization") is None
            else:
                assert self.headers.get("Authorization") == "Bearer qa-local"
            status = 200
            data: Any
            if self.path in state.errors:
                status, message = state.errors[self.path]
                data = {"message": message}
            elif self.path == "/api/companies/workspaces":
                data = {
                    "workspaces": [{"id": OTHER, "name": "Other"}, {"id": COMPANY, "name": "Acme"}],
                    "defaultWorkspaceId": COMPANY,
                }
            elif self.path == "/api/review/checks":
                data = [
                    {
                        "id": "sec-https-only",
                        "category": "Security",
                        "name": "HTTPS",
                        "severity": "high",
                    }
                ]
            elif self.path == "/api/review":
                assert self.headers["Content-Type"].startswith("text/plain")
                data = state.review
            elif self.path == f"/api/companies/{COMPANY}/collections":
                data = {
                    "collections": [{"id": COLLECTION, "name": "Payments", "specTitle": "Payments"}]
                }
            elif self.path == f"/api/companies/{COMPANY}/collections/{COLLECTION}/spec":
                data = {"spec": SPEC}
            elif self.path == ROOT:
                data = (
                    {"apiContracts": [state.contract]}
                    if self.command == "GET"
                    else {"apiContract": {**state.contract, **body}}
                )
                status = 201 if self.command == "POST" else 200
            elif self.path == DOC:
                if self.command == "DELETE":
                    status, data = 204, None
                else:
                    data = {"apiContract": {**state.contract, **(body or {})}}
            elif self.path == f"{DOC}/sync":
                data = {"apiContract": {**state.contract, "pendingChanges": body["changes"]}}
            elif self.path == f"{DOC}/approval":
                data = {
                    **state.contract,
                    "governance": {
                        "requireApproval": True,
                        "approval": {"status": body["decision"]},
                    },
                }
            elif self.path == f"{DOC}/publish":
                data = {"results": state.outcomes}
            else:
                status, data = 404, {"message": "Unexpected local test route"}
            encoded = b"" if status == 204 else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = handle_request  # noqa: N815
        do_POST = handle_request  # noqa: N815
        do_PATCH = handle_request  # noqa: N815
        do_DELETE = handle_request  # noqa: N815

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


def test_public_checks_need_no_login(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--json", "insights", "checks", env={"ELVA_BASE_URL": api.url})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["checks"][0]["id"] == "sec-https-only"
    assert len(api.calls) == 1


@pytest.mark.parametrize("score,scorable,expected", [(82, True, 0), (70, True, 4), (99, False, 4)])
def test_review_threshold_and_json(
    api: Api,
    run: Callable[..., subprocess.CompletedProcess[str]],
    score: int,
    scorable: bool,
    expected: int,
) -> None:
    api.review.update(overallScore=score, scorable=scorable)
    result = run(
        "--json", "insights", "review", "-", "--fail-under", "80", stdin_text=SPEC, env=api.env
    )
    assert result.returncode == expected, result.stderr
    assert json.loads(result.stdout)["review"]["overallScore"] == score
    assert api.calls == [("POST", "/api/review", SPEC)]
    if expected:
        assert "ELVA_INSIGHTS_GATE" in result.stderr


def test_file_review_shows_findings(
    api: Api, workdir: Path, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    path = workdir / "spec.yaml"
    path.write_text(SPEC)
    result = run("insights", "review", str(path), env=api.env)
    assert result.returncode == 0, result.stderr
    assert "82/100" in result.stdout and "Use HTTPS [recommended]" in result.stdout


def test_collection_insights_use_default_workspace(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--json", "insights", "show", "Payments", env=api.env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["company_id"] == COMPANY and data["collection_id"] == COLLECTION
    assert api.calls[-1] == ("POST", "/api/review", SPEC)


@pytest.mark.parametrize("threshold", ["nan", "inf", "101", "-1"])
def test_invalid_threshold_never_reads_or_calls_api(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], threshold: str
) -> None:
    result = run("insights", "review", "missing.yaml", "--fail-under", threshold, env=api.env)
    assert result.returncode == 2, result.stderr
    assert not api.calls


def test_invalid_spec_is_validation_failure(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.errors["/api/review"] = (422, "Spec parsed but not valid OpenAPI")
    result = run("insights", "review", "-", stdin_text="invalid", env=api.env)
    assert result.returncode == 4 and "ELVA_VALIDATION" in result.stderr


def test_contract_list_uses_server_default(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--json", "contract", "list", env=api.env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["company_id"] == COMPANY
    assert api.calls[-1] == ("GET", ROOT, None)


def test_explicit_workspace_takes_precedence(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--workspace", COMPANY, "contract", "list", env=api.env)
    assert result.returncode == 0, result.stderr
    assert api.calls == [("GET", ROOT, None)]


@pytest.mark.parametrize("ref", [CONTRACT.upper(), "partner api"])
def test_show_by_name_and_id(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], ref: str
) -> None:
    result = run("--json", "contract", "show", ref, env=api.env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["contract"]["id"] == CONTRACT


def test_create_always_starts_as_draft(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run(
        "--yes",
        "--json",
        "contract",
        "create",
        "--name",
        "Client API",
        "--audience",
        "partner",
        env=api.env,
    )
    assert result.returncode == 0, result.stderr
    assert api.calls[-1] == (
        "POST",
        ROOT,
        {"name": "Client API", "audience": "partner", "status": "draft"},
    )


@pytest.mark.parametrize(
    "action", ["create", "update", "sync", "approve", "reject", "publish", "delete"]
)
def test_mutations_need_yes(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], action: str
) -> None:
    args = ["--name", "Test"] if action == "create" else [CONTRACT]
    if action in {"update", "sync"}:
        args += ["--from", "-"]
    body: dict[str, Any] = (
        {"name": "Changed"} if action == "update" else {"changes": [], "collections": []}
    )
    result = run("contract", action, *args, stdin_text=json.dumps(body), env=api.env)
    assert result.returncode == 2 and "--yes" in result.stderr, result.stderr
    assert all(method == "GET" for method, _, _ in api.calls)


@pytest.mark.parametrize("action", ["create", "update"])
def test_json_cannot_accidentally_publish(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], action: str
) -> None:
    args = [] if action == "create" else [CONTRACT]
    result = run(
        "--yes",
        "contract",
        action,
        *args,
        "--from",
        "-",
        stdin_text='{"name":"X","status":"active"}',
        env=api.env,
    )
    assert result.returncode == 2 and "contract publish" in result.stderr
    assert not api.calls


def test_update_round_trips_show_envelope(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    payload = {"contract": {**api.contract, "description": "Updated"}}
    result = run(
        "--yes",
        "--json",
        "contract",
        "update",
        CONTRACT,
        "--from",
        "-",
        stdin_text=json.dumps(payload),
        env=api.env,
    )
    assert result.returncode == 0, result.stderr
    assert api.calls[-1][0] == "PATCH" and api.calls[-1][2]["description"] == "Updated"


def test_sync_sends_reviewed_changes_without_publish(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    payload = {
        "changes": [{"kind": "drift", "message": "Added field"}],
        "collections": [],
        "endpointSchemas": [],
        "refreshedCollections": [],
    }
    result = run(
        "--yes",
        "--json",
        "contract",
        "sync",
        CONTRACT,
        "--from",
        "-",
        stdin_text=json.dumps(payload),
        env=api.env,
    )
    assert result.returncode == 0, result.stderr
    assert api.calls[-1] == ("POST", f"{DOC}/sync", payload)
    assert not any(path.endswith("publish") for _, path, _ in api.calls)


@pytest.mark.parametrize("action,decision", [("approve", "approved"), ("reject", "rejected")])
def test_approval_uses_dedicated_endpoint(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], action: str, decision: str
) -> None:
    result = run("--yes", "--json", "contract", action, CONTRACT, "--note", "Reviewed", env=api.env)
    assert result.returncode == 0, result.stderr
    assert api.calls[-1] == ("POST", f"{DOC}/approval", {"note": "Reviewed", "decision": decision})


@pytest.mark.parametrize(
    "outcomes,exit_code",
    [
        ([{"platform": "postman", "status": "published"}], 0),
        ([{"platform": "postman", "status": "unchanged"}], 0),
        (
            [
                {"platform": "postman", "status": "published"},
                {"platform": "mcp", "status": "failed"},
            ],
            5,
        ),
        ([{"platform": "postman", "status": "skipped"}], 5),
        ([], 5),
    ],
)
def test_publish_preserves_partial_results(
    api: Api,
    run: Callable[..., subprocess.CompletedProcess[str]],
    outcomes: list[dict[str, Any]],
    exit_code: int,
) -> None:
    api.contract["publishing"] = {"platformConfigs": [{"platform": "postman"}]}
    api.outcomes = outcomes
    result = run("--yes", "--json", "contract", "publish", CONTRACT, env=api.env)
    assert result.returncode == exit_code, result.stderr
    assert json.loads(result.stdout)["results"] == outcomes
    assert api.calls[-1] == ("POST", f"{DOC}/publish", {})


def test_publish_without_external_destination_activates_contract(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--yes", "contract", "publish", CONTRACT, env=api.env)
    assert result.returncode == 0, result.stderr
    assert api.calls[-1] == ("PATCH", DOC, {"status": "active"})


def test_delete_handles_empty_204(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = run("--yes", "--json", "contract", "delete", CONTRACT, env=api.env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "deleted"


@pytest.mark.parametrize("status,code", [(401, 3), (403, 3), (409, 2), (422, 4), (502, 5)])
def test_backend_failures_remain_actionable(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]], status: int, code: int
) -> None:
    api.errors[DOC] = (status, "Contract action rejected")
    result = run("--yes", "contract", "publish", CONTRACT, env=api.env)
    assert result.returncode == code, result.stderr
    assert not any(method != "GET" for method, _, _ in api.calls)


def test_cross_workspace_response_is_refused(
    api: Api, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    api.contract["company"] = OTHER
    result = run("--yes", "contract", "delete", CONTRACT, env=api.env)
    assert result.returncode == 5, result.stderr
    assert not any(method == "DELETE" for method, _, _ in api.calls)
