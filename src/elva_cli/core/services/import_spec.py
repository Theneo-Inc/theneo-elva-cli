"""`elva import spec`: put an OpenAPI document into a collection.

Creating is the default and updating is opt-in: an overwrite is never implicit.
Judging whether the spec is valid stays the server's job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from elva_cli.auth import get_access_token
from elva_cli.core.api.http import HttpError, default_error, get_json, send_form, send_json
from elva_cli.core.api.targets import Target, resolve_collection, resolve_workspace
from elva_cli.core.services.import_result import Action, DryRunResult, ImportSpecResult
from elva_cli.core.spec.detect import FORMATS, SpecFormat, SpecMeta, detect_format, read_meta
from elva_cli.errors import ApiError, ElvaError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_HTTP_TIMEOUT = 120.0

MAX_BYTES = 10 * 1024 * 1024
MAX_NAME = 100
EXTENSIONS = (".json", ".yaml", ".yml")
_FIELD = "spec"

_STDIN_SOURCE = "<stdin>"
_UNEXPECTED_RESPONSE = "The server returned an unexpected response while importing your spec."

_SETTLE_DELAYS = (0.3, 0.7, 1.5)


class _Outcome(NamedTuple):
    target: Target
    doc: dict[str, Any]
    metadata_confirmed: bool
    published_mcps: tuple[str, ...] = ()


def import_spec(
    *,
    base_url: str,
    workspace: str | None = None,
    path: Path | None = None,
    stdin: bytes | None = None,
    spec_url: str | None = None,
    name: str | None = None,
    prompt_for_name: Callable[[], str] | None = None,
    collection: str | None = None,
    update: bool = False,
    spec_format: str | None = None,
    dry_run: bool = False,
) -> ImportSpecResult | DryRunResult:
    """Create a collection from a spec, or update one with --update."""
    source, data = _read_source(path=path, stdin=stdin, spec_url=spec_url)
    resolved, meta = _inspect(data, spec_format, source)
    action = Action.UPDATED if update else Action.CREATED
    target_name = _target_name(
        update=update, collection=collection, name=name, meta=meta, prompt=prompt_for_name
    )

    if dry_run:
        return DryRunResult(
            action="update" if update else "create",
            collection=target_name,
            source=source,
            spec_format=str(resolved),
            endpoints=meta.endpoints,
            spec_title=meta.title,
            spec_version=meta.version,
            size_bytes=len(data) if data is not None else None,
        )

    token = get_access_token(base_url=base_url)
    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace)

    if update:
        outcome = _update(
            base_url=base_url,
            token=token,
            company_id=space.id,
            collection=target_name,
            source=source,
            data=data,
            spec_url=spec_url,
        )
    else:
        outcome = _create(
            base_url=base_url,
            token=token,
            company_id=space.id,
            name=target_name,
            source=source,
            data=data,
            spec_url=spec_url,
        )

    doc = outcome.doc
    return ImportSpecResult(
        action=str(action),
        collection=_text(doc.get("name")) or outcome.target.name,
        collection_id=outcome.target.id,
        workspace=space.name,
        source=source,
        spec_format=str(resolved),
        endpoints=_endpoint_count(doc),
        spec_title=_text(doc.get("specTitle")),
        spec_version=_text(doc.get("specVersion")),
        url=_collection_link(base_url, outcome.target.id),
        metadata_confirmed=outcome.metadata_confirmed,
        published_mcps=outcome.published_mcps,
    )


def _read_source(
    *, path: Path | None, stdin: bytes | None, spec_url: str | None
) -> tuple[str, bytes | None]:
    """The spec's display name, and its bytes when we hold them.

    A URL is fetched server-side, so there is nothing local to read -- which is
    also why --name cannot be defaulted from it.
    """
    given = [given for given in (path, stdin, spec_url) if given is not None]
    if len(given) != 1:
        raise UsageError(
            "give exactly one of FILE, --url or -",
            hint="A path uploads the file, --url has the server fetch it, - reads stdin.",
        )

    if spec_url is not None:
        if not spec_url.startswith(("http://", "https://")):
            raise UsageError(f"--url must start with http:// or https://, got {spec_url!r}")
        return spec_url, None

    if stdin is not None:
        return _STDIN_SOURCE, _checked(stdin, _STDIN_SOURCE)

    assert path is not None
    if path.is_dir():
        raise UsageError(
            f"{path} is a directory, not a spec file",
            hint="Point at the OpenAPI file itself.",
        )
    if path.suffix.lower() not in EXTENSIONS:
        raise UsageError(
            f"{path.name} must be one of {', '.join(EXTENSIONS)}",
            hint="Elva accepts JSON and YAML specs only.",
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise UsageError(
            f"no such file: {path}",
            hint="Paths are relative to the directory you ran this from.",
        ) from exc
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc
    return path.name, _checked(data, path.name)


def _checked(data: bytes, source: str) -> bytes:
    if not data.strip():
        raise UsageError(f"{source} is empty")
    if len(data) > MAX_BYTES:
        raise UsageError(
            f"{source} is {len(data) / 1024 / 1024:.1f} MB; the limit is 10 MB",
            hint="Split the spec, or import it with --url so the server fetches it.",
        )
    return data


def _inspect(data: bytes | None, requested: str | None, source: str) -> tuple[SpecFormat, SpecMeta]:
    """Format and whatever the document says about itself.

    Detection runs even when --format was given: the flag settles what an
    ambiguous document is, but it cannot make a Postman collection into a spec
    the backend can read.
    """
    declared = _declared(requested)
    if declared is SpecFormat.POSTMAN:
        raise _postman_error(source)
    if data is None:
        return declared or SpecFormat.OPENAPI, SpecMeta()

    detected = detect_format(data)
    if detected is SpecFormat.POSTMAN:
        raise _postman_error(source)

    resolved = declared or detected
    if resolved is None:
        raise UsageError(
            f"could not tell whether {source} is an OpenAPI document or a Postman collection",
            hint=f"Pass --format with one of: {', '.join(FORMATS)}",
        )
    return resolved, read_meta(data)


def _postman_error(source: str) -> UsageError:
    """No --format override here: forcing openapi uploads the collection and
    yields nothing, which is the outcome this refusal exists to prevent."""
    return UsageError(
        f"{source} is a Postman collection, and Elva cannot import one from a file",
        hint="Export it as OpenAPI first, or use the Postman integration in the web app.",
    )


def _declared(requested: str | None) -> SpecFormat | None:
    if requested is None:
        return None
    try:
        return SpecFormat(requested.strip().lower())
    except ValueError as exc:
        raise UsageError(
            f"{requested!r} is not a valid value for --format",
            hint=f"Choose one of: {', '.join(FORMATS)}",
        ) from exc


def _target_name(
    *,
    update: bool,
    collection: str | None,
    name: str | None,
    meta: SpecMeta,
    prompt: Callable[[], str] | None,
) -> str:
    """Which collection this is about: --collection when updating, else --name,
    the spec's own title, or a prompt."""
    if update:
        if name:
            raise UsageError(
                "--name cannot be combined with --update",
                hint="--update replaces the spec of --collection; it never renames it.",
            )
        if not collection:
            raise UsageError(
                "--update needs to know which collection to update",
                hint="Pass --collection, set ELVA_COLLECTION, or put one in elva.json.",
            )
        return collection

    chosen = name or meta.title or (prompt() if prompt is not None else None)
    if not chosen:
        raise UsageError(
            "no name for the new collection",
            hint="Pass --name. It defaults to the spec's info.title when it has one.",
        )
    chosen = chosen.strip()
    if not chosen:
        raise UsageError("the collection name cannot be blank")
    if len(chosen) > MAX_NAME:
        raise UsageError(f"the collection name is {len(chosen)} characters; the limit is 100")
    return chosen


