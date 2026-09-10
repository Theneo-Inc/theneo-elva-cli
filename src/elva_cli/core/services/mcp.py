"""`elva mcp list` / `elva mcp show <slug>`: see what MCP servers exist in a
workspace before creating more. Read-only, so both are safe to run
unattended (Auth aside) -- no --yes gate needed here, unlike `mcp create`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from elva_cli.auth import get_access_token, refresh_now
from elva_cli.core.api.http import HttpError, default_error, get_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.core.services.mcp_result import McpListResult, McpServer, McpShowResult
from elva_cli.errors import ApiError, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable

_UNEXPECTED_RESPONSE = "The server returned an unexpected response while reading MCP servers."


def list_mcps(*, base_url: str, workspace: str | None) -> McpListResult:
    token = get_access_token(base_url=base_url)
    reauth = _reauth(base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)

    try:
        body = get_json(f"{base_url}/api/companies/{space.id}/mcps", token=token, reauth=reauth)
    except HttpError as exc:
        raise _list_error(exc) from exc

    return McpListResult(servers=tuple(_to_summary(row) for row in _rows(body)))


def show_mcp(*, base_url: str, workspace: str | None, slug: str) -> McpShowResult:
    token = get_access_token(base_url=base_url)
    reauth = _reauth(base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)

    try:
        body = get_json(
            f"{base_url}/api/companies/{space.id}/mcps/{quote(slug, safe='')}",
            token=token,
            reauth=reauth,
        )
    except HttpError as exc:
        raise _show_error(exc, slug=slug) from exc

    if not isinstance(body, dict) or not isinstance(body.get("mcp"), dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    return McpShowResult(server=_to_detail(body["mcp"]))


def _reauth(base_url: str) -> Callable[[str], str]:
    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    return reauth


def _rows(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("mcps"), list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    return [row for row in body["mcps"] if isinstance(row, dict)]


def _to_summary(row: dict[str, Any]) -> McpServer:
    return McpServer(
        slug=_str(row.get("mcpSlug")),
        name=_str(row.get("mcpName")),
        status=_str(row.get("status")),
        tool_count=_int(row.get("toolCount")),
        collection_id=_opt_str(row.get("collectionId")),
    )


def _to_detail(row: dict[str, Any]) -> McpServer:
    auth_config_raw = row.get("authConfig")
    auth_config: dict[str, Any] = auth_config_raw if isinstance(auth_config_raw, dict) else {}

    collection_raw = row.get("collection")
    collection_name = (
        _opt_str(collection_raw.get("name")) if isinstance(collection_raw, dict) else None
    )

    operations = row.get("selectedOperations")
    has_secret = auth_config.get("hasSecret")

    return McpServer(
        slug=_str(row.get("mcpSlug")),
        name=_str(row.get("mcpName")),
        status=_str(row.get("status")),
        tool_count=_int(row.get("toolCount")),
        collection_id=_opt_str(row.get("collectionId")),
        deployment_id=_opt_str(row.get("deploymentId")),
        collection_name=collection_name,
        auth_type=_opt_str(auth_config.get("type")),
        has_secret=has_secret if isinstance(has_secret, bool) else None,
        selected_operations=tuple(operations) if isinstance(operations, list) else None,
        version=_opt_str(row.get("version")),
        runtime_url=_runtime_url(row),
    )


def _runtime_url(row: dict[str, Any]) -> str | None:
    base = row.get("runtimeUrl")
    if not isinstance(base, str) or not base:
        return None

    settings_raw = row.get("settings")
    settings: dict[str, Any] = settings_raw if isinstance(settings_raw, dict) else {}
    slug = settings.get("customSlug") or row.get("mcpSlug")
    if not isinstance(slug, str) or not slug:
        return None
    return f"{base.rstrip('/')}/mcp/{slug}"


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _list_error(error: HttpError) -> Exception:
    if error.status == 403:
        return UsageError(
            "you don't have access to this workspace",
            hint="Check --workspace.",
        )
    return default_error(error, action="Listing MCP servers")


def _show_error(error: HttpError, *, slug: str) -> Exception:
    if error.status in (400, 404):
        return UsageError(
            f"no MCP server named {slug!r} in this workspace",
            hint="Run 'elva mcp list' to see what exists.",
        )
    if error.status == 403:
        return UsageError(
            "you don't have access to this workspace",
            hint="Check --workspace.",
        )
    return default_error(error, action="Looking up that MCP server")
