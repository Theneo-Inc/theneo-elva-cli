"""mcp create's result types, kept apart from the flow itself so importing
them for rendering doesn't drag in urllib (see mcp_result.py for the same
reasoning).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpCreateResult:
    deployment_id: str
    slug: str
    name: str
    tool_count: int
    runtime_url: str | None
    auth_type: str
    has_secret: bool | None


@dataclass(frozen=True)
class OperationOutcome:
    operation_key: str
    method: str
    path: str
    included: bool
    reason: str | None = None


@dataclass(frozen=True)
class McpDryRunResult:
    tool_count: int
    operations: tuple[OperationOutcome, ...]
