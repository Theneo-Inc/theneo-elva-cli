"""Read the operations out of an OpenAPI spec. Pure functions over raw text.

The thing to get right is `key`. `elva mcp create` selects operations by
"<METHOD> <path>", which stays unambiguous when operationId is missing or
repeated, so that is what `key` carries. `operation_id` is for people to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from elva_cli.errors import ValidationError

# The method keys of a path item, in output order. Anything else under a path
# item (parameters, servers, $ref, x-*) is not an operation.
_METHOD_ORDER = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
_METHODS = frozenset(_METHOD_ORDER)
_METHOD_RANK = {method: rank for rank, method in enumerate(_METHOD_ORDER)}


class SpecInvalid(ValidationError):  # noqa: N818  named for the domain, not the -Error suffix
    """The spec is not something the CLI can read. Exit 4, never used for network
    or storage failures.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, hint="The spec must be a JSON or YAML OpenAPI document.")


@dataclass(frozen=True)
class Operation:
    """One operation from a spec's paths, flattened for listing."""

    key: str
    method: str
    path: str
    operation_id: str | None
    summary: str | None
    tags: tuple[str, ...]


class CollectionOperations(tuple[Operation, ...]):
    """The output envelope for `collection endpoints`, so --json stays a bare array."""

    __slots__ = ()


def parse_spec(raw: str) -> dict[str, Any]:
    """The spec as a mapping, or SpecInvalid.

    JSON first, then YAML, which covers both formats the backend stores.
    """
    document = _load(raw)
    if not isinstance(document, dict):
        raise SpecInvalid("the spec did not parse to an OpenAPI document")
    if not isinstance(document.get("paths"), dict):
        raise SpecInvalid("the spec has no paths object")
    return document


def extract_operations(spec: dict[str, Any]) -> list[Operation]:
    """Every operation in `spec`, sorted by path then method.

    Sorted rather than left in document order so a diff between two runs means
    something.
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

    operations: list[Operation] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for key, body in item.items():
            method = str(key).lower()
            if method not in _METHODS:
                continue
            operations.append(_operation(str(path), method, body if isinstance(body, dict) else {}))

    operations.sort(key=lambda op: (op.path, _METHOD_RANK[op.method.lower()]))
    return operations


def filter_operations(
    ops: list[Operation],
    tags: tuple[str, ...] = (),
    methods: tuple[str, ...] = (),
    path_prefixes: tuple[str, ...] = (),
) -> list[Operation]:
    """The subset of `ops` matching every filter given.

    OR within a filter, AND across them. An empty filter is not a constraint.
    """
    wanted_tags = frozenset(tags)
    wanted_methods = frozenset(method.upper() for method in methods)
    prefixes = tuple(path_prefixes)

    kept: list[Operation] = []
    for op in ops:
        if wanted_tags and wanted_tags.isdisjoint(op.tags):
            continue
        if wanted_methods and op.method.upper() not in wanted_methods:
            continue
        if prefixes and not any(op.path.startswith(prefix) for prefix in prefixes):
            continue
        kept.append(op)
    return kept


def _operation(path: str, method: str, body: dict[str, Any]) -> Operation:
    return Operation(
        key=f"{method.upper()} {path}",
        method=method.upper(),
        path=path,
        operation_id=_text(body.get("operationId")),
        summary=_text(body.get("summary")),
        tags=_tags(body.get("tags")),
    )


def _load(raw: str) -> object:
    """The parsed document, or SpecInvalid when neither parser can read it."""
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    import yaml

    try:
        return yaml.safe_load(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise SpecInvalid("the spec is not valid JSON or YAML") from exc


def _tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(tag.strip() for tag in value if isinstance(tag, str) and tag.strip())


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
