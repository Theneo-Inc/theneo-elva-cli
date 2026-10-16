from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from elva_cli.commands.prompt import inferred_audience
from elva_cli.core.services import local_source
from elva_cli.core.services.plan_result import AppliedPlan, PlanResult
from elva_cli.errors import UsageError
from elva_cli.main import app


def test_root_prompt_scans_raw_code_and_creates_both_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("@app.get('/orders')\ndef orders(): return {'id': '1'}")
    review = {
        "contract": {
            "name": "Customer API",
            "collections": [{"endpoints": [{"method": "GET", "path": "/orders"}]}],
        }
    }
    plan = {"planId": "a" * 24, "review": review}
    received = []

    def prepare(**kwargs: Any) -> PlanResult:
        received.append(kwargs)
        return PlanResult(plan)

    monkeypatch.setattr(local_source, "local_plan", prepare)
    monkeypatch.setattr(
        "elva_cli.core.services.plan.apply_plan",
        lambda **_: AppliedPlan({"contractId": "b" * 24, "mcp": {"status": "draft"}}),
    )
    result = CliRunner().invoke(
        app,
        [
            "--yes",
            "--json",
            "--prompt",
            "Find external customer endpoints and create an MCP",
            "--out",
            "review.json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert received[0]["body"]["snapshot"]["files"][0]["path"] == "app.py"
    assert received[0]["body"]["audience"] == "partner"
    data = json.loads(result.stdout)
    assert data["status"] == "drafts_created"
    assert data["result"]["contractId"] == "b" * 24
    assert Path("review.json").exists()


def test_unattended_ambiguous_audience_requires_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["--yes", "--json", "--prompt", "Make an MCP"])
    assert isinstance(result.exception, UsageError)
    assert "--audience" in str(result.exception)


def test_prompt_cannot_be_mixed_with_a_subcommand() -> None:
    result = CliRunner().invoke(app, ["--prompt", "Make a customer MCP", "whoami"])
    assert isinstance(result.exception, UsageError)


def test_resume_needs_no_snapshot_and_continues_after_api_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = "a" * 24
    responses: Iterator[dict[str, Any]] = iter(
        [
            {"jobId": job, "status": "needs_input", "requiredInputs": ["baseUrl"]},
            {"jobId": job, "status": "planning"},
            {"jobId": job, "status": "done"},
        ]
    )
    calls = []
    monkeypatch.setattr(local_source, "_scope", lambda *_: ("token", "workspace", "/contracts"))

    def request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((args, kwargs))
        if kwargs.get("method") == "POST":
            return {"jobId": job}
        return next(responses)

    monkeypatch.setattr(local_source, "_request", request)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(local_source, "planning_job", lambda **_: PlanResult({"planId": job}))
    result = local_source.local_plan(
        base_url="https://api.example.com",
        workspace=None,
        body=None,
        resume=job,
        base_url_answer=lambda: "https://customer.example.com",
        progress=lambda _: None,
    )
    assert result.plan["planId"] == job
    posts = [c for c in calls if c[1].get("method") == "POST"]
    assert len(posts) == 1 and posts[0][0][-1].endswith("/resume")
    assert posts[0][1]["body"] == {"baseUrl": "https://customer.example.com"}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("For external customers", "partner"),
        ("for public use", "public"),
        ("for employees", "internal"),
        ("public or internal use", None),
    ],
)
def test_audience_inference_only_uses_clear_intent(text: str, expected: str | None) -> None:
    assert inferred_audience(text) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://[",
        "http://host:bad",
        "https://host?q=1",
        "https://user:pass@host",
        "https://host/#x",
    ],
)
def test_malformed_api_url_is_usage_error(value: str) -> None:
    from elva_cli.commands.prompt import validate_api_url

    with pytest.raises(UsageError):
        validate_api_url(value)


def test_failed_resume_forwards_replacement_url_once(monkeypatch: pytest.MonkeyPatch) -> None:
    job = "b" * 24
    responses: Iterator[dict[str, Any]] = iter(
        [{"jobId": job, "status": "failed", "canResume": True}, {"jobId": job, "status": "done"}]
    )
    calls = []
    monkeypatch.setattr(local_source, "_scope", lambda *_: ("token", "workspace", "/contracts"))

    def request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {} if kwargs.get("method") == "POST" else next(responses)

    monkeypatch.setattr(local_source, "_request", request)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(local_source, "planning_job", lambda **_: PlanResult({"planId": job}))
    local_source.local_plan(
        base_url="https://elva.example.com",
        workspace=None,
        body=None,
        resume=job,
        base_url_answer=lambda: "unused",
        progress=lambda _: None,
        replacement_base_url="https://fixed.example.com",
    )
    assert [c["body"] for c in calls if c.get("method") == "POST"] == [
        {"baseUrl": "https://fixed.example.com"}
    ]