def _create(
    *,
    base_url: str,
    token: str,
    company_id: str,
    name: str,
    source: str,
    data: bytes | None,
    spec_url: str | None,
) -> _Outcome:
    """POST a new collection. The route awaits its metadata extraction and
    re-reads before answering, so this reply is already correct."""
    url = f"{base_url}/api/companies/{company_id}/collections"
    try:
        if data is None:
            assert spec_url is not None
            body = send_json(
                url,
                token=token,
                method="POST",
                payload={"name": name, "specUrl": spec_url},
                timeout=_HTTP_TIMEOUT,
            )
        else:
            body = send_form(
                url,
                token=token,
                method="POST",
                fields={"name": name},
                field=_FIELD,
                filename=_upload_name(source),
                data=data,
                content_type=_content_type(data),
                timeout=_HTTP_TIMEOUT,
            )
    except HttpError as exc:
        raise _create_error(exc, name=name) from exc

    doc = _document(body)
    return _Outcome(Target(id=_require_id(doc), name=_text(doc.get("name")) or name), doc, True)


def _update(
    *,
    base_url: str,
    token: str,
    company_id: str,
    collection: str,
    source: str,
    data: bytes | None,
    spec_url: str | None,
) -> _Outcome:
    target = resolve_collection(
        base_url=base_url, token=token, company_id=company_id, collection=collection
    )
    url = f"{base_url}/api/companies/{company_id}/collections/{target.id}"
    try:
        if data is None:
            assert spec_url is not None
            body = send_json(
                url,
                token=token,
                method="PATCH",
                payload={"specUrl": spec_url},
                timeout=_HTTP_TIMEOUT,
            )
        else:
            body = send_form(
                url,
                token=token,
                method="PATCH",
                fields={},
                field=_FIELD,
                filename=_upload_name(source),
                data=data,
                content_type=_content_type(data),
                timeout=_HTTP_TIMEOUT,
            )
    except HttpError as exc:
        raise _update_error(exc, collection=target.name) from exc

    doc, confirmed, mcps = _settled(
        _document(body),
        base_url=base_url,
        token=token,
        company_id=company_id,
        collection_id=target.id,
    )
    return _Outcome(target, doc, confirmed, mcps)


