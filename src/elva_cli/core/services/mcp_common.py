"""The bits `mcp.py` and `mcp_logs.py` would otherwise each copy: JSON field
coercion and the two workspace/server `UsageError`s their HTTP-status mappings
share. The per-call ``default_error`` action string still lives in each module,
since only the shared branches are here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from elva_cli.errors import ForbiddenError, UsageError

if TYPE_CHECKING:
    from collections.abc import Callable


def reauth_for(base_url: str) -> Callable[[str], str]:
    """The `reauth` callback every service passes to `get_json`/`send_json`:
    force a refresh of a token that looked valid but got a 401 anyway."""
    from elva_cli.auth import refresh_now

    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    return reauth


def as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def as_opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def workspace_forbidden() -> ForbiddenError:
    """The 403 both modules return: the caller can see the workspace exists but
    isn't a member."""
    return ForbiddenError(
        "you don't have access to this workspace",
        hint="Check --workspace.",
    )


def runtime_url(row: dict[str, Any]) -> str | None:
    """Prefer the API's canonical endpoint; support older host-only responses."""
    if row.get("status") == "draft":
        return None
    if "mcpUrl" in row:
        return as_opt_str(row.get("mcpUrl"))
    base = as_opt_str(row.get("runtimeUrl"))
    settings = row.get("settings")
    custom_slug = as_opt_str(settings.get("customSlug")) if isinstance(settings, dict) else None
    deployment_id = as_opt_str(row.get("deploymentId"))
    target = custom_slug or deployment_id
    if not base or not target:
        return None
    return f"{base.rstrip('/')}/mcp/{target}"


def unknown_server(slug: str) -> UsageError:
    """The 400/404 both modules return for a slug that resolves to nothing."""
    return UsageError(
        f"no MCP server named {slug!r} in this workspace",
        hint="Run 'elva mcp list' to see what exists.",
    )
