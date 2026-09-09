"""Recognise a spec and read the few facts the CLI needs out of it.

Judging whether the document is *valid* is still the server's job. A spec this
module cannot parse is not rejected here -- it just has no title to offer, and
the user is asked for a name instead.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass


class SpecFormat(enum.StrEnum):
    OPENAPI = "openapi"
    POSTMAN = "postman"


FORMATS = tuple(fmt.value for fmt in SpecFormat)

SNIFF_BYTES = 8192

_POSTMAN = re.compile(rb"_postman_id|schema\.getpostman\.com")
_OPENAPI = re.compile(rb"""^[\s{]*["']?(openapi|swagger)["']?\s*:""", re.MULTILINE)

_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


@dataclass(frozen=True)
class SpecMeta:
    """Every field is optional: an unparseable document still imports, it just
    cannot describe itself first."""

    title: str | None = None
    version: str | None = None
    endpoints: int | None = None


def detect_format(data: bytes) -> SpecFormat | None:
    """The format `data` looks like, or None if neither marker shows up.

    Postman is checked first: a collection can legitimately mention "swagger"
    in a request name, but an OpenAPI document never carries _postman_id.
    """
    head = data[:SNIFF_BYTES]
    if _POSTMAN.search(head):
        return SpecFormat.POSTMAN
    if _OPENAPI.search(head):
        return SpecFormat.OPENAPI
    return None


def read_meta(data: bytes) -> SpecMeta:
    """Title, version and operation count, best effort.

    YAML is a superset of JSON, so one parser covers both. Any failure returns
    an empty SpecMeta rather than raising: a document the CLI cannot read may
    still be one the server accepts.
    """
    import yaml

    try:
        document = yaml.safe_load(data)
    except (yaml.YAMLError, UnicodeDecodeError, ValueError):
        return SpecMeta()
    if not isinstance(document, dict):
        return SpecMeta()

    info = document.get("info")
    info = info if isinstance(info, dict) else {}

    return SpecMeta(
        title=_text(info.get("title")),
        version=_text(info.get("version")),
        endpoints=_count_operations(document.get("paths")),
    )


def _count_operations(paths: object) -> int | None:
    """Operations, not paths -- one path with GET and POST is two endpoints,
    matching what Elva reports back after an import."""
    if not isinstance(paths, dict):
        return None
    total = 0
    for operations in paths.values():
        if isinstance(operations, dict):
            total += sum(1 for key in operations if str(key).lower() in _METHODS)
    return total


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    # An unquoted YAML version like `version: 1.0` parses as a float.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None
