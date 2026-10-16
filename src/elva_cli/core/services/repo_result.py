"""Repository results, independent of HTTP and authentication imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Repository:
    id: str
    owner: str
    name: str
    company_id: str
    branch: str
    private: bool
    ai_enabled: bool
    base_url: str | None
    needs_base_url: bool
    last_scan_at: str | None = None
    last_scan_job_id: str | None = None


@dataclass(frozen=True)
class RepoListResult:
    company_id: str
    repositories: tuple[Repository, ...]


@dataclass(frozen=True)
class RepoJob:
    id: str
    repo_id: str
    status: str
    progress: float
    current_step: str | None
    stats: dict[str, Any]
    errors: tuple[dict[str, Any], ...]
    collections: dict[str, Any] | None
    quality: Any
    commit_sha: str | None
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class RepoProblem:
    code: str
    message: str
    hint: str | None
    exit_code: int


@dataclass(frozen=True)
class RepoScanResult:
    repository: Repository
    scan_job_id: str | None
    already_running: bool = False
    job: RepoJob | None = None
    error: RepoProblem | None = None
