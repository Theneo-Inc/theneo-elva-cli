"""Read-only access to the collections in a workspace.

Nothing here touches settings or prompts: the command layer resolves the
workspace id and passes it down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.core.openapi_ops import Operation, extract_operations, parse_spec
from elva_cli.errors import ApiError, AuthError, ElvaError, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable


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
    """The output envelope for a listing, so --json stays a bare array."""

    __slots__ = ()


@dataclass(frozen=True)
class McpSummary:
    """One MCP server published from a collection."""

    deployment_id: str
    slug: str
    name: str
    status: str
    tool_count: int | None


@dataclass(frozen=True)
class CollectionDetail:
    """One collection in full, as `collection show` presents it."""

    id: str
    name: str
    description: str | None
    spec_uploaded: bool
    spec_title: str | None
    spec_version: str | None
    labels: tuple[str, ...]
    source: str | None
    is_demo: bool
    endpoint_count: int
    created_at: str | None
    updated_at: str | None
    mcps: tuple[McpSummary, ...]


class AmbiguousCollection(UsageError):  # noqa: N818  named for the domain, not the -Error suffix
    """More than one collection matches. Carries the candidates; core never prompts."""

    code = "ELVA_AMBIGUOUS_COLLECTION"

    def __init__(self, candidates: list[CollectionSummary]) -> None:
        self.candidates = tuple(candidates)
        name = self.candidates[0].name
        ids = ", ".join(candidate.id for candidate in self.candidates)
        super().__init__(
            f"{len(self.candidates)} collections are named {name!r}",
            hint=f"Pass the id instead: {ids}",
        )


def list_collections(
    base_url: str,
    token: str,
    company_id: str,
    reauth: Callable[[str], str] | None = None,
) -> list[CollectionSummary]:
    """Every collection in the workspace, sorted by name for stable output."""
    try:
        payload = get_json(
            f"{base_url}/api/companies/{company_id}/collections", token=token, reauth=reauth
        )
    except HttpError as exc:
        raise _list_error(exc) from exc

    summaries = [_summary(row) for row in _rows(payload) if _row_id(row)]
    return sorted(summaries, key=lambda summary: (summary.name.lower(), summary.id))


def resolve_collection(
    base_url: str,
    token: str,
    company_id: str,
    ref: str,
    reauth: Callable[[str], str] | None = None,
) -> CollectionSummary:
    """The one collection `ref` means: an id, else a name.

    Ids and names both match case-insensitively and ignore surrounding space,
    so the same `--collection` value works across every command.
    """
    summaries = list_collections(base_url, token, company_id, reauth)
    wanted = ref.strip().casefold()

    for summary in summaries:
        if summary.id.casefold() == wanted:
            return summary

    by_name = [summary for summary in summaries if summary.name.strip().casefold() == wanted]
    if len(by_name) == 1:
        return by_name[0]
    if not by_name:
        raise UsageError(
            f"no collection named {ref!r} in this workspace",
            hint=_available(summaries),
        )
    raise AmbiguousCollection(by_name)


def get_collection(base_url: str, token: str, company_id: str, ref: str) -> CollectionDetail:
    """One collection in full. `ref` is resolved to an id first."""
    summary = resolve_collection(base_url, token, company_id, ref)
    url = f"{base_url}/api/companies/{company_id}/collections/{summary.id}"
    try:
        payload = get_json(url, token=token)
    except HttpError as exc:
        raise _detail_error(exc, name=summary.name) from exc

    doc = _document(payload)
    return CollectionDetail(
        id=_row_id(doc) or summary.id,
        name=_text(doc.get("name")) or summary.name,
        description=_text(doc.get("description")),
        # No hasSpec field yet (tracked separately); a specTitle is the proxy.
        spec_uploaded=bool(_text(doc.get("specTitle"))),
        spec_title=_text(doc.get("specTitle")),
        spec_version=_text(doc.get("specVersion")),
        labels=_labels(doc.get("labels")),
        source=_text(doc.get("source")),
        is_demo=bool(doc.get("isDemo")),
        endpoint_count=_endpoint_count(doc),
        created_at=_timestamp(doc, "createdAt", "_createdAt"),
        updated_at=_timestamp(doc, "updatedAt", "_updatedAt"),
        mcps=_mcps(payload),
    )


def get_collection_operations(
    base_url: str, token: str, company_id: str, ref: str
) -> list[Operation]:
    """The operations in a collection's uploaded OpenAPI spec.

    Keeps the exit codes apart: a parse failure is 4 (the spec is wrong), an
    unreachable server or missing stored file is 5 (the transport is wrong).
    """
    summary = resolve_collection(base_url, token, company_id, ref)
    url = f"{base_url}/api/companies/{company_id}/collections/{summary.id}/spec"
    try:
        payload = get_json(url, token=token)
    except HttpError as exc:
        raise _spec_error(exc, name=summary.name) from exc

    return extract_operations(parse_spec(_spec_text(payload)))


def _spec_text(payload: Any) -> str:
    """The raw spec out of a {"spec": "<text>"} envelope."""
    if isinstance(payload, dict):
        spec = payload.get("spec")
        if isinstance(spec, str):
            return spec
    raise ApiError("The server returned an unexpected spec response.")


def _spec_error(exc: HttpError, *, name: str) -> ElvaError:
    """Map a rejected spec fetch.

    The backend returns 404 for two different things: no spec uploaded (exit 2,
    the user fixes it) and a record pointing at a file missing from storage
    (exit 5, we do).
    """
    if exc.status == 401:
        return AuthError("Your credentials are no longer valid.")
    if exc.status == 404:
        if "no spec" in (exc.detail or "").lower():
            return UsageError(
                f"collection {name!r} has no spec uploaded",
                hint="Upload one with 'elva import spec'.",
            )
        # "Spec file not found in storage", or any other 404: the record is there
        # but the file behind it is not. That is a storage fault to retry, not a
        # usage error the caller can fix.
        return ApiError(f"the spec for {name!r} could not be retrieved (HTTP 404)")
    return default_error(exc, action="Fetching the spec")


def _available(summaries: list[CollectionSummary]) -> str:
    """Name what is there, so a typo does not cost another command."""
    if not summaries:
        return "This workspace has no collections yet."
    shown = sorted(summary.name for summary in summaries)[:10]
    return f"Available: {', '.join(shown)}"


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


def _detail_error(exc: HttpError, *, name: str) -> ElvaError:
    """Map a rejected detail call. The workspace already resolved, so this is about
    the collection.
    """
    if exc.status == 401:
        return AuthError("Your credentials are no longer valid.")
    if exc.status in (403, 404):
        return UsageError(
            f"collection {name!r} not found",
            hint="It may have been deleted; run 'elva collection list'.",
        )
    return default_error(exc, action="Fetching the collection")


def _document(payload: Any) -> dict[str, Any]:
    """The collection out of a {"collection": {...}} envelope."""
    if not isinstance(payload, dict):
        raise ApiError("The server returned an unexpected collection response.")
    doc = payload.get("collection")
    if not isinstance(doc, dict):
        raise ApiError("The server returned an unexpected collection response.")
    return doc


def _mcps(payload: Any) -> tuple[McpSummary, ...]:
    """The MCP servers the detail route returns alongside the document."""
    if not isinstance(payload, dict):
        return ()
    rows = payload.get("mcps")
    if not isinstance(rows, list):
        return ()
    return tuple(
        McpSummary(
            deployment_id=_text(row.get("deploymentId")) or "",
            slug=_text(row.get("mcpSlug")) or "",
            name=_text(row.get("mcpName")) or _text(row.get("mcpSlug")) or "(unnamed)",
            status=_text(row.get("status")) or "unknown",
            tool_count=_int(row.get("toolCount")),
        )
        for row in rows
        if isinstance(row, dict)
    )


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


def _endpoint_count(doc: dict[str, Any]) -> int:
    """The detail route sends the endpoints array; its length is the count."""
    endpoints = doc.get("endpoints")
    return len(endpoints) if isinstance(endpoints, list) else 0


def _timestamp(doc: dict[str, Any], *keys: str) -> str | None:
    """The first of `keys` the document actually carries; the API is not
    consistent about the leading underscore."""
    for key in keys:
        value = _text(doc.get(key))
        if value is not None:
            return value
    return None


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
