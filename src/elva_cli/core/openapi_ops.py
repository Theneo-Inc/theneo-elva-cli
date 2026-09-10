"""Read the operations out of an uploaded OpenAPI spec.

Pure functions over a spec's raw text: no I/O, no Ctx, no rendering. The command
layer fetches the raw file (see get_collection_operations) and hands it here.

The one thing to get right is the operation `key`. `elva mcp create` selects
operations by "<METHOD> <path>" -- method uppercased, one space -- in preference
to a tool name or the raw operationId, because that pair is unambiguous even when
operationId is missing or duplicated across paths. So that is what `key` carries,
and it is what to pipe into `elva mcp create --operations`. `operation_id` is
emitted too, but only for a human to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from elva_cli.errors import ValidationError

# The HTTP methods an OpenAPI path item may carry, in the order operations are
# emitted for a given path. Everything else under a path item (parameters,
# servers, summary, description, $ref, x-*) is not an operation and is skipped.
_METHOD_ORDER = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
_METHODS = frozenset(_METHOD_ORDER)
_METHOD_RANK = {method: rank for rank, method in enumerate(_METHOD_ORDER)}


class SpecInvalid(ValidationError):  # noqa: N818  named for the domain, not the -Error suffix
    """The uploaded spec is not an OpenAPI document the CLI can read.

    A ValidationError, so it carries exit code 4: the spec is wrong, the tool
    worked. This is never raised for a network or storage failure -- those stay
    ApiError (exit 5). Keep that line clean: a caller must be able to trust that
    4 means the spec and 5 means the transport.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, hint="The spec must be a JSON or YAML OpenAPI document.")


@dataclass(frozen=True)
class Operation:
    """One operation from a spec's paths, flattened for listing.

    `key` is the "<METHOD> <path>" selector `elva mcp create` accepts; `method`
    is uppercased to match it. `tags` is a tuple so the whole thing is hashable
    and frozen.
    """

    key: str
    method: str
    path: str
    operation_id: str | None
    summary: str | None
    tags: tuple[str, ...]


class CollectionOperations(tuple[Operation, ...]):
    """The output envelope for `collection endpoints`.

    A distinct type so the output layer dispatches a table on it, while `--json`
    still serialises it as a bare array of operations (a tuple has no wrapper
    key). Mirrors CollectionSummaries.
    """

    __slots__ = ()


def parse_spec(raw: str) -> dict[str, Any]:
    """The spec as a mapping, or SpecInvalid.

    JSON is tried first, then YAML -- YAML is nearly a superset, so one attempt
    each covers both the JSON and YAML files the backend stores verbatim. A
    document that neither parser can read, that parses to something other than a
    mapping (a scalar, a list, null), or that has no mapping `paths`, is not an
    OpenAPI spec this command can list, so it is SpecInvalid (exit 4).
    """
    document = _load(raw)
    if not isinstance(document, dict):
        raise SpecInvalid("the spec did not parse to an OpenAPI document")
    if not isinstance(document.get("paths"), dict):
        raise SpecInvalid("the spec has no paths object")
    return document


def extract_operations(spec: dict[str, Any]) -> list[Operation]:
    """Every operation in `spec`, sorted by path then by method order.

    For each path item only the HTTP-method keys are operations; parameters,
    servers, summary, description, $ref and x-* are skipped. A path item that is
    not a mapping (a $ref string, say) contributes nothing. Sorting by path and
    then by _METHOD_ORDER -- not alphabetically -- makes the output stable, so a
    diff between two runs is meaningful.
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
    """The subset of `ops` matching every filter that was given.

    Each filter is an OR within itself and an AND across filters: an operation
    is kept when it has any of `tags`, and its method is any of `methods`
    (case-insensitive), and its path starts with any of `path_prefixes`. An empty
    filter is not a constraint -- it lets everything through.
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
