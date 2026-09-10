from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.core.services.workspace_switch_result import WorkspaceSwitchResult
from elva_cli.errors import ApiError, UsageError
from elva_cli.settings.writer import resolve_target, set_value

if TYPE_CHECKING:
    from pathlib import Path

_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
_UNEXPECTED_RESPONSE = "The server returned an unexpected workspaces response."


@dataclass(frozen=True)
class _Row:
    name: str
    slug: str


def switch_workspace(
    *,
    base_url: str,
    cwd: Path,
    requested: str,
    use_global: bool,
) -> WorkspaceSwitchResult:
    cleaned = requested.strip()
    if not cleaned:
        raise UsageError(
            "workspace name is required",
            hint="Pass a workspace name or slug.",
        )
    if _OBJECT_ID.match(cleaned.lower()):
        raise UsageError(
            "switch expects a workspace name or slug, not an id",
            hint="Run 'elva workspace list' to see names and slugs.",
        )

    rows = _fetch_rows(base_url)
    if not rows:
        raise UsageError(
            "your account has no workspaces",
            hint="Create one at https://app.getelva.ai, then try again.",
        )

    match = _match(rows, cleaned)
    target = resolve_target(use_global=use_global, cwd=cwd)
    set_value(key="workspace", value=match.slug, target=target)
    return WorkspaceSwitchResult(
        active_name=match.name,
        active_slug=match.slug,
        target_kind=target.kind,
        path=str(target.path),
    )


def fetch_workspace_names(*, base_url: str) -> list[str]:
    rows = _fetch_rows(base_url)
    return [row.name for row in rows]


def _fetch_rows(base_url: str) -> list[_Row]:
    token = get_access_token(base_url=base_url)
    try:
        payload = get_json(f"{base_url}/api/companies/workspaces", token=token)
    except HttpError as exc:
        raise default_error(exc, action="Listing workspaces") from exc
    return _extract_rows(payload)


def _extract_rows(payload: Any) -> list[_Row]:
    if not isinstance(payload, dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    raw = payload.get("workspaces")
    if not isinstance(raw, list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    rows: list[_Row] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        slug = str(entry.get("companySlug") or "").strip()
        if not name or not slug:
            continue
        rows.append(_Row(name=name, slug=slug))
    return rows


def _match(rows: list[_Row], requested: str) -> _Row:
    wanted = requested.lower()
    matches = [row for row in rows if row.name.lower() == wanted or row.slug.lower() == wanted]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise UsageError(
            f"more than one workspace matches {requested!r}",
            hint=f"Candidates: {', '.join(sorted({row.slug for row in matches}))}",
        )
    suggestions = _suggest(rows, wanted)
    hint = (
        f"Did you mean: {', '.join(suggestions)}?"
        if suggestions
        else f"Available: {', '.join(sorted(row.name for row in rows)[:10])}"
    )
    raise UsageError(f"no workspace named {requested!r}", hint=hint)


def _suggest(rows: list[_Row], wanted: str) -> list[str]:
    pool: list[str] = []
    for row in rows:
        pool.append(row.name)
        if row.slug and row.slug.lower() != row.name.lower():
            pool.append(row.slug)
    return difflib.get_close_matches(wanted, pool, n=3, cutoff=0.6)
