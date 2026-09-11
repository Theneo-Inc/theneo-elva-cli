"""mcp logs's result types, kept apart from the flow itself so importing them
for rendering doesn't drag in urllib (see mcp_result.py for the same
reasoning).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LogEntry:
    id: str
    time: str
    tool: str
    status: int
    duration_ms: int
    agent: str | None
    agent_id: str | None
    client_id: str | None
    user_id: str | None
    error: str | None
    tokens: int | None


@dataclass(frozen=True)
class McpLogsResult:
    entries: tuple[LogEntry, ...]
    total: int
    page: int
    limit: int
