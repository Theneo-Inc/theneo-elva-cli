from __future__ import annotations

import copy
import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from elva_cli.core.services import plan as service
from elva_cli.core.services.plan_result import PlanResult
from elva_cli.errors import ApiError, UsageError, ValidationError
from elva_cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

URL = "https://api.example.com"
COMPANY = "a" * 24
PLAN = "b" * 24


def fixture() -> dict[str, Any]:
    review = {"version": 1, "companyId": COMPANY, "blockers": [], "contract": {"name": "Orders"}}
    return {
        "planId": PLAN,
        "review": review,
        "apiOrigin": URL,
        "digest": "d" * 64,
        "fileDigest": hashlib.sha256(service.canonical_json(review).encode()).hexdigest(),
    }


def test_plan_digest_is_order_independent() -> None:
    original = fixture()
    reordered = copy.deepcopy(original)
    reordered["review"] = dict(reversed(list(original["review"].items())))
    assert service.validate_plan(reordered, URL) == reordered


@pytest.mark.parametrize("change", ["content", "version", "origin", "workspace", "id"])
def test_refuses_tampered_or_wrong_server_plan(change: str) -> None:
    value = fixture()
    if change == "content":
        value["review"]["contract"]["name"] = "Other"
    elif change == "version":
        value["review"]["version"] = 2
    elif change == "origin":
        value["apiOrigin"] = "https://other.example.com"
    elif change == "workspace":
        value["review"]["companyId"] = "invalid"
    else:
        value["planId"] = "invalid"
    with pytest.raises(UsageError):
        service.validate_plan(value, URL)


def test_plan_file_never_overwrites_or_follows_existing_symlink(tmp_path: Path) -> None:
    target = tmp_path / "review.json"
    target.write_text("reviewed")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    for path in (target, link):
        with pytest.raises(UsageError):
            service.save_plan(PlanResult(fixture()), path)
    assert target.read_text() == "reviewed"


def test_wrong_workspace_cannot_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_scope", lambda *_: ("token", "c" * 24, "/contracts"))
    with pytest.raises(UsageError, match="different workspace"):
        service.apply_plan(
            base_url=URL, workspace=None, plan=fixture(), confirm=lambda _: pytest.fail()
        )


def test_apply_only_sends_server_plan_id_and_review_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_scope", lambda *_: ("token", COMPANY, "/contracts"))
    calls: list[Any] = []

    def request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((args, kwargs))
        return {"planId": PLAN, "status": "applied", "contractId": "c" * 24}

    monkeypatch.setattr(service, "_request", request)
    confirmed: list[str] = []
    result = service.apply_plan(
        base_url=URL, workspace=None, plan=fixture(), confirm=confirmed.append
    )
    assert result.result["status"] == "applied"
    assert len(confirmed) == 1
    assert calls[0][0][-1] == f"/contracts/ai/plans/{PLAN}/apply"
    assert calls[0][1]["body"] == {"digest": fixture()["digest"], "review": fixture()["review"]}


@pytest.mark.parametrize("status,error", [("planning", ApiError), ("failed", ValidationError)])
def test_unfinished_jobs_never_report_success(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    error: type[Exception],
) -> None:
    monkeypatch.setattr(service, "_scope", lambda *_: ("token", COMPANY, "/contracts"))
    monkeypatch.setattr(
        service, "_request", lambda *_: {"jobId": PLAN, "status": status, "error": {"status": 422}}
    )
    with pytest.raises(error):
        service.planning_job(
            base_url=URL, workspace=None, job_id=PLAN, progress=lambda _: None, wait=False
        )


def test_agent_discovery_contains_new_commands_and_flags() -> None:
    import json

    result = CliRunner().invoke(app, ["--json", "schema"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    commands = {c["command"]: c for c in data["commands"]}
    assert data["version"] == 1
    assert {"elva apply", "elva plan show", "elva mcp plan"} <= commands.keys()
    assert any("--prompt" in p["options"] for p in commands["elva contract update"]["parameters"])


def test_invalid_plan_json_values_are_usage_errors() -> None:
    for invalid in (float("nan"), "\\ud800"):
        value = fixture()
        value["review"]["contract"]["name"] = invalid if isinstance(invalid, float) else chr(0xD800)
        with pytest.raises(UsageError):
            service.validate_plan(value, URL)


def test_schema_distinguishes_flags_options_and_arguments() -> None:
    import json

    result = CliRunner().invoke(app, ["--json", "schema"])
    assert result.exit_code == 0, result.output
    commands = {c["command"]: c for c in json.loads(result.stdout)["commands"]}
    root = {p["name"]: p for p in commands["elva"]["parameters"]}
    assert root["json_output"]["is_flag"] is True
    assert root["json_output"]["default"] is False
    assert root["workspace"]["envvar"] == "ELVA_WORKSPACE"
    argument = commands["elva apply"]["parameters"][0]
    assert argument["kind"] == "argument"
    assert argument["options"] == []
