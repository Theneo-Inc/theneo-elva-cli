"""`elva import spec`: put an OpenAPI document into a collection.

Creating is the default and updating is opt-in: an overwrite is never implicit.
Judging whether the spec is valid stays the server's job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from elva_cli.auth import get_access_token, refresh_now
from elva_cli.core.api.collections import (
    collection_link,
    endpoint_count,
    require_id,
    text,
)
from elva_cli.core.api.http import HttpError, default_error, get_json, send_form
from elva_cli.core.api.targets import Target, resolve_collection, resolve_workspace
from elva_cli.core.services.import_result import Action, DryRunResult, ImportSpecResult
from elva_cli.core.spec.detect import FORMATS, SpecFormat, SpecMeta, detect_format, read_meta
from elva_cli.core.spec.fetch import SpecFetchError, fetch_spec
from elva_cli.core.spec.normalize import to_yaml
from elva_cli.errors import ApiError, ElvaError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_HTTP_TIMEOUT = 120.0
_URL_FETCH_TIMEOUT = 30.0

MAX_BYTES = 10 * 1024 * 1024
MAX_NAME = 100
EXTENSIONS = (".json", ".yaml", ".yml")
_YAML_SUFFIXES = (".yaml", ".yml")
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
    source, raw = _read_source(path=path, stdin=stdin, spec_url=spec_url, base_url=base_url)
    resolved, meta = _inspect(raw, spec_format, source)
    data = _converted(raw, source)
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
            size_bytes=len(data),
        )

    token = get_access_token(base_url=base_url)

    # Idempotent lookups/polls refresh-and-retry once on a 401 (e.g. the token
    # expiring during a large upload); the upload itself is never auto-replayed.
    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    space = resolve_workspace(base_url=base_url, token=token, workspace=workspace, reauth=reauth)

    if update:
        outcome = _update(
            base_url=base_url,
            token=token,
            company_id=space.id,
            collection=target_name,
            source=source,
            data=data,
            reauth=reauth,
        )
    else:
        outcome = _create(
            base_url=base_url,
            token=token,
            company_id=space.id,
            name=target_name,
            source=source,
            data=data,
        )

    doc = outcome.doc
    return ImportSpecResult(
        action=str(action),
        collection=text(doc.get("name")) or outcome.target.name,
        collection_id=outcome.target.id,
        workspace=space.name,
        source=source,
        spec_format=str(resolved),
        endpoints=endpoint_count(doc),
        spec_title=text(doc.get("specTitle")),
        spec_version=text(doc.get("specVersion")),
        url=collection_link(base_url, outcome.target.id),
        metadata_confirmed=outcome.metadata_confirmed,
        published_mcps=outcome.published_mcps,
    )


def _read_source(
    *, path: Path | None, stdin: bytes | None, spec_url: str | None, base_url: str
) -> tuple[str, bytes]:
    """The spec's display name and its bytes, exactly as they arrived.

    A URL is fetched through Elva's proxy -- the same path the web app uses --
    so the bytes come back here to be inspected and named like a local file,
    rather than the server being handed a link.

    Nothing is converted here. `_inspect` has to see the document the user
    actually has, and the size limit has to report a number they can check
    against their own file; `_converted` runs after both.
    """
    given = [given for given in (path, stdin, spec_url) if given is not None]
    if len(given) != 1:
        raise UsageError(
            "give exactly one of FILE, --url or -",
            hint="A path uploads the file, --url has Elva fetch it, - reads stdin.",
        )

    if spec_url is not None:
        if not spec_url.startswith(("http://", "https://")):
            raise UsageError(f"--url must start with http:// or https://, got {spec_url!r}")
        try:
            fetched = fetch_spec(base_url=base_url, url=spec_url, timeout=_URL_FETCH_TIMEOUT)
        except SpecFetchError as exc:
            raise UsageError(str(exc)) from exc
        return spec_url, _checked(fetched, spec_url)

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
    """The source as it stands, measured before anything rewrites it, so the
    size in the error is one the user can check against their own file."""
    if not data.strip():
        raise UsageError(f"{source} is empty")
    if len(data) > MAX_BYTES:
        raise UsageError(f"{source} is {_mb(data)}; the limit is 10 MB")
    return data


def _converted(raw: bytes, source: str) -> bytes:
    """The bytes that actually go up: a JSON spec re-serialised as YAML.

    This runs after `_inspect`, never before. `detect_format` only sniffs the
    first `SNIFF_BYTES`, and YAML expands a minified JSON document by roughly a
    fifth -- enough to push `openapi:` or `_postman_id` past that window for a
    document only a few KB long. Converting first made a valid 6.7 KB spec
    report "could not tell whether ... is an OpenAPI document or a Postman
    collection", and hid a 7.4 KB Postman collection from the refusal that
    exists to stop it being uploaded as a spec.

    The limit is checked again here because the conversion can cross it on its
    own, and the message names both numbers -- the one on disk does not explain
    the failure by itself.
    """
    data = to_yaml(raw)
    if len(data) > MAX_BYTES:
        raise UsageError(
            f"{source} is {_mb(raw)} as it stands, but {_mb(data)} once converted to "
            f"YAML for upload; the limit is 10 MB",
            hint="Elva stores specs as YAML, the same as the web app does.",
        )
    return data


def _mb(data: bytes) -> str:
    return f"{len(data) / 1024 / 1024:.1f} MB"


def _inspect(data: bytes, requested: str | None, source: str) -> tuple[SpecFormat, SpecMeta]:
    """Format and whatever the document says about itself.

    Detection runs even when --format was given: the flag settles what an
    ambiguous document is, but it cannot make a Postman collection into a spec
    the backend can read.
    """
    declared = _declared(requested)
    if declared is SpecFormat.POSTMAN:
        raise _postman_error(source)

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
    yields nothing, which is the outcome this refusal exists to prevent.

    Elva does import Postman collections, just not out of a file: it pulls them
    from Postman's own API, which is what `elva import postman` drives."""
    return UsageError(
        f"{source} is a Postman collection, and Elva cannot import one from a file",
        hint="Run 'elva import postman' to pull it from Postman, or export it as OpenAPI first.",
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
    data: bytes,
) -> _Outcome:
    """POST a new collection. The route awaits its metadata extraction and
    re-reads before answering, so this reply is already correct."""
    url = f"{base_url}/api/companies/{company_id}/collections"
    try:
        body = send_form(
            url,
            token=token,
            method="POST",
            fields={"name": name},
            field=_FIELD,
            filename=_upload_name(source, data),
            data=data,
            content_type=_content_type(data),
            timeout=_HTTP_TIMEOUT,
        )
    except HttpError as exc:
        raise _create_error(exc, name=name) from exc

    doc = _document(body)
    return _Outcome(
        Target(
            id=require_id(doc, message=_UNEXPECTED_RESPONSE), name=text(doc.get("name")) or name
        ),
        doc,
        True,
    )


