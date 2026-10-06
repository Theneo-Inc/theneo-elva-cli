"""Grounded AI plans: inspectable files, scoped execution, resumable server jobs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any

from elva_cli.core.services.contract import _find, _request, _scope
from elva_cli.core.services.plan_result import AppliedPlan, PlanResult
from elva_cli.errors import ApiError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_ID = re.compile(r"[a-f0-9]{24}")


def canonical_json(value: Any) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(k, ensure_ascii=False) + ":" + canonical_json(value[k])
                for k in sorted(value, key=lambda k: k.encode("utf-16-be"))
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def validate_plan(data: Any, base_url: str) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("plan"), dict):
        data = data["plan"]
    if not isinstance(data, dict) or not isinstance(data.get("review"), dict):
        raise UsageError("Expected an Elva plan JSON file.")
    review = data["review"]
    if (
        review.get("version") != 1
        or not isinstance(data.get("planId"), str)
        or not _ID.fullmatch(data["planId"])
        or data.get("apiOrigin") != base_url.rstrip("/")
        or not isinstance(data.get("digest"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", data["digest"])
        or not isinstance(review.get("companyId"), str)
        or not _ID.fullmatch(review["companyId"])
    ):
        raise UsageError("Plan version, server, or workspace is invalid for this invocation.")
    try:
        digest = hashlib.sha256(canonical_json(review).encode()).hexdigest()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UsageError("Plan contains invalid JSON values.") from exc
    if digest != data.get("fileDigest"):
        raise UsageError(
            "Plan was edited or corrupted. Generate a new plan to review these changes."
        )
    return data


def save_plan(result: PlanResult, path: Path | None) -> None:
    if path is None:
        return
    try:
        # Never overwrite another reviewed plan or follow a pre-existing symlink.
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result.plan, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise UsageError(
            f"Could not create plan file: {path}", hint="Choose a new writable path."
        ) from exc


def planning_job(
    *,
    base_url: str,
    workspace: str | None,
    job_id: str,
    progress: Callable[[str], None],
    wait: bool = True,
) -> PlanResult:
    if not _ID.fullmatch(job_id):
        raise UsageError("Invalid planning job ID.")
    token, _, path = _scope(base_url, workspace)
    deadline = time.monotonic() + (600 if wait else 0)
    next_progress = 0.0
    while True:
        data = _request(base_url, token, f"{path}/ai/jobs/{job_id}")
        if not isinstance(data, dict) or data.get("jobId") != job_id:
            raise ApiError("Unexpected planning job response.")
        if data.get("status") == "done":
            result = data.get("result")
            if not isinstance(result, dict):
                raise ApiError("Unexpected completed plan.")
            result["apiOrigin"] = base_url.rstrip("/")
            result["fileDigest"] = hashlib.sha256(
                canonical_json(result["review"]).encode()
            ).hexdigest()
            return PlanResult(validate_plan(result, base_url))
        if data.get("status") == "needs_input":
            raise UsageError(
                "Source scanning finished; the live API base URL is needed.",
                code="ELVA_INPUT_REQUIRED",
                hint=f"Resume: elva --resume {job_id} --api-base-url https://your-api.example.com",
            )
        if data.get("status") == "failed":
            error = data.get("error") or {}
            if error.get("status", 500) >= 500:
                raise ApiError(
                    str(error.get("message", "AI planning is unavailable.")),
                    code="ELVA_PLAN_UNAVAILABLE",
                    hint=f"Retry: elva --resume {job_id}."
                    if data.get("canResume")
                    else "Retry planning when the AI service is available.",
                )
            raise ValidationError(
                str(error.get("message", "AI planning failed.")),
                code="ELVA_PLAN_FAILED",
                hint="Review the source catalog and prompt, then generate a new plan.",
            )
        if data.get("status") != "planning":
            raise ApiError("Unexpected planning job status.")
        if time.monotonic() >= deadline:
            raise ApiError(
                f"Planning job {job_id} is still running.",
                code="ELVA_PLAN_PENDING",
                hint=f"Resume with 'elva plan show {job_id}'. No contract or MCP was created.",
            )
        if time.monotonic() >= next_progress:
            progress(f"Planning job {job_id}: selecting endpoints and reviewing fields...")
            next_progress = time.monotonic() + 30
        time.sleep(3)


def create_plan(
    *,
    base_url: str,
    workspace: str | None,
    body: dict[str, Any],
    reference: str | None,
    progress: Callable[[str], None],
) -> PlanResult:
    if not isinstance(body.get("prompt"), str) or not 1 <= len(body["prompt"].strip()) <= 2000:
        raise UsageError("Prompt must contain between 1 and 2000 characters.")
    token, company_id, path = _scope(base_url, workspace)
    if reference:
        body = {**body, "contractId": _find(base_url, token, company_id, path, reference)["id"]}
    job = _request(base_url, token, f"{path}/ai/plan", method="POST", body=body)
    if not isinstance(job, dict) or not isinstance(job.get("jobId"), str):
        raise ApiError("Unexpected planning response.")
    progress(f"Planning job {job['jobId']} started; 'elva plan show {job['jobId']}' resumes it.")
    return planning_job(
        base_url=base_url,
        workspace=company_id,
        job_id=job["jobId"],
        progress=progress,
    )


def apply_plan(
    *,
    base_url: str,
    workspace: str | None,
    plan: dict[str, Any],
    confirm: Callable[[str], None],
) -> AppliedPlan:
    plan = validate_plan(plan, base_url)
    token, company_id, path = _scope(base_url, workspace)
    if company_id != plan["review"]["companyId"]:
        raise UsageError(
            "The plan belongs to a different workspace. Select that workspace explicitly."
        )
    if plan["review"].get("blockers"):
        raise ValidationError("Plan is incomplete: " + "; ".join(plan["review"]["blockers"]))
    confirm(
        f"Apply reviewed plan {plan['planId']} in workspace {company_id}? "
        "This saves contract changes and any MCP as a draft. It does not publish."
    )
    data = _request(
        base_url,
        token,
        f"{path}/ai/plans/{plan['planId']}/apply",
        method="POST",
        body={"digest": plan["digest"], "review": plan["review"]},
    )
    if not isinstance(data, dict) or data.get("status") != "applied":
        raise ApiError("Plan application was not confirmed. Retry the same plan file to resume.")
    return AppliedPlan(data)


def read_plan(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise UsageError("Plan file exceeds the 10 MiB limit.")
        data: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise UsageError("Could not read a valid plan JSON file.") from exc
