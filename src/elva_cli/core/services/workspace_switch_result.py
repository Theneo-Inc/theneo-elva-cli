from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceSwitchResult:
    active_name: str
    active_slug: str
    target_kind: str
    path: str
