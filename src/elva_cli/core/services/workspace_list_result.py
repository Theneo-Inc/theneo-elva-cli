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
