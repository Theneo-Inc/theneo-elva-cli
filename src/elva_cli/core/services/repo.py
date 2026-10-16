"""Workspace-scoped GitHub connection and scan flows.

GitHub credentials stay on Elva's backend. All mutations follow a scoped
preflight, and a failed local wait retains the remote job for later inspection.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, get_json, send_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.core.api.timeout import request_timeout, use_timeout
from elva_cli.core.services.repo_result import (
    RepoJob,
    RepoListResult,
    RepoProblem,
    RepoScanResult,
    Repository,
)
from elva_cli.errors import ApiError, AuthError, ElvaError, ExitCode, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable

_ID = re.compile(r"[a-f0-9]{24}", re.IGNORECASE)
_NAME = re.compile(r"[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}")
_TERMINAL = {"done", "failed", "cancelled"}


def github_name(value: str) -> tuple[str, str]:
    """Accept an owner/name or a GitHub clone URL, never a credential-bearing URL."""
    name = value.strip()
    for prefix in ("https://github.com/", "ssh://git@github.com/", "git@github.com:"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    name = name.removesuffix("/").removesuffix(".git")
    if not _NAME.fullmatch(name) or any(part in {".", ".."} for part in name.split("/")):
        raise UsageError(
            "Expected OWNER/REPO or a GitHub clone URL.",
            hint="For example: elva repo connect acme/payments --branch main",
        )
    owner, repo = name.split("/")
    return owner, repo


def _unexpected() -> ApiError:
    return ApiError("The server returned an unexpected repository response.")


def _string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise _unexpected()
    return value


def _id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise _unexpected()
    return value.lower()


def _optional_string(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value is not None and not isinstance(value, str):
        raise _unexpected()
    return value


def _repository(row: Any, company_id: str) -> Repository:
    if not isinstance(row, dict):
        raise _unexpected()
    if row.get("companyId") != company_id:
        raise ApiError(
            "The API did not return a repository in the selected workspace.",
            code="ELVA_REPO_SCOPE",
            hint="Use an Elva API version that supports workspace-scoped repository sync.",
        )
    for key in ("private", "aiEnabled", "needsBaseUrl"):
        if not isinstance(row.get(key), bool):
            raise _unexpected()
    return Repository(
        id=_id(row.get("id")),
        owner=_string(row, "owner"),
        name=_string(row, "name"),
        company_id=company_id,
        branch=_string(row, "branch"),
        private=row["private"],
        ai_enabled=row["aiEnabled"],
        base_url=_optional_string(row, "baseUrl"),
        needs_base_url=row["needsBaseUrl"],
        last_scan_at=_optional_string(row, "lastScanAt"),
        last_scan_job_id=_id(row["lastScanJobId"]) if row.get("lastScanJobId") else None,
    )


def _api(base_url: str, token: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        # A GitHub 401 must not trigger a refresh of the separate Elva identity.
        if payload is None:
            return get_json(f"{base_url.rstrip('/')}{path}", token=token)
        return send_json(
            f"{base_url.rstrip('/')}{path}", token=token, method="POST", payload=payload
        )
    except HttpError as exc:
        detail = exc.detail or ""
        if exc.status == 401 and "github" in detail.lower():
            raise AuthError(
                "Your GitHub connection is missing or no longer valid.",
                code="ELVA_GITHUB_AUTH",
                hint="Connect or reconnect GitHub in the Elva web app, then retry.",
            ) from exc
        if exc.status in {400, 404, 409}:
            raise UsageError(
                detail or "Repository or scan not found, or the request conflicts with its state.",
                hint="Check the repository, branch, workspace and job ID; run 'elva repo list'.",
            ) from exc
        if exc.status == 429:
            raise ApiError(
                "The scan queue or request limit is full.",
                code="ELVA_REPO_QUEUE_FULL",
                hint="Wait for the current scans to finish, then retry.",
            ) from exc
        if exc.status == 402:
            raise ApiError(
                "Your workspace plan does not allow this repository connection.",
                code="ELVA_REPO_PLAN_LIMIT",
                hint="Review your workspace plan and connected repositories in Elva.",
            ) from exc
        raise default_error(exc, action="Repository request") from exc


def _scope(base_url: str, workspace: str | None) -> tuple[str, RepoListResult]:
    token = get_access_token(base_url=base_url)
    company_id = resolve_workspace(base_url=base_url, token=token, workspace=workspace).id
    payload = _api(base_url, token, f"/api/repos?companyId={company_id}")
    if not isinstance(payload, dict) or payload.get("companyId") != company_id:
        raise ApiError(
            "The API did not confirm the requested repository workspace.",
            code="ELVA_REPO_SCOPE",
            hint="Update the Elva API to support workspace-scoped repository sync.",
        )
    rows = payload.get("repos")
    if not isinstance(rows, list):
        raise _unexpected()
    return token, RepoListResult(company_id, tuple(_repository(row, company_id) for row in rows))


def list_repos(*, base_url: str, workspace: str | None) -> RepoListResult:
    return _scope(base_url, workspace)[1]


def _validate_wait(wait_timeout: float) -> None:
    if not math.isfinite(wait_timeout) or wait_timeout <= 0:
        raise UsageError("--wait-timeout must be a finite, positive number of seconds.")


def connect_repo(
    *,
    base_url: str,
    workspace: str | None,
    repository: str,
    branch: str | None,
    ai_enabled: bool | None,
    wait: bool,
    wait_timeout: float,
    confirm: Callable[[str], None],
    progress: Callable[[str], None],
) -> RepoScanResult:
    owner, name = github_name(repository)
    _validate_wait(wait_timeout)
    if branch is not None and not re.fullmatch(r"[A-Za-z0-9._/-]{1,250}", branch):
        raise UsageError("Invalid branch name.")
    token, scope = _scope(base_url, workspace)
    existing = next(
        (
            r
            for r in scope.repositories
            if f"{r.owner}/{r.name}".lower() == f"{owner}/{name}".lower()
        ),
        None,
    )
    # Preserve reconnect preferences; new connections default to static scanning.
    chosen_branch = branch or (existing.branch if existing else None)
    chosen_ai = (
        ai_enabled if ai_enabled is not None else (existing.ai_enabled if existing else False)
    )
    confirm(f"{owner}/{name}")
    body: dict[str, Any] = {
        "owner": owner,
        "name": name,
        "companyId": scope.company_id,
        "aiEnabled": chosen_ai,
    }
    if chosen_branch is not None:
        body["branch"] = chosen_branch
    payload = _api(base_url, token, "/api/repos", body)
    if not isinstance(payload, dict):
        raise _unexpected()
    repo = _repository(payload, scope.company_id)
    if not payload.get("scanJobId") and payload.get("scanQueueError"):
        return RepoScanResult(
            repo,
            None,
            error=RepoProblem(
                "ELVA_REPO_QUEUE_FULL",
                "Repository connected, but its scan could not be queued.",
                f"Retry with 'elva repo sync {repo.id}' when the queue has space.",
                ExitCode.API,
            ),
        )
    result = RepoScanResult(
        repo, _id(payload.get("scanJobId")), bool(payload.get("alreadyRunning"))
    )
    return _finish(base_url, token, result, wait, wait_timeout, progress)


def sync_repo(
    *,
    base_url: str,
    workspace: str | None,
    repository: str,
    wait: bool,
    wait_timeout: float,
    confirm: Callable[[str], None],
    progress: Callable[[str], None],
) -> RepoScanResult:
    _validate_wait(wait_timeout)
    reference = (
        repository.lower()
        if _ID.fullmatch(repository)
        else "/".join(github_name(repository)).lower()
    )
    token, scope = _scope(base_url, workspace)
    matches = [r for r in scope.repositories if reference in {r.id, f"{r.owner}/{r.name}".lower()}]
    if len(matches) != 1:
        raise UsageError(
            "Repository is not uniquely connected in this workspace.",
            hint="Run 'elva repo list', or connect it with 'elva repo connect OWNER/REPO'.",
        )
    repo = matches[0]
    confirm(f"{repo.owner}/{repo.name}")
    payload = _api(base_url, token, f"/api/repos/{repo.id}/rescan", {"companyId": scope.company_id})
    if not isinstance(payload, dict):
        raise _unexpected()
    result = RepoScanResult(
        repo, _id(payload.get("scanJobId")), bool(payload.get("alreadyRunning"))
    )
    return _finish(base_url, token, result, wait, wait_timeout, progress)


def scan_status(
    *,
    base_url: str,
    workspace: str | None,
    job_id: str,
    wait: bool,
    wait_timeout: float,
    progress: Callable[[str], None],
) -> RepoScanResult:
    _validate_wait(wait_timeout)
    if not _ID.fullmatch(job_id):
        raise UsageError(
            "Expected the scan job ID returned by 'elva repo connect' or 'elva repo sync'."
        )
    token, scope = _scope(base_url, workspace)
    job = _job(base_url, token, job_id.lower())
    repo = next((r for r in scope.repositories if r.id == job.repo_id), None)
    if repo is None:
        raise UsageError("This scan does not belong to a repository in the selected workspace.")
    return _finish(
        base_url, token, RepoScanResult(repo, job.id, job=job), wait, wait_timeout, progress
    )


def _job(base_url: str, token: str, job_id: str) -> RepoJob:
    row = _api(base_url, token, f"/api/catalog/jobs/{job_id}")
    if not isinstance(row, dict) or row.get("id") != job_id:
        raise _unexpected()
    progress = row.get("progress")
    if (
        isinstance(progress, bool)
        or not isinstance(progress, (int, float))
        or not math.isfinite(progress)
        or not 0 <= progress <= 100
    ):
        raise _unexpected()
    if not isinstance(row.get("stats"), dict) or not isinstance(row.get("errors"), list):
        raise _unexpected()
    if any(not isinstance(item, dict) for item in row["errors"]):
        raise _unexpected()
    collections = row.get("collections")
    if collections is not None:
        if not isinstance(collections, dict):
            raise _unexpected()
        for key in ("created", "updated", "unchanged", "removed"):
            refs = collections.get(key)
            if not isinstance(refs, list) or any(not isinstance(ref, dict) for ref in refs):
                raise _unexpected()
        _optional_string(collections, "skipped")
    return RepoJob(
        id=job_id,
        repo_id=_id(row.get("repoId")),
        status=_string(row, "status"),
        progress=float(progress),
        current_step=_optional_string(row, "currentStep"),
        stats=row["stats"],
        errors=tuple(row["errors"]),
        collections=collections,
        quality=row.get("quality"),
        commit_sha=_optional_string(row, "commitSha"),
        started_at=_optional_string(row, "startedAt"),
        finished_at=_optional_string(row, "finishedAt"),
    )


def _finish(
    base_url: str,
    token: str,
    result: RepoScanResult,
    wait: bool,
    wait_timeout: float,
    progress: Callable[[str], None],
) -> RepoScanResult:
    job_id = result.scan_job_id
    assert job_id is not None
    resume = f"Inspect with 'elva repo status {job_id}' in the same workspace."
    deadline = time.monotonic() + wait_timeout
    request_limit = request_timeout(30.0)
    last_progress: tuple[str, float, str | None] | None = None
    if wait:
        progress(f"Scan {job_id}. {resume} Ctrl-C stops waiting; the scan continues on Elva.")
    try:
        while True:
            job = result.job
            if job is not None:
                if job.repo_id != result.repository.id:
                    raise _unexpected()
                marker = (job.status, job.progress, job.current_step)
                if wait and marker != last_progress:
                    progress(f"{job.progress:g}% {job.status}: {job.current_step or ''}")
                    last_progress = marker
                if job.status in _TERMINAL:
                    return _terminal(result, resume)
            if not wait:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApiError(
                    "Stopped waiting; the remote scan may still be running.",
                    code="ELVA_REPO_WAIT_TIMEOUT",
                    hint=resume,
                )
            # Bound each poll by both the user's HTTP timeout and remaining wait.
            with use_timeout(lambda: min(request_limit, max(0.001, deadline - time.monotonic()))):
                job = _job(base_url, token, job_id)
            if job.repo_id != result.repository.id:
                raise _unexpected()
            result = replace(result, job=job)
            if job.status not in _TERMINAL:
                time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
    except ElvaError as exc:
        return replace(
            result,
            error=RepoProblem(
                exc.code, exc.message, f"{exc.hint or ''} {resume}".strip(), exc.exit_code
            ),
        )


def _terminal(result: RepoScanResult, resume: str) -> RepoScanResult:
    job = result.job
    assert job is not None
    problem: RepoProblem | None = None
    if job.status in {"failed", "cancelled"}:
        problem = RepoProblem(
            "ELVA_REPO_SCAN_FAILED" if job.status == "failed" else "ELVA_REPO_SCAN_CANCELLED",
            f"Repository scan {job.status}.",
            resume,
            ExitCode.API if job.status == "failed" else ExitCode.USAGE,
        )
    elif job.collections is None or job.collections.get("skipped"):
        problem = RepoProblem(
            "ELVA_REPO_SYNC_INCOMPLETE",
            "Scan finished without confirming collection sync: "
            + str((job.collections or {}).get("skipped") or "no collection results returned"),
            "Review the scan in Elva before retrying.",
            ExitCode.VALIDATION,
        )
    return replace(result, error=problem)
