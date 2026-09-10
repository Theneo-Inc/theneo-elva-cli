"""Reading Elva's collection documents, and linking to them in the web app.

Every route that puts a spec into a collection answers with the same document
shape, so the handful of fields the CLI actually reads out of it live here
rather than once per import flow.
"""

from __future__ import annotations

from typing import Any

from elva_cli.errors import ApiError
from elva_cli.safe_text import printable

UNEXPECTED_RESPONSE = "The server returned an unexpected response while importing."


def find_id(doc: dict[str, Any]) -> str | None:
    """The collection's id, or None -- never raises.

    A route that has not gone through the same response-shaping as the rest of
    the API can leak a raw Mongo document, where an id is extended JSON
    (`{"_id": {"$oid": "..."}}`) rather than the plain string every other route
    sends. Both are accepted, because the caller cannot tell which kind of
    route it is talking to just by looking at the collection name.
    """
    for key in ("id", "_id"):
        value = doc.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            oid = value.get("$oid")
            if isinstance(oid, str) and oid:
                return oid
    return None


def require_id(doc: dict[str, Any], *, message: str = UNEXPECTED_RESPONSE) -> str:
    """The collection's id. Without one there is nothing to report or link to.

    `message` lets each flow say what it was in the middle of, because "while
    importing your spec" and "while importing from Postman" send the reader to
    different places.
    """
    found = find_id(doc)
    if found is None:
        raise ApiError(message)
    return found


def endpoint_count(doc: dict[str, Any]) -> int | None:
    """The list route sends a count; a single document sends the array."""
    count = doc.get("endpointCount")
    if isinstance(count, int):
        return count
    endpoints = doc.get("endpoints")
    return len(endpoints) if isinstance(endpoints, list) else None


def collection_link(base_url: str, collection_id: str) -> str | None:
    """The web app is the same host with `api` swapped for `app`. A base_url
    that does not follow that shape gets no link rather than a wrong one."""
    import urllib.parse

    parts = urllib.parse.urlsplit(base_url)
    if not parts.netloc.startswith(("api.", "api-")):
        return None
    host = "app" + parts.netloc[3:]
    return f"{parts.scheme}://{host}/collections?selected={collection_id}"


def text(value: Any) -> str | None:
    """A string field, or None if there is nothing in it.

    Control characters are taken out here rather than at each place the value
    is displayed: these are names somebody else chose, and every caller ends up
    putting them on a terminal.
    """
    if not isinstance(value, str):
        return None
    cleaned = printable(value).strip()
    return cleaned or None
