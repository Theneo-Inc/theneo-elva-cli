"""Turn the names a person types into the ids the API wants.

`--workspace` and `--collection` are names because that is what the web app
shows and what someone can remember; every collection route is keyed by
ObjectId. This module is the translation, and it accepts an id directly so a
script that already has one pays for no extra lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.errors import ApiError, UsageError

_OBJECT_ID = re.compile(r"^[0-9a-fA-F]{24}$")


@dataclass(frozen=True)
class Target:
    id: str
    name: str


def resolve_workspace(*, base_url: str, token: str, workspace: str | None) -> Target:
    """The workspace to act in.

    With nothing given, a single-workspace account resolves to that one -- the
    unambiguous case should not need a flag. More than one is a question the
    CLI cannot answer for the user, so it lists them and stops.
    """
    if workspace and _OBJECT_ID.match(workspace):
        return Target(id=workspace, name=workspace)

    try:
        payload = get_json(f"{base_url}/api/companies/workspaces", token=token)
    except HttpError as exc:
        raise default_error(exc, action="Looking up your workspaces") from exc

    found = [
        Target(id=str(row["id"]), name=str(row.get("name") or row["id"]))
        for row in _rows(payload, "workspaces")
        if row.get("id")
    ]
    slugs = {
        str(row["id"]): str(row.get("companySlug") or "")
        for row in _rows(payload, "workspaces")
        if row.get("id")
    }

    if not found:
        raise UsageError(
            "your account has no workspaces",
            hint="Create one at https://app.getelva.ai, then try again.",
        )

    if workspace is None:
        if len(found) == 1:
            return found[0]
        raise UsageError(
            "more than one workspace, so there is no obvious default",
            hint=f"Pass --workspace with one of: {_names(found)}",
        )

    wanted = workspace.strip().lower()
    matches = [
        target
        for target in found
        if target.name.lower() == wanted or slugs.get(target.id, "").lower() == wanted
    ]
    return _exactly_one(matches, kind="workspace", wanted=workspace, available=found)


def resolve_collection(*, base_url: str, token: str, company_id: str, collection: str) -> Target:
    """The collection to act on, by name or by id."""
    if _OBJECT_ID.match(collection):
        return Target(id=collection, name=collection)

    try:
        payload = get_json(f"{base_url}/api/companies/{company_id}/collections", token=token)
    except HttpError as exc:
        if exc.status == 404:
            raise UsageError(
                "that workspace does not exist, or you cannot see it",
                hint="Check --workspace.",
            ) from exc
        raise default_error(exc, action="Listing collections") from exc

    found = [
        Target(id=str(row["id"]), name=str(row.get("name") or row["id"]))
        for row in _rows(payload, "collections")
        if row.get("id")
    ]
    wanted = collection.strip().lower()
    matches = [target for target in found if target.name.lower() == wanted]
    return _exactly_one(matches, kind="collection", wanted=collection, available=found)


def _rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ApiError(f"The server returned an unexpected {key} response.")
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise ApiError(f"The server returned an unexpected {key} response.")
    return [row for row in rows if isinstance(row, dict)]


def _names(targets: list[Target]) -> str:
    shown = sorted(target.name for target in targets)[:10]
    return ", ".join(shown)


def _exactly_one(
    matches: list[Target], *, kind: str, wanted: str, available: list[Target]
) -> Target:
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UsageError(
            f"no {kind} named {wanted!r}",
            hint=(
                f"Available: {_names(available)}"
                if available
                else f"This workspace has no {kind}s yet."
            ),
        )
    raise UsageError(
        f"{len(matches)} {kind}s are named {wanted!r}",
        hint=f"Pass the id instead: {', '.join(target.id for target in matches)}",
    )