def _update(
    *,
    base_url: str,
    token: str,
    company_id: str,
    collection: str,
    source: str,
    data: bytes,
    reauth: Callable[[str], str] | None = None,
) -> _Outcome:
    target = resolve_collection(
        base_url=base_url,
        token=token,
        company_id=company_id,
        collection=collection,
        reauth=reauth,
    )
    url = f"{base_url}/api/companies/{company_id}/collections/{target.id}"
    try:
        body = send_form(
            url,
            token=token,
            method="PATCH",
            fields={},
            field=_FIELD,
            filename=_upload_name(source, data),
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
        reauth=reauth,
    )
    return _Outcome(target, doc, confirmed, mcps)


def _upload_name(source: str, data: bytes) -> str:
    """A filename for the multipart part, with an extension matching the bytes.

    The route's fileFilter accepts on media type and only falls back to the
    extension when that type is generic (octet-stream, text/plain, empty).
    _content_type always sends a specific one, so this name never decides
    acceptance -- but a JSON spec goes up as YAML, so `payments.json` would
    name a file that is not JSON for anything downstream reading the extension
    instead of the body.

    A local name is kept otherwise: only the extension is corrected, and only
    when it disagrees with what is actually being sent. `.yml` already agrees.
    """
    json_bytes = data.lstrip()[:1] in (b"{", b"[")
    if source == _STDIN_SOURCE or "://" in source:
        return "spec.json" if json_bytes else "spec.yaml"

    import pathlib

    name = pathlib.PurePosixPath(source)
    wanted = ".json" if json_bytes else ".yaml"
    suffix = name.suffix.lower()
    if suffix == wanted or (not json_bytes and suffix in _YAML_SUFFIXES):
        return source
    return name.with_suffix(wanted).name


def _content_type(data: bytes) -> str:
    """From the content, not the filename, so the route's fileFilter accepts it
    outright instead of falling back to the extension."""
    return "application/json" if data.lstrip()[:1] in (b"{", b"[") else "application/yaml"


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


def _metadata(doc: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    return text(doc.get("specTitle")), text(doc.get("specVersion")), endpoint_count(doc)


def _settled(
    uploaded: dict[str, Any],
    *,
    base_url: str,
    token: str,
    company_id: str,
    collection_id: str,
    reauth: Callable[[str], str] | None = None,
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
            body = get_json(url, token=token, reauth=reauth)
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
        text(row.get("mcpName")) or text(row.get("mcpSlug")) or ""
        for row in rows
        if isinstance(row, dict) and row.get("status") == "published"
    ]
    return tuple(name for name in names if name)
