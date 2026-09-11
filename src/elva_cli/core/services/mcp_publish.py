"""`elva mcp publish <slug>`: transition a draft MCP server to published."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, send_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.core.services.mcp_common import (
    as_int,
    as_opt_str,
    as_str,
    reauth_for,
    unknown_server,
)
from elva_cli.core.services.mcp_create_result import McpCreateResult
from elva_cli.errors import ApiError, UsageError, ValidationError

_UNEXPECTED_RESPONSE = "The server returned an unexpected response while publishing the MCP server."


def publish_mcp(*, base_url: str, workspace: str | None, slug: str) -> McpCreateResult:
    token = get_access_token(base_url=base_url)
    reauth = reauth_for(base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)
    url = f"{base_url}/api/companies/{space.id}/mcps/{quote(slug, safe='')}/publish"
    try:
        response = send_json(url, token=token, method="POST", payload={})
    except HttpError as exc:
        raise _publish_error(exc, slug=slug) from exc
    return _to_result(response)


def _to_result(body: Any) -> McpCreateResult:
    if not isinstance(body, dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    auth_config_raw = body.get("authConfig")
    auth_config: dict[str, Any] = auth_config_raw if isinstance(auth_config_raw, dict) else {}
    has_secret = auth_config.get("hasSecret")
    return McpCreateResult(
        deployment_id=as_str(body.get("deploymentId")),
        slug=as_str(body.get("mcpSlug")),
        name=as_str(body.get("apiName")),
        tool_count=as_int(body.get("toolCount")),
        runtime_url=as_opt_str(body.get("runtimeUrl")),
        auth_type=as_opt_str(auth_config.get("type")) or "none",
        has_secret=has_secret if isinstance(has_secret, bool) else None,
        status=as_opt_str(body.get("status")) or "published",
        action="publish",
        already_published=bool(body.get("alreadyPublished")),
    )


def _publish_error(error: HttpError, *, slug: str) -> Exception:
    if error.status == 400:
        return ValidationError(error.detail or "The server rejected this publish request.")
    if error.status == 404:
        if error.detail and error.detail != "MCP not found":
            return UsageError(error.detail)
        return unknown_server(slug)
    if error.status == 402:
        return UsageError(
            error.detail or "You've reached your MCP server limit.",
            hint="Upgrade your plan, or remove an existing MCP server.",
        )
    if error.status == 403:
        return UsageError(
            "you need editor access to publish MCP servers in this workspace",
            hint="Ask a workspace admin, or check --workspace.",
        )
    return default_error(error, action="Publishing the MCP server")
