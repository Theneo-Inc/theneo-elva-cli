"""`import postman`'s result types, kept apart from the flow itself.

elva_cli.ui.renderables.postman has to import these at runtime (singledispatch
resolves the annotation when it registers the renderer), so keeping them here
means that import does not drag urllib in with it.

Nothing here holds the Postman API key. A result object is what `--json` prints
and what a crash report could conceivably reach, so the credential stops at the
service boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PostmanCollection:
    """One collection as Postman describes it. `uid` is what the import route
    is keyed by; `id` is the bare form, kept because scripts see both."""

    uid: str
    name: str
    id: str | None = None
    owner: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class PostmanCollectionList:
    """What the API key can see. Nothing has been imported."""

    workspace: str
    collections: tuple[PostmanCollection, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PostmanImportResult:
    collection: str
    """The Elva collection the Postman one landed in."""

    collection_id: str
    workspace: str

    postman_collection: str | None
    """The name the collection has in Postman.

    None when the import was addressed by id: nothing was listed, so the only
    Postman-side identity the CLI ever held is the id itself.
    """

    postman_uid: str
    endpoints: int | None
    url: str | None
