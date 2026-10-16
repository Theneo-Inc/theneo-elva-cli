from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from elva_cli.core.services.contract import _request, _scope
from elva_cli.core.services.plan import planning_job
from elva_cli.errors import ApiError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from elva_cli.core.services.plan_result import PlanResult


def local_plan(
    *,
    base_url: str,
    workspace: str | None,
    body: dict[str, Any] | None,
    resume: str | None,
    base_url_answer: Callable[[], str],
    progress: Callable[[str], None],
    replacement_base_url: str | None = None,
) -> PlanResult:
    token, company_id, path = _scope(base_url, workspace)
    if resume:
        if not re.fullmatch(r"[a-f0-9]{24}", resume):
            raise UsageError("Invalid source planning job ID.")
        job_id = resume
    else:
        data = _request(base_url, token, f"{path}/ai/source", method="POST", body=body)
        if not isinstance(data, dict) or not re.fullmatch(
            r"[a-f0-9]{24}", str(data.get("jobId", ""))
        ):
            raise ApiError("Unexpected source planning response.")
        job_id = data["jobId"]
    progress(f"Source job {job_id}; resume with elva --resume {job_id}.")
    deadline = time.monotonic() + 900
    next_progress = 0.0
    retried = False
    while True:
        job = _request(base_url, token, f"{path}/ai/jobs/{job_id}")
        if not isinstance(job, dict) or job.get("jobId") != job_id:
            raise ApiError("Unexpected source job response.")
        if job.get("status") == "done":
            return planning_job(
                base_url=base_url,
                workspace=company_id,
                job_id=job_id,
                progress=progress,
                wait=False,
            )
        if job.get("status") == "needs_input":
            if job.get("requiredInputs") != ["baseUrl"]:
                raise ApiError("This source job requires inputs unsupported by this CLI version.")
            try:
                answer = base_url_answer()
            except UsageError as exc:
                raise UsageError(
                    "The source was scanned, but the live API URL is needed "
                    "to build callable tools.",
                    code="ELVA_INPUT_REQUIRED",
                    hint=f"Resume: elva --resume {job_id} "
                    "--api-base-url https://your-api.example.com",
                ) from exc
            _request(
                base_url,
                token,
                f"{path}/ai/jobs/{job_id}/resume",
                method="POST",
                body={"baseUrl": answer},
            )
        elif job.get("status") == "failed":
            error = job.get("error") or {}
            if resume and job.get("canResume") and not retried:
                _request(
                    base_url,
                    token,
                    f"{path}/ai/jobs/{job_id}/resume",
                    method="POST",
                    body={"baseUrl": replacement_base_url} if replacement_base_url else {},
                )
                retried = True
                progress(
                    "Retrying planning from the existing source collections; no source upload."
                )
            else:
                failure = ApiError if error.get("status", 500) >= 500 else ValidationError
                ids = ", ".join(str(i) for i in job.get("sourceCollectionIds", []))
                raise failure(
                    str(error.get("message", "Source planning failed.")),
                    hint=(f"Retry: elva --resume {job_id}. " if job.get("canResume") else "")
                    + (
                        f"Generated source collections remain in Elva: {ids}."
                        if ids
                        else "No source collections were generated."
                    ),
                )
        elif job.get("status") != "planning":
            raise ApiError("Unexpected source job status.")
        if time.monotonic() >= deadline:
            raise ApiError(
                "Source planning is still running.",
                code="ELVA_PLAN_PENDING",
                hint=f"Continue with elva --resume {job_id}.",
            )
        if time.monotonic() >= next_progress:
            progress(str(job.get("stage") or "Analyzing source and preparing the MCP contract"))
            next_progress = time.monotonic() + 30
        time.sleep(3)
