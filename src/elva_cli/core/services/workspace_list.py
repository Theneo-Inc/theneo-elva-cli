from __future__ import annotations

import re
from typing import Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.core.services.workspace_list_result import WorkspaceItem, WorkspaceListResult
from elva_cli.errors import ApiError

_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
_UNEXPECTED_RESPONSE = "The server returned an unexpected workspaces response."


def list_workspaces(
    *,
    base_url: str,
    active_workspace: str | None,
    active_origin: str,
) -> WorkspaceListResult:
    token = get_access_token(base_url=base_url)
    try:
        payload = get_json(f"{base_url}/api/companies/workspaces", token=token)
    except HttpError as exc:
        raise default_error(exc, action="Listing workspaces") from exc

    rows = _rows(payload)
    configured = active_workspace.strip() if active_workspace else None
    if not rows:
        return WorkspaceListResult(
            workspaces=[],
            configured_workspace=configured or None,
            configured_origin=active_origin if configured else None,
            configured_matched=configured is None,
        )

    items = _build_items(rows, active_workspace=configured, active_origin=active_origin)
    matched = any(item.active for item in items) or configured is None
    return WorkspaceListResult(
        workspaces=items,
        configured_workspace=configured if not matched else None,
        configured_origin=active_origin if (configured and not matched) else None,
        configured_matched=matched,
    )


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    rows = payload.get("workspaces")
    if not isinstance(rows, list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    return [row for row in rows if isinstance(row, dict)]


def _build_items(
    rows: list[dict[str, Any]],
    *,
    active_workspace: str | None,
    active_origin: str,
) -> list[WorkspaceItem]:
    auto_select = active_workspace is None and len(rows) == 1
    wanted = active_workspace.lower() if active_workspace else None
    match_by_id = active_workspace is not None and _OBJECT_ID.match(wanted or "") is not None

    items: list[WorkspaceItem] = []
    for row in rows:
        raw_name = str(row.get("name") or "").strip()
        raw_slug = str(row.get("companySlug") or "").strip()
        if not raw_name and not raw_slug:
            continue

        name = raw_name or "(unnamed)"
        slug = raw_slug or "-"
        role = str(row.get("role") or "").strip() or "-"

        is_active = False
        source: str | None = None
        if auto_select:
            is_active = True
            source = "auto"
        elif wanted is not None:
            if match_by_id:
                is_active = str(row.get("id") or "").lower() == wanted
            else:
                is_active = raw_name.lower() == wanted or raw_slug.lower() == wanted
            if is_active:
                source = active_origin

        items.append(
            WorkspaceItem(
                name=name,
                slug=slug,
                role=role,
                active=is_active,
                active_source=source,
            )
        )
    return items
