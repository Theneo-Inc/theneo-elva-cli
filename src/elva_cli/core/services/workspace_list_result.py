"""workspace list's result types, kept apart from the flow itself so importing
them for rendering doesn't drag in urllib (see whoami_result.py for the same
reasoning)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkspaceItem:
    name: str
    slug: str
    role: str
    active: bool
    active_source: str | None


@dataclass(frozen=True)
class WorkspaceListResult:
    workspaces: list[WorkspaceItem] = field(default_factory=list)
