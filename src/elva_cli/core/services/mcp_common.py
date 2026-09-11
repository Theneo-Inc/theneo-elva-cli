"""The bits `mcp.py` and `mcp_logs.py` would otherwise each copy: JSON field
coercion and the two workspace/server `UsageError`s their HTTP-status mappings
share. The per-call ``default_error`` action string still lives in each module,
since only the shared branches are here.
"""

from __future__ import annotations

from typing import Any

from elva_cli.errors import UsageError


def as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def as_opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def workspace_forbidden() -> UsageError:
    """The 403 both modules return: the caller can see the workspace exists but
    isn't a member."""
    return UsageError(
        "you don't have access to this workspace",
        hint="Check --workspace.",
    )


def unknown_server(slug: str) -> UsageError:
    """The 400/404 both modules return for a slug that resolves to nothing."""
    return UsageError(
        f"no MCP server named {slug!r} in this workspace",
        hint="Run 'elva mcp list' to see what exists.",
    )
