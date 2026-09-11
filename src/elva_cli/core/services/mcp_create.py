"""`elva mcp create`: generate an MCP server from a collection.

Two ways to build the request body -- pure flags for the common cases
(`build_body_from_flags`) or a full JSON document for everything else
(`build_body_from_file`) -- converging on the same plain dict that
`create_mcp`/`dry_run_mcp` send. Which one the caller uses, and the
mutual-exclusivity between them, is a command-layer concern (see
`commands/mcp.py`); this module just builds and validates one body at a
time and does not know where it came from.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, send_json
from elva_cli.core.api.targets import resolve_collection, resolve_workspace
from elva_cli.core.services.mcp_common import as_int, as_opt_str, as_str, reauth_for
from elva_cli.core.services.mcp_create_result import (
    McpCreateResult,
    McpDryRunResult,
    OperationOutcome,
)
from elva_cli.errors import ApiError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_MAX_NAME = 100
_MAX_OPERATIONS = 5000
_MAX_FILTER_ITEMS = 100
_FILTER_FIELDS = (
    "excludePatterns",
    "includeTags",
    "excludeTags",
    "includeMethods",
    "excludeMethods",
)
_UNEXPECTED_RESPONSE = "The server returned an unexpected response while creating the MCP server."

AUTH_TYPES = ("none", "bearer", "api_key")
API_KEY_PLACEMENTS = ("header", "query")


def build_body_from_flags(
    *,
    name: str,
    operations: tuple[str, ...] | None,
    auth_type: str,
    api_key_header: str | None,
    api_key_in: str | None,
    base_url: str | None,
    timeout: int | None,
) -> dict[str, Any]:
    _check_name(name)
    if operations is not None:
        _check_count("--operations", operations, _MAX_OPERATIONS)
    if auth_type not in AUTH_TYPES:
        raise UsageError(
            f"{auth_type!r} is not a valid value for --auth-type",
            hint=f"Choose one of: {', '.join(AUTH_TYPES)} (or use --from for anything else).",
        )
    if auth_type != "api_key" and (api_key_header or api_key_in):
        raise UsageError("--api-key-header/--api-key-in only apply with --auth-type api_key")
    if api_key_in is not None and api_key_in not in API_KEY_PLACEMENTS:
        raise UsageError(
            f"{api_key_in!r} is not a valid value for --api-key-in",
            hint=f"Choose one of: {', '.join(API_KEY_PLACEMENTS)}",
        )

    body: dict[str, Any] = {"mcpName": name}
    if operations is not None:
        body["selectedOperations"] = list(operations)
    if base_url:
        body["baseUrl"] = base_url
    if timeout is not None:
        _check_timeout(timeout)
        body["timeout"] = timeout

    auth_config: dict[str, Any] = {"type": auth_type}
    if api_key_header:
        auth_config["apiKeyHeaderName"] = api_key_header
    if api_key_in:
        auth_config["apiKeyIn"] = api_key_in
    body["authConfig"] = auth_config
    return body


def build_body_from_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise UsageError(
            f"no such file: {path}",
            hint="Paths are relative to the directory you ran this from.",
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise UsageError(f"{path.name} must contain a JSON object")

    name = body.get("mcpName")
    if not isinstance(name, str) or not name.strip():
        raise UsageError(f"{path.name} must set mcpName")
    _check_name(name)

    operations = body.get("selectedOperations")
    if isinstance(operations, list):
        _check_count("selectedOperations", operations, _MAX_OPERATIONS)
    for field in _FILTER_FIELDS:
        items = body.get(field)
        if isinstance(items, list):
            _check_count(field, items, _MAX_FILTER_ITEMS)
    timeout = body.get("timeout")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        _check_timeout(timeout)

    _reject_inline_secrets(body, source=path.name)
    return body


def merge_secret(body: dict[str, Any], secret: str) -> dict[str, Any]:
    """Attach a --client-secret value to whichever field the body's
    authConfig.type actually has a slot for."""
    auth_config = body.get("authConfig")
    if not isinstance(auth_config, dict) or auth_config.get("type") not in (
        "oauth",
        "openid_connect",
    ):
        raise UsageError(
            "--client-secret only applies when authConfig.type is oauth or openid_connect",
            hint="Set authConfig.type in --from, or omit --client-secret.",
        )
    auth_type = auth_config["type"]

    if auth_type == "oauth":
        oauth = auth_config.get("oauth")
        if not isinstance(oauth, dict):
            raise UsageError("--from's authConfig.oauth is required to attach --client-secret")
        auth_config = {**auth_config, "oauth": {**oauth, "clientSecret": secret}}
    else:
        auth_config = {**auth_config, "oidcClientSecret": secret}
    return {**body, "authConfig": auth_config}


def create_mcp(
    *, base_url: str, workspace: str | None, collection: str | None, body: dict[str, Any]
) -> McpCreateResult:
    token, space, coll = _resolve(base_url=base_url, workspace=workspace, collection=collection)
    url = f"{base_url}/api/companies/{space.id}/collections/{coll.id}/mcps"
    payload = {key: value for key, value in body.items() if key != "dryRun"}
    try:
        response = send_json(url, token=token, method="POST", payload=payload)
    except HttpError as exc:
        raise _create_error(exc) from exc
    return _to_result(response)


def dry_run_mcp(
    *, base_url: str, workspace: str | None, collection: str | None, body: dict[str, Any]
) -> McpDryRunResult:
    token, space, coll = _resolve(base_url=base_url, workspace=workspace, collection=collection)
    url = f"{base_url}/api/companies/{space.id}/collections/{coll.id}/mcps"
    try:
        response = send_json(url, token=token, method="POST", payload={**body, "dryRun": True})
    except HttpError as exc:
        raise _create_error(exc) from exc
    return _to_dry_run_result(response)


def _resolve(
    *, base_url: str, workspace: str | None, collection: str | None
) -> tuple[str, Any, Any]:
    if collection is None:
        raise UsageError(
            "no collection given",
            hint="Pass --collection, set ELVA_COLLECTION, or put one in elva.json.",
        )
    token = get_access_token(base_url=base_url)
    reauth = reauth_for(base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)
    coll = resolve_collection(
        base_url=base_url, token=token, company_id=space.id, collection=collection, reauth=reauth
    )
    return token, space, coll


def _check_name(name: str) -> None:
    if not name.strip():
        raise UsageError("mcpName cannot be blank")
    if len(name) > _MAX_NAME:
        raise UsageError(f"the MCP name is {len(name)} characters; the limit is {_MAX_NAME}")


def _check_count(flag: str, items: Sequence[str], limit: int) -> None:
    if len(items) > limit:
        raise UsageError(f"{len(items)} were given for {flag}; the limit is {limit}")


def _check_timeout(timeout: int | float) -> None:
    if not (1000 <= timeout <= 300000):
        raise UsageError(f"timeout must be between 1000 and 300000 ms, got {timeout}")


def _reject_inline_secrets(body: dict[str, Any], *, source: str) -> None:
    auth_config = body.get("authConfig")
    if not isinstance(auth_config, dict):
        return
    if auth_config.get("oidcClientSecret"):
        raise UsageError(
            f"{source} embeds authConfig.oidcClientSecret",
            hint="Remove it from the file and pass --client-secret instead.",
        )
    oauth = auth_config.get("oauth")
    if isinstance(oauth, dict) and oauth.get("clientSecret"):
        raise UsageError(
            f"{source} embeds authConfig.oauth.clientSecret",
            hint="Remove it from the file and pass --client-secret instead.",
        )


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
    )


def _to_dry_run_result(body: Any) -> McpDryRunResult:
    if not isinstance(body, dict) or not isinstance(body.get("operations"), list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    operations = tuple(_to_outcome(row) for row in body["operations"] if isinstance(row, dict))
    return McpDryRunResult(tool_count=as_int(body.get("toolCount")), operations=operations)


def _to_outcome(row: dict[str, Any]) -> OperationOutcome:
    return OperationOutcome(
        operation_key=as_str(row.get("operationKey")),
        method=as_str(row.get("method")),
        path=as_str(row.get("path")),
        included=bool(row.get("included")),
        reason=as_opt_str(row.get("reason")),
    )


def _create_error(error: HttpError) -> Exception:
    if error.status == 400:
        return ValidationError(error.detail or "The server rejected this MCP configuration.")
    if error.status == 402:
        return UsageError(
            error.detail or "You've reached your MCP server limit.",
            hint="Upgrade your plan, or remove an existing MCP server.",
        )
    if error.status == 403:
        return UsageError(
            "you need editor access to create MCP servers in this workspace",
            hint="Ask a workspace admin, or check --workspace.",
        )
    if error.status == 409:
        return UsageError(
            error.detail or "An MCP server already exists for this collection or name."
        )
    return default_error(error, action="Creating the MCP server")
