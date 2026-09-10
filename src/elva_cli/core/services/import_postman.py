"""`elva import postman`: pull a collection out of Postman into Elva.

Two backend routes do the work, both keyed by company and both authenticated
with Elva's own JWT:

    POST /api/companies/:id/postman/collections   {apiKey}  -- what is there
    POST /api/companies/:id/postman/import                  -- bring one in

The Postman API key is somebody else's credential passing through. It never
reaches argv (the command layer reads it from the environment, a hidden prompt
or stdin), it is never stored, it is never logged, and it is stripped back out
of any server message before that message is shown -- see `_redacted`. It is
also not sent over a cleartext connection at all; see `_refuse_plaintext`.

A rejected key exits 3 rather than 4 or 1: it is a credential problem, and the
fix is a new key, not a different invocation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token
from elva_cli.core.api.collections import (
    collection_link,
    endpoint_count,
    find_id,
    require_id,
    text,
)
from elva_cli.core.api.http import HttpError, default_error, get_json, send_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.core.services.postman_result import (
    PostmanCollection,
    PostmanCollectionList,
    PostmanImportResult,
)
from elva_cli.errors import (
    ApiError,
    AuthError,
    ElvaError,
    ForbiddenError,
    UsageError,
    ValidationError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from elva_cli.core.api.targets import Target

_HTTP_TIMEOUT = 120.0

_KEY_FIELD = "apiKey"
_COLLECTION_FIELD = "collectionIds"

MAX_KEY = 512

_UNEXPECTED_RESPONSE = "The server returned an unexpected response while importing from Postman."
_KEY_HINT = (
    "Set ELVA_POSTMAN_API_KEY to a current key from https://postman.co/settings/me/api-keys, "
    "or leave it unset to be asked for one."
)
_REDACTED = "***"

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})

_POSTMAN_ID = re.compile(
    r"^(?:[0-9]+-)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def list_postman_collections(
    *, base_url: str, workspace: str | None = None, api_key: str
) -> PostmanCollectionList:
    """Every collection the API key can see. Imports nothing."""
    key = _checked_key(api_key)
    _refuse_plaintext(base_url)
    token, space = _elva_context(base_url=base_url, workspace=workspace)
    found = _fetch(base_url=base_url, token=token, company_id=space.id, key=key)
    return PostmanCollectionList(workspace=space.name, collections=found)


def import_postman(
    *,
    base_url: str,
    workspace: str | None = None,
    api_key: str,
    collection: str | None = None,
    choose: Callable[[Sequence[PostmanCollection]], PostmanCollection] | None = None,
) -> PostmanImportResult:
    """Import one Postman collection, named or picked.

    `choose` is how a terminal asks. Without one -- in CI, under --json, with
    stdout redirected -- an unnamed collection is a usage error listing what
    was available, because guessing which of somebody's collections to import
    is not a decision this can make for them.
    """
    key = _checked_key(api_key)
    _refuse_plaintext(base_url)
    token, space = _elva_context(base_url=base_url, workspace=workspace)

    chosen = _direct(collection)
    listed = chosen is None
    postman_name: str | None = None
    if chosen is None:
        found = _fetch(base_url=base_url, token=token, company_id=space.id, key=key)
        chosen = _choose(found, wanted=collection, choose=choose)
        postman_name = chosen.name

    body = _import(
        base_url=base_url,
        token=token,
        company_id=space.id,
        key=key,
        chosen=chosen,
        key_proven=listed,
    )

    read = _document(body)
    found_id = find_id(read) if read is not None else None
    if read is not None and found_id is not None:
        doc, collection_id = read, found_id
    else:
        doc = _look_up(base_url=base_url, token=token, company_id=space.id, name=postman_name)
        collection_id = require_id(doc, message=_UNEXPECTED_RESPONSE)
    return PostmanImportResult(
        collection=text(doc.get("name")) or chosen.name,
        collection_id=collection_id,
        workspace=space.name,
        postman_collection=postman_name,
        postman_uid=chosen.uid,
        endpoints=endpoint_count(doc),
        url=collection_link(base_url, collection_id),
    )


def _direct(collection: str | None) -> PostmanCollection | None:
    """A collection given as a Postman id, taken at its word.

    Listing first would spend a round trip confirming what the id already says,
    and would make the import depend on that collection coming back in the list
    route's answer -- which is not something this can promise for an account
    with a lot of them, or a route that pages. `targets.py` accepts an Elva id
    the same way and for the same reason.

    A name still has to be resolved, because a name is not what the import
    route takes.
    """
    if collection is None:
        return None
    wanted = collection.strip()
    if not _POSTMAN_ID.match(wanted):
        return None
    return PostmanCollection(uid=wanted, name=wanted)


def _elva_context(*, base_url: str, workspace: str | None) -> tuple[str, Target]:
    """Elva's own credentials first, so being signed out fails before a Postman
    key is ever put on the wire."""
    token = get_access_token(base_url=base_url)
    return token, resolve_workspace(base_url=base_url, token=token, workspace=workspace)


def _checked_key(api_key: str) -> str:
    """The key, trimmed, or a usage error that does not quote it back.

    Whitespace inside a key means a mangled paste rather than a key, and
    catching that here beats a 401 the user has to interpret.
    """
    key = api_key.strip()
    if not key:
        raise UsageError("no Postman API key was given", hint=_KEY_HINT)
    if len(key) > MAX_KEY:
        raise UsageError(
            f"that Postman API key is {len(key)} characters; the limit is {MAX_KEY}",
            hint=_KEY_HINT,
        )
    if any(char.isspace() or ord(char) < 0x20 for char in key):
        raise UsageError(
            "that Postman API key has whitespace in it, so it is not a key",
            hint="Check the value was pasted whole and on one line.",
        )
    return key


def _refuse_plaintext(base_url: str) -> None:
    """A third-party credential does not go out in the clear.

    Loopback is exempt: a backend on this machine is not a network hop, and
    refusing there would only break local development.
    """
    import urllib.parse

    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme == "https":
        return
    host = (parts.hostname or "").lower()
    if host in _LOOPBACK or host.endswith(".localhost"):
        return
    raise UsageError(
        f"refusing to send a Postman API key to {host or base_url!r} over {parts.scheme or 'no'}://",
        hint="A Postman key only travels over https. Check --base-url.",
    )


def _fetch(
    *, base_url: str, token: str, company_id: str, key: str
) -> tuple[PostmanCollection, ...]:
    url = f"{base_url}/api/companies/{company_id}/postman/collections"
    try:
        body = send_json(
            url,
            token=token,
            method="POST",
            payload={_KEY_FIELD: key},
            timeout=_HTTP_TIMEOUT,
        )
    except HttpError as exc:
        raise _postman_error(exc, key=key, action="Listing your Postman collections") from exc
    return tuple(_collection(row) for row in _rows(body))


def _rows(body: Any) -> list[dict[str, Any]]:
    """The collection array, whether or not it arrives in an envelope."""
    rows: Any = body
    if isinstance(body, dict):
        for envelope in ("collections", "data", "items"):
            if isinstance(body.get(envelope), list):
                rows = body[envelope]
                break
    if not isinstance(rows, list):
        raise ApiError(_UNEXPECTED_RESPONSE)
    return [row for row in rows if isinstance(row, dict)]


def _collection(row: dict[str, Any]) -> PostmanCollection:
    """One row. `uid` is Postman's own addressable id; a backend that only
    passes `id` through still gives something to key the import by."""
    uid = text(row.get("uid")) or text(row.get("id")) or text(row.get("_id"))
    if uid is None:
        raise ApiError(_UNEXPECTED_RESPONSE)
    owner = row.get("owner")
    return PostmanCollection(
        uid=uid,
        name=text(row.get("name")) or uid,
        id=text(row.get("id")),
        owner=text(owner) if isinstance(owner, str) else None,
        updated_at=text(row.get("updatedAt")) or text(row.get("updated_at")),
    )


def _choose(
    found: Sequence[PostmanCollection],
    *,
    wanted: str | None,
    choose: Callable[[Sequence[PostmanCollection]], PostmanCollection] | None,
) -> PostmanCollection:
    if not found:
        raise UsageError(
            "that Postman API key cannot see any collections",
            hint="Check the key's workspace access at https://postman.co/settings/me/api-keys.",
        )

    if wanted is None:
        if choose is None:
            raise UsageError(
                "no Postman collection was named",
                hint=f"Name one of: {_names(found)}",
            )
        picked = choose(found)
        if picked not in found:
            msg = "the picker returned a collection that was not offered"
            raise ElvaError(msg)
        return picked

    return _match(found, wanted)


def _match(found: Sequence[PostmanCollection], wanted: str) -> PostmanCollection:
    """By id first, then by exact name, case-insensitively.

    An id is unambiguous, so it is tried before a name that might not be. Two
    collections really can share a name -- Postman does not stop it -- and
    picking one of them silently would import the wrong API.
    """
    needle = wanted.strip()
    for target in found:
        if needle in (target.uid, target.id):
            return target

    lowered = needle.lower()
    matches = [target for target in found if target.name.lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UsageError(
            f"no Postman collection named {wanted!r}",
            hint=f"Available: {_names(found)}",
        )
    raise UsageError(
        f"{len(matches)} Postman collections are named {wanted!r}",
        hint=f"Pass the id instead: {', '.join(target.uid for target in matches)}",
    )


def _names(found: Sequence[PostmanCollection]) -> str:
    shown = sorted(target.name for target in found)[:10]
    more = len(found) - len(shown)
    listed = ", ".join(repr(name) for name in shown)
    return f"{listed} (and {more} more)" if more > 0 else listed


def _import(
    *,
    base_url: str,
    token: str,
    company_id: str,
    key: str,
    chosen: PostmanCollection,
    key_proven: bool,
) -> Any:
    """The raw reply. Reading the collection out of it is the caller's job,
    because the caller is the one that can fall back to a lookup."""
    url = f"{base_url}/api/companies/{company_id}/postman/import"
    try:
        body = send_json(
            url,
            token=token,
            method="POST",
            payload={_KEY_FIELD: key, _COLLECTION_FIELD: [chosen.uid]},
            timeout=_HTTP_TIMEOUT,
        )
    except HttpError as exc:
        raise _import_error(exc, key=key, chosen=chosen, key_proven=key_proven) from exc
    return body


def _document(body: Any) -> dict[str, Any] | None:
    """The collection that was created, if the reply carries it.

    The route takes an array, so it may well answer with one. Only ever one id
    goes up, so the first row back is the collection this import made; the
    singular shapes are accepted too because the sibling create route uses
    them.

    None rather than an error: the caller has a way to find out regardless, and
    an unrecognised reply to a request that succeeded is not a failed import.
    """
    if isinstance(body, list):
        return _first(body)
    if not isinstance(body, dict):
        return None

    doc = body.get("collection")
    if isinstance(doc, dict):
        return doc
    for envelope in ("collections", "imported", "results", "data"):
        rows = body.get(envelope)
        if isinstance(rows, list):
            return _first(rows)
        if isinstance(rows, dict):
            return rows
    if any(key in body for key in ("id", "_id")):
        return body
    return None


def _first(rows: list[Any]) -> dict[str, Any] | None:
    return next((row for row in rows if isinstance(row, dict)), None)


def _look_up(*, base_url: str, token: str, company_id: str, name: str | None) -> dict[str, Any]:
    """The collection the import just made, found by name instead of read out
    of the reply.

    Reached only when the import returned something this cannot read. Elva
    names the new collection after the Postman one, so the name is enough --
    which is also why an import addressed straight by id cannot do this: it
    never learned the name, and guessing which collection is new would be
    worse than saying so.
    """
    if name is None:
        raise ApiError(
            "The import was accepted, but Elva's reply could not be read, so this "
            "cannot say which collection it made.",
            hint="Check your collections in Elva before importing again.",
        )

    try:
        payload = get_json(f"{base_url}/api/companies/{company_id}/collections", token=token)
    except (HttpError, ApiError) as exc:
        raise _landed_but_unreadable(name) from exc

    rows = payload.get("collections") if isinstance(payload, dict) else None
    wanted = name.strip().lower()
    matches = [
        row
        for row in (rows or [])
        if isinstance(row, dict) and str(row.get("name", "")).strip().lower() == wanted
    ]
    if len(matches) != 1:
        raise _landed_but_unreadable(name)
    return matches[0]


def _landed_but_unreadable(name: str) -> ApiError:
    """Still an error -- there is no id to report -- but one that says the
    import happened, so nobody retries it into a duplicate."""
    return ApiError(
        "The import was accepted, but Elva's reply could not be read and no single "
        f"collection named {name!r} was found afterwards.",
        hint="Check your collections in Elva before importing again.",
    )


def _import_error(
    error: HttpError, *, key: str, chosen: PostmanCollection, key_proven: bool
) -> ElvaError:
    if error.status == 403:
        return _forbidden(key_proven=key_proven)
    if error.status == 409:
        return UsageError(
            f"a collection named {chosen.name!r} already exists in Elva",
            hint="Rename the existing one, or rename the collection in Postman.",
        )
    conflict = _named_conflict(error.detail, name=chosen.name)
    if conflict is not None:
        return UsageError(
            conflict, hint="Rename the existing one, or rename the collection in Postman."
        )
    if error.status == 404 and _redacted(error.detail, key):
        return UsageError(
            f"Postman no longer has a collection {chosen.uid!r}",
            hint="It may have been deleted, or the id may not be one Postman knows.",
        )
    return _postman_error(error, key=key, action=f"Importing {chosen.name!r}")


def _forbidden(*, key_proven: bool) -> ElvaError:
    """A 403 from the import route, which is not the same thing as a bad key.

    Listing needs any access to the workspace; importing needs the editor role.
    That difference is the only thing the import route checks that the list
    route does not -- so when the same key listed collections a moment ago, a
    403 here is about what this account may do in Elva, and telling the user to
    rotate a working Postman key would send them nowhere.

    Without that listing (an import addressed straight by id) both are still
    live possibilities, so the hint names them both.
    """
    if key_proven:
        return ForbiddenError(
            "You do not have permission to import into this workspace.",
            hint=(
                "The Postman key worked, so this is the Elva side: importing needs "
                "the editor role. Ask a workspace admin to grant it."
            ),
        )
    return ForbiddenError(
        "Elva refused the import.",
        hint=(f"Importing needs the editor role in this workspace. {_KEY_HINT}"),
    )


def _postman_error(error: HttpError, *, key: str, action: str) -> ElvaError:
    """A rejected request from either Postman route.

    401 and 403 are read as the Postman key rather than the Elva session: both
    routes sit behind requireCompanyAccess, and the workspace lookup that ran
    first already put the JWT past it. The hint names the other possibility
    anyway, because a workspace given as an id skips that lookup.
    """
    detail = _redacted(error.detail, key)
    if error.status in (401, 403):
        return AuthError(
            detail or "Elva could not use that Postman API key.",
            hint=f"{_KEY_HINT} If you are also signed out of Elva, run 'elva auth login'.",
        )
    if error.status in (400, 422):
        if _about_the_key(detail):
            return AuthError(detail or "Postman rejected that API key.", hint=_KEY_HINT)
        return ValidationError(detail or "Postman rejected this request.")
    return default_error(error, action=action)


_NAMES_THE_KEY = ("api key", "apikey", "api_key", "postman key", "postman token")
_REJECTS_IT = ("invalid", "expired", "revoked", "incorrect", "wrong", "rejected", "not valid")
_UNAMBIGUOUS = ("unauthor", "forbidden")


def _named_conflict(detail: str | None, *, name: str) -> str | None:
    """`detail`, if it both claims something already exists and names this
    particular collection -- otherwise None.

    Matching "already exists" alone is not enough: nothing here can tell that
    phrase apart from an unrelated failure that happens to use the same words,
    so a false match would put the wrong sentence in front of the user with
    real confidence behind it. Requiring the collection's own name lowers that
    risk without needing to know the route's exact wording.
    """
    if detail is None or "already exists" not in detail.lower():
        return None
    if name.lower() not in detail.lower():
        return None
    return detail


def _about_the_key(detail: str | None) -> bool:
    """Whether a 400 is really a credential failure wearing the wrong status.

    Backends routinely flatten an upstream 401 into a 400, and the difference
    matters: exit 3 says "get a new key", exit 4 says "the CLI worked and your
    input is wrong".

    Naming the field is not enough to decide that. "apiKey is required" and
    "apiKey must be a string" are what a backend says when *this* code sends
    the wrong body -- and the field names above are an assumption about a route
    nothing here has run against. Reading those as a bad key would have the
    user rotating a Postman key that was fine, forever. So a 400 has to both
    name the key and say it was refused.
    """
    if not detail:
        return False
    lowered = detail.lower()
    if any(phrase in lowered for phrase in _UNAMBIGUOUS):
        return True
    return any(name in lowered for name in _NAMES_THE_KEY) and any(
        verdict in lowered for verdict in _REJECTS_IT
    )


def _redacted(detail: str | None, key: str) -> str | None:
    """The server's explanation, with the key taken back out of it.

    Nothing should echo a credential, but this message is about to be printed
    and possibly pasted into an issue, so it does not depend on that.
    """
    if not detail:
        return None
    return detail.replace(key, _REDACTED)
