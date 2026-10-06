"""API contract output models; backend fields are preserved for JSON editing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractList:
    company_id: str
    contracts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ContractResult:
    company_id: str
    action: str
    contract: dict[str, Any]


@dataclass(frozen=True)
class ContractPublished:
    company_id: str
    contract_id: str
    results: tuple[dict[str, Any], ...]
    complete: bool
