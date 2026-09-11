"""`elva mcp logs <slug>`: an MCP server's recent request history."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import quote, urlencode

from elva_cli.auth import get_access_token, refresh_now
from elva_cli.core.api.http import HttpError, UnreachableError, default_error, get_json
from elva_cli.core.api.targets import Target, resolve_workspace
from elva_cli.core.services.mcp_common import (
    as_int,
    as_opt_str,
    as_str,
    unknown_server,
    workspace_forbidden,
)
from elva_cli.core.services.mcp_logs_result import LogEntry, McpLogsResult
from elva_cli.errors import ApiError, ElvaError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_T = TypeVar("_T")

_UNEXPECTED_RESPONSE = "The server returned an unexpected response while reading MCP logs."
_BACKEND_MAX_LIMIT = 100
_EPOCH = "1970-01-01T00:00:00.000Z"
_DEFAULT_INTERVAL = 2.0

_FOLLOW_BACKOFF_SECONDS = (2.0, 4.0, 8.0, 16.0, 32.0)
_FOLLOW_GAVE_UP = "Lost contact with the server while following MCP logs."


class _TransientPollError(Exception):
    """A logs request failed in a way worth retrying (5xx, 429, or the server
    was unreachable)."""


def _is_transient(status: int) -> bool:
    """A 429 or any 5xx: the request was well-formed and may work on a retry."""
    return status == 429 or status >= 500


@dataclass(frozen=True)
class _Page:
    entries: list[LogEntry]
    total: int


def fetch_logs_window(
    *, base_url: str, workspace: str | None, slug: str, page: int, limit: int
) -> McpLogsResult:
    """Exactly the CLI's own `page`/`limit` window, stitched from as many
    backend pages (each <=100) as that takes.
    """
    token, reauth, space = _resolve(base_url=base_url, workspace=workspace)
    try:
        return _window(base_url, space.id, slug, page=page, limit=limit, token=token, reauth=reauth)
    except _TransientPollError as exc:
        raise _transient_as_error(exc) from exc


def follow_logs(
    *,
    base_url: str,
    workspace: str | None,
    slug: str,
    limit: int,
    sleep: Callable[[float], None] = time.sleep,
    interval: float = _DEFAULT_INTERVAL,
    notify: Callable[[str], None] | None = None,
) -> Iterator[tuple[LogEntry, ...]]:
    """Yields the most recent `limit` entries once (oldest first, so they
    print in the order they happened), then polls forever, yielding
    whatever's new each time.
    """
    token, reauth, space = _resolve(base_url=base_url, workspace=workspace)
    backlog = _with_retry(
        lambda: _window(base_url, space.id, slug, page=1, limit=limit, token=token, reauth=reauth),
        sleep=sleep,
        notify=notify,
    )
    chronological = tuple(reversed(backlog.entries))
    yield chronological

    last = chronological[-1] if chronological else None
    since_time = last.time if last else _EPOCH
    since_ids = _ids_at(chronological, since_time)

    while True:
        sleep(interval)
        fresh = _poll_with_retry(
            base_url,
            space.id,
            slug,
            token=token,
            reauth=reauth,
            since_time=since_time,
            since_ids=since_ids,
            sleep=sleep,
            notify=notify,
        )
        if fresh:
            newest = fresh[-1].time
            if newest == since_time:
                since_ids = since_ids | _ids_at(fresh, newest)
            else:
                since_time = newest
                since_ids = _ids_at(fresh, newest)
        yield fresh


def _ids_at(entries: tuple[LogEntry, ...], moment: str) -> frozenset[str]:
    """Every id sharing the boundary timestamp. `from=<time>` re-serves all of
    them on the next poll."""
    return frozenset(entry.id for entry in entries if entry.time == moment)


def _resolve(*, base_url: str, workspace: str | None) -> tuple[str, Callable[[str], str], Target]:
    token = get_access_token(base_url=base_url)
    reauth = _reauth(base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)
    return token, reauth, space


def _reauth(base_url: str) -> Callable[[str], str]:
    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    return reauth


def _window(
    base_url: str,
    company_id: str,
    slug: str,
    *,
    page: int,
    limit: int,
    token: str,
    reauth: Callable[[str], str],
) -> McpLogsResult:
    if limit <= _BACKEND_MAX_LIMIT:
        result = _get_page(
            base_url, company_id, slug, page=page, limit=limit, token=token, reauth=reauth
        )
        return McpLogsResult(
            entries=tuple(result.entries), total=result.total, page=page, limit=limit
        )

    offset = (page - 1) * limit
    skip = offset % _BACKEND_MAX_LIMIT
    backend_page = offset // _BACKEND_MAX_LIMIT + 1

    collected: list[LogEntry] = []
    total = 0
    while len(collected) < skip + limit:
        result = _get_page(
            base_url,
            company_id,
            slug,
            page=backend_page,
            limit=_BACKEND_MAX_LIMIT,
            token=token,
            reauth=reauth,
        )
        total = result.total
        collected.extend(result.entries)
        if len(result.entries) < _BACKEND_MAX_LIMIT or len(collected) >= total:
            break
        backend_page += 1

    window = tuple(collected[skip : skip + limit])
    return McpLogsResult(entries=window, total=total, page=page, limit=limit)


def _fetch_logs_page(url: str, *, token: str, reauth: Callable[[str], str], slug: str) -> _Page:
    """One GET against the logs endpoint. A network failure or a 5xx/429 comes
    back as `_TransientPollError`."""
    try:
        body = get_json(url, token=token, reauth=reauth)
    except UnreachableError as exc:
        raise _TransientPollError(str(exc)) from exc
    except HttpError as exc:
        if _is_transient(exc.status):
            raise _TransientPollError(f"HTTP {exc.status}") from exc
        raise _logs_error(exc, slug=slug) from exc
    return _parse_page(body)


def _get_page(
    base_url: str,
    company_id: str,
    slug: str,
    *,
    page: int,
    limit: int,
    token: str,
    reauth: Callable[[str], str],
) -> _Page:
    query = urlencode({"page": page, "limit": limit, "sort": "time", "order": "desc"})
    url = f"{base_url}/api/companies/{company_id}/mcps/{quote(slug, safe='')}/logs?{query}"
    return _fetch_logs_page(url, token=token, reauth=reauth, slug=slug)


def _with_retry(
    operation: Callable[[], _T],
    *,
    sleep: Callable[[float], None],
    notify: Callable[[str], None] | None,
) -> _T:
    """Run `operation`, retrying through `_FOLLOW_BACKOFF_SECONDS` on a
    `_TransientPollError`. A non-transient error (bad slug, lost access,
    malformed body) propagates on the first try; exhausting the retries
    raises ApiError."""
    last: _TransientPollError | None = None
    for delay in (0.0, *_FOLLOW_BACKOFF_SECONDS):
        if delay:
            if notify is not None:
                notify(f"server is unavailable; retrying in {delay:.0f}s")
            sleep(delay)
        try:
            return operation()
        except _TransientPollError as exc:
            last = exc
    raise ApiError(_FOLLOW_GAVE_UP) from (last.__cause__ if last else None)


def _poll_with_retry(
    base_url: str,
    company_id: str,
    slug: str,
    *,
    token: str,
    reauth: Callable[[str], str],
    since_time: str,
    since_ids: frozenset[str],
    sleep: Callable[[float], None],
    notify: Callable[[str], None] | None,
) -> tuple[LogEntry, ...]:
    return _with_retry(
        lambda: _poll_new(
            base_url,
            company_id,
            slug,
            token=token,
            reauth=reauth,
            since_time=since_time,
            since_ids=since_ids,
        ),
        sleep=sleep,
        notify=notify,
    )


def _poll_new(
    base_url: str,
    company_id: str,
    slug: str,
    *,
    token: str,
    reauth: Callable[[str], str],
    since_time: str,
    since_ids: frozenset[str],
) -> tuple[LogEntry, ...]:
    collected: list[LogEntry] = []
    seen: set[str] = set()
    backend_page = 1
    while True:
        query = urlencode(
            {
                "page": backend_page,
                "limit": _BACKEND_MAX_LIMIT,
                "sort": "time",
                "order": "asc",
                "from": since_time,
            }
        )
        url = f"{base_url}/api/companies/{company_id}/mcps/{quote(slug, safe='')}/logs?{query}"
        page = _fetch_logs_page(url, token=token, reauth=reauth, slug=slug)
        for entry in page.entries:
            if entry.id in since_ids or entry.id in seen:
                continue
            seen.add(entry.id)
            collected.append(entry)
        if len(page.entries) < _BACKEND_MAX_LIMIT:
            break
        backend_page += 1
    return tuple(collected)


def _parse_page(body: Any) -> _Page:
    if not isinstance(body, dict) or not isinstance(body.get("logs"), list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    total = body.get("total")
    if not isinstance(total, int):
        raise ApiError(_UNEXPECTED_RESPONSE)
    rows = [row for row in body["logs"] if isinstance(row, dict)]
    return _Page(entries=[_to_entry(row) for row in rows], total=total)


def _to_entry(row: dict[str, Any]) -> LogEntry:
    tokens = row.get("tokens")
    return LogEntry(
        id=as_str(row.get("id")),
        time=as_str(row.get("time")),
        tool=as_str(row.get("tool")),
        status=as_int(row.get("status")),
        duration_ms=as_int(row.get("durationMs")),
        agent=as_opt_str(row.get("agent")),
        agent_id=as_opt_str(row.get("agentId")),
        client_id=as_opt_str(row.get("clientId")),
        user_id=as_opt_str(row.get("userId")),
        error=as_opt_str(row.get("error")),
        tokens=tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None,
    )


def _logs_error(error: HttpError, *, slug: str) -> Exception:
    if error.status in (400, 404):
        return unknown_server(slug)
    if error.status == 403:
        return workspace_forbidden()
    return default_error(error, action="Reading MCP logs")


def _transient_as_error(exc: _TransientPollError) -> ElvaError:
    """The one-shot window doesn't retry, so a transient failure becomes the
    same user-facing error the un-wrapped exception would have produced."""
    cause = exc.__cause__
    if isinstance(cause, HttpError):
        return default_error(cause, action="Reading MCP logs")
    if isinstance(cause, ElvaError):  # UnreachableError
        return cause
    return ApiError(_UNEXPECTED_RESPONSE)