def _upload_name(source: str) -> str:
    """A filename for the multipart part.

    The route's fileFilter accepts on media type and only falls back to the
    extension when that type is generic (octet-stream, text/plain, empty).
    _content_type always sends a specific one, so this name is never what
    decides acceptance -- stdin just needs to send something.
    """
    return "spec.json" if source == _STDIN_SOURCE else source


def _content_type(data: bytes) -> str:
    """From the content, not the filename, so the route's fileFilter accepts it
    outright instead of falling back to the extension."""
    return "application/json" if data.lstrip()[:1] in (b"{", b"[") else "application/yaml"


def _collection_link(base_url: str, collection_id: str) -> str | None:
    """The web app is the same host with `api` swapped for `app`. A base_url
    that does not follow that shape gets no link rather than a wrong one."""
    import urllib.parse

    parts = urllib.parse.urlsplit(base_url)
    if not parts.netloc.startswith(("api.", "api-")):
        return None
    host = "app" + parts.netloc[3:]
    return f"{parts.scheme}://{host}/collections?selected={collection_id}"


def _create_error(error: HttpError, *, name: str) -> ElvaError:
    if error.status == 409:
        return UsageError(
            f"a collection named {name!r} already exists",
            hint=f"Pass a different --name, or update it with: -c {name} import spec ... --update",
        )
    if error.status in (400, 422):
        return ValidationError(error.detail or "The server rejected this spec as invalid.")
    return default_error(error, action="Creating the collection")


def _update_error(error: HttpError, *, collection: str) -> ElvaError:
    if error.status == 404:
        return UsageError(
            f"no collection named {collection!r}",
            hint="It may have been deleted since the CLI looked it up.",
        )
    if error.status in (400, 422):
        return ValidationError(error.detail or "The server rejected this spec as invalid.")
    return default_error(error, action="Updating the collection")


def _document(body: Any) -> dict[str, Any]:
    """The collection out of a {"collection": {...}} envelope."""
    if not isinstance(body, dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    doc = body.get("collection")
    if not isinstance(doc, dict):
        raise ApiError(_UNEXPECTED_RESPONSE)
    return doc


def _require_id(doc: dict[str, Any]) -> str:
    for key in ("id", "_id"):
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value
    raise ApiError(_UNEXPECTED_RESPONSE)


def _metadata(doc: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    return _text(doc.get("specTitle")), _text(doc.get("specVersion")), _endpoint_count(doc)


def _settled(
    uploaded: dict[str, Any],
    *,
    base_url: str,
    token: str,
    company_id: str,
    collection_id: str,
) -> tuple[dict[str, Any], bool, tuple[str, ...]]:
    """The collection once the server has caught up with the spec just sent,
    whether it was actually observed to catch up, and the MCP servers
    published from it.

    updateCollection fires extractAndUpdateSpecMetadata without awaiting, after
    it has already built the PATCH response, so that response still describes
    the previous spec. Best-effort: the upload already succeeded, so no failure
    here is worth turning that into an error. But the document we settle for
    may still be the previous spec's, and the caller has to say so rather than
    report it as this import's result.
    """
    import time

    url = f"{base_url}/api/companies/{company_id}/collections/{collection_id}"
    before = _metadata(uploaded)
    latest = uploaded
    mcps: tuple[str, ...] = ()

    for delay in _SETTLE_DELAYS:
        time.sleep(delay)
        try:
            body = get_json(url, token=token)
        except (ApiError, HttpError):
            return latest, False, mcps
        doc = _document(body)
        mcps = _published_mcps(body)
        latest = doc
        if _metadata(doc) != before:
            return doc, True, mcps
    return latest, False, mcps


def _published_mcps(body: Any) -> tuple[str, ...]:
    """Names of the MCP servers this collection has published.

    The collection route returns them alongside the document, so this costs no
    extra call. It cannot say which are stale: the list selects deploymentId,
    mcpName, status, toolCount and collectionId, and not the
    collectionSpecHash that isOutdated compares against.
    """
    if not isinstance(body, dict):
        return ()
    rows = body.get("mcps")
    if not isinstance(rows, list):
        return ()
    names = [
        _text(row.get("mcpName")) or _text(row.get("mcpSlug")) or ""
        for row in rows
        if isinstance(row, dict) and row.get("status") == "published"
    ]
    return tuple(name for name in names if name)


def _endpoint_count(doc: dict[str, Any]) -> int | None:
    """The list route sends a count; a single document sends the array."""
    count = doc.get("endpointCount")
    if isinstance(count, int):
        return count
    endpoints = doc.get("endpoints")
    return len(endpoints) if isinstance(endpoints, list) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
