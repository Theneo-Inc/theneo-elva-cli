"""import's result types, kept apart from the flows themselves.

elva_cli.ui.renderables.import_spec has to import these at runtime
(singledispatch resolves the annotation when it registers the renderer), so
keeping them here means that import does not drag urllib or yaml in with it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Action(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"


@dataclass(frozen=True)
class ImportSpecResult:
    action: str
    collection: str
    collection_id: str
    workspace: str
    source: str
    spec_format: str
    endpoints: int | None
    spec_title: str | None
    spec_version: str | None
    url: str | None
    metadata_confirmed: bool = True
    """False when the server had not finished processing the spec in the time
    the CLI waited, so the fields above may still describe the previous one."""


@dataclass(frozen=True)
class DryRunResult:
    """What --dry-run would have done. Nothing has been sent."""

    action: str
    collection: str
    source: str
    spec_format: str
    endpoints: int | None
    spec_title: str | None
    spec_version: str | None
    size_bytes: int | None
