"""API insight output without loading the review flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InsightChecks:
    checks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class InsightReview:
    source: str
    review: dict[str, Any]
    company_id: str | None = None
    collection_id: str | None = None
