"""whoami's result type, kept apart from the flow itself so importing it for
rendering doesn't drag in urllib (see auth_result.py for the same reasoning)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WhoamiResult:
    email: str
    company_name: str | None
