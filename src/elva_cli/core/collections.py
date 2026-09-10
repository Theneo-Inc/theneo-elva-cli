"""`elva collection list`: the collections in a workspace.

A read-only listing that mirrors what the web app shows. "Workspace" is the
product's word for what the API calls a companyId; that id is resolved here (via
the same ELVA-156 resolver every other command uses) and is never handed back
for printing. `resolve_collection` turns the name or id a person typed into one
summary and is deliberately written to be reused by `show` and `endpoints` when
they land -- it never prompts, so an ambiguous match is raised, not resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.errors import ApiError, AuthError, ElvaError, UsageError

if TYPE_CHECKING:
    from elva_cli.context import Ctx


@dataclass(frozen=True)
class CollectionSummary:
    """The subset of a collection a listing needs. No companyId: see module doc."""

    id: str
    name: str
    spec_uploaded: bool
    endpoint_count: int | None
    labels: tuple[str, ...]
    is_demo: bool
    updated_at: str | None


class CollectionSummaries(tuple[CollectionSummary, ...]):
    """The output envelope for a listing.

    A distinct type so the output layer dispatches a table on it, while `--json`
    still serialises it as a bare array (a list has no wrapper key). Kept apart
    from `list_collections`, which returns a plain list, so a caller that only
    wants the data is never handed a presentation type.
    """

    __slots__ = ()


class AmbiguousCollection(UsageError):  # noqa: N818  named for the domain, not the -Error suffix
    """More than one collection matches the name given.

    Carries the candidates so a command can offer a picker later; core never
    prompts, so it stops here with them attached rather than choosing one.
    """

    code = "ELVA_AMBIGUOUS_COLLECTION"

    def __init__(self, candidates: list[CollectionSummary]) -> None:
        self.candidates = tuple(candidates)
        name = self.candidates[0].name
        ids = ", ".join(candidate.id for candidate in self.candidates)
        super().__init__(
            f"{len(self.candidates)} collections are named {name!r}",
            hint=f"Pass the id instead: {ids}",
        )


def list_collections(ctx: Ctx) -> list[CollectionSummary]:
    """Every collection in the resolved workspace, sorted by name for stable output."""
    base_url = ctx.settings.base_url
    token = get_access_token(base_url=base_url)
    company_id = _workspace_id(ctx, base_url=base_url, token=token)

    try:
        payload = get_json(f"{base_url}/api/companies/{company_id}/collections", token=token)
    except HttpError as exc:
        raise _list_error(exc) from exc

    summaries = [_summary(row) for row in _rows(payload) if _row_id(row)]
    return sorted(summaries, key=lambda summary: (summary.name.lower(), summary.id))


def resolve_collection(ctx: Ctx, ref: str) -> CollectionSummary:
    """The one collection a person means by `ref`: an exact id, else an exact name.

    Zero matches is a usage error naming `ref`; more than one is
    `AmbiguousCollection` carrying the candidates, so a caller can disambiguate
    however it likes. Built for reuse by `show` and `endpoints`.
    """
    summaries = list_collections(ctx)

    for summary in summaries:
        if summary.id == ref:
            return summary

    by_name = [summary for summary in summaries if summary.name == ref]
    if len(by_name) == 1:
        return by_name[0]
    if not by_name:
        raise UsageError(
            f"no collection named {ref!r} in this workspace",
            hint="Run 'elva collection list' to see what is there.",
        )
    raise AmbiguousCollection(by_name)


def _workspace_id(ctx: Ctx, *, base_url: str, token: str) -> str:
    """The companyId to list, via the shared workspace resolver.

    resolve_workspace (ELVA-156) is shared with the other commands, so its
    messages are left as they are -- except that a workspace-selection failure
    reached from here should also point at ELVA_WORKSPACE, the env form of the
    flag its hint already names.
    """
    try:
        target = resolve_workspace(base_url=base_url, token=token, workspace=ctx.settings.workspace)
    except UsageError as exc:
        raise _also_name_the_env(exc) from exc
    return target.id


def _also_name_the_env(exc: UsageError) -> UsageError:
    hint = exc.hint
    if hint and "--workspace" in hint and "ELVA_WORKSPACE" not in hint:
        hint = f"{hint} You can also set ELVA_WORKSPACE."
    return UsageError(str(exc), hint=hint)


def _list_error(exc: HttpError) -> ElvaError:
    """Map a rejected listing. 403/404 are about the workspace, not the token."""
    if exc.status == 401:
        return AuthError("Your credentials are no longer valid.")
    if exc.status in (403, 404):
        return UsageError(
            "that workspace does not exist, or you cannot see it",
            hint="Check --workspace or ELVA_WORKSPACE.",
        )
    return default_error(exc, action="Listing collections")


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ApiError("The server returned an unexpected collections response.")
    rows = payload.get("collections")
    if not isinstance(rows, list):
        raise ApiError("The server returned an unexpected collections response.")
    return [row for row in rows if isinstance(row, dict)]


def _summary(row: dict[str, Any]) -> CollectionSummary:
    return CollectionSummary(
        id=_row_id(row) or "",
        name=_text(row.get("name")) or "(unnamed)",
        # No hasSpec field yet (tracked separately); a specTitle is the proxy.
        spec_uploaded=bool(_text(row.get("specTitle"))),
        endpoint_count=_int(row.get("endpointCount")),
        labels=_labels(row.get("labels")),
        is_demo=bool(row.get("isDemo")),
        updated_at=_text(row.get("updatedAt")),
    )


def _row_id(row: dict[str, Any]) -> str | None:
    for key in ("id", "_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _labels(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _int(value: Any) -> int | None:
    # bool is an int subclass; a flag that leaked into this field is not a count.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
