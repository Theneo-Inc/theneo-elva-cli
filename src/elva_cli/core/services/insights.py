"""Run the same authoritative review engine as Elva's API Insights page."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token, refresh_now
from elva_cli.core.api.http import HttpError, default_error, get_json, send_text
from elva_cli.core.api.targets import resolve_collection, resolve_workspace
from elva_cli.core.services.insights_result import InsightChecks, InsightReview
from elva_cli.errors import ApiError, UsageError, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
CATEGORIES = ("Design", "DeveloperExperience", "AIReadiness", "Security")


def list_checks(*, base_url: str, category: str | None) -> InsightChecks:
    _category(category)
    try:
        data = get_json(f"{base_url}/api/review/checks", token=None)
    except HttpError as exc:
        raise default_error(exc, action="Listing insight checks") from exc
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ApiError("Unexpected insight check catalogue.")
    return InsightChecks(
        tuple(row for row in data if category is None or row.get("category") == category)
    )


def review_file(*, base_url: str, path: Path | None, stdin: bytes | None) -> InsightReview:
    if stdin is not None:
        raw, source = stdin, "stdin"
    elif path is not None:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError as exc:
            raise UsageError(f"Could not read spec file: {path}") from exc
        source = str(path)
    else:
        raise UsageError("Pass an OpenAPI file, or '-' to read one from stdin.")
    return InsightReview(source, _review(base_url, raw))


def review_collection(*, base_url: str, workspace: str | None, collection: str) -> InsightReview:
    token = get_access_token(base_url=base_url)

    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)
    target = resolve_collection(
        base_url=base_url, token=token, company_id=space.id, collection=collection, reauth=reauth
    )
    try:
        data = get_json(
            f"{base_url}/api/companies/{space.id}/collections/{target.id}/spec",
            token=token,
            reauth=reauth,
        )
    except HttpError as exc:
        if exc.status == 404 and "no spec" in (exc.detail or "").lower():
            raise UsageError(
                "This collection has no uploaded spec.", hint="Import a spec first."
            ) from exc
        raise default_error(exc, action="Loading the collection spec") from exc
    if not isinstance(data, dict) or not isinstance(data.get("spec"), str):
        raise ApiError("Unexpected collection spec response.")
    return InsightReview(target.name, _review(base_url, data["spec"].encode()), space.id, target.id)


def _review(base_url: str, raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValidationError("Supply a nonempty OpenAPI document no larger than 2 MiB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValidationError("The spec must be UTF-8 YAML or JSON.") from exc
    try:
        data = send_text(f"{base_url}/api/review", token=None, content=content)
    except HttpError as exc:
        if exc.status in {400, 413, 422}:
            raise ValidationError(exc.detail or "The spec could not be reviewed.") from exc
        raise default_error(exc, action="Reviewing the API spec") from exc
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("scorable"), bool)
        or not isinstance(data.get("checks"), list)
        or not isinstance(data.get("scores"), dict)
    ):
        raise ApiError("Unexpected API insights response.")
    score = data.get("overallScore")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= 100
    ):
        raise ApiError("Unexpected API insights score.")
    if any(not isinstance(row, dict) for row in data["checks"]) or any(
        not isinstance(row, dict) for row in data["scores"].values()
    ):
        raise ApiError("Unexpected API insights checks or scores.")
    return data


def _category(category: str | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise UsageError(f"Unknown category. Choose: {', '.join(CATEGORIES)}.")
