"""Turn the names a person types into the ids the API wants.

`--workspace` and `--collection` are names because that is what the web app
shows and what someone can remember; every collection route is keyed by
ObjectId. This module is the translation, and it accepts an id directly so a
script that already has one pays for no extra lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.errors import ApiError, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable

_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")


@dataclass(frozen=True)
class Target:
    id: str
    name: str


def resolve_workspace(
    *,
    base_url: str,
    token: str,
    workspace: str | None,
    reauth: Callable[[str], str] | None = None,
) -> Target:
    """The workspace to act in.

    With nothing given, a single-workspace account resolves to that one -- the
    unambiguous case should not need a flag. More than one is a question the
    CLI cannot answer for the user, so it lists them and stops.
    """
    if workspace and _OBJECT_ID.match(workspace.lower()):
        normalized = workspace.lower()
        return Target(id=normalized, name=normalized)

    try:
        payload = get_json(f"{base_url}/api/companies/workspaces", token=token, reauth=reauth)
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


def resolve_collection(
    *,
    base_url: str,
    token: str,
    company_id: str,
    collection: str,
    reauth: Callable[[str], str] | None = None,
) -> Target:
    """The collection to act on, by name or by id.

    One resolver for the whole CLI: core.collections owns the matching so that
    `--collection` behaves the same here as it does in the collection commands.
    Callers here have no picker, so an ambiguous name becomes a usage error.
    """
    from elva_cli.core.collections import AmbiguousCollection
    from elva_cli.core.collections import resolve_collection as resolve

    try:
        summary = resolve(base_url, token, company_id, collection, reauth)
    except AmbiguousCollection as exc:
        candidates = [Target(id=c.id, name=c.name) for c in exc.candidates]
        raise UsageError(
            f"{len(candidates)} collections are named {collection!r}",
            hint=f"Pass the id instead: {', '.join(t.id for t in candidates)}",
        ) from exc
    return Target(id=summary.id, name=summary.name)


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
