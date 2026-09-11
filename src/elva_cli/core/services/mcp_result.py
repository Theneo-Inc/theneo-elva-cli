"""mcp's result types, kept apart from the flow itself so importing them for
rendering doesn't drag in urllib (see whoami_result.py/import_result.py for
the same reasoning).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpServer:
    slug: str
    name: str
    status: str  # "draft" | "published"
    tool_count: int
    collection_id: str | None

    # show only
    deployment_id: str | None = None
    collection_name: str | None = None
    auth_type: str | None = None
    has_secret: bool | None = None
    selected_operations: tuple[str, ...] | None = None
    version: str | None = None
    runtime_url: str | None = None


@dataclass(frozen=True)
class McpListResult:
    servers: tuple[McpServer, ...]


@dataclass(frozen=True)
class McpShowResult:
    server: McpServer
