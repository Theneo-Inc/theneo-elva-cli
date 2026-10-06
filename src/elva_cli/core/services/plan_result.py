from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlanResult:
    plan: dict[str, Any]


@dataclass(frozen=True)
class AppliedPlan:
    result: dict[str, Any]
