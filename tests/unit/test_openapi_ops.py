"""The pure spec reader: parsing, operation extraction, and filtering.

No network here -- these functions take raw text or a parsed spec and nothing
else, so the tests are just data in, data out.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from elva_cli.core.openapi_ops import (
    Operation,
    SpecInvalid,
    extract_operations,
    filter_operations,
    parse_spec,
)
from elva_cli.errors import ExitCode

JSON_SPEC = json.dumps(
    {
        "openapi": "3.0.0",
        "paths": {
            "/users/{id}": {
                "get": {"operationId": "getUser", "summary": "Fetch a user", "tags": ["users"]}
            }
        },
    }
)

YAML_SPEC = """
openapi: 3.0.0
paths:
  /users/{id}:
    get:
      operationId: getUser
      summary: Fetch a user
      tags: [users]
"""


class TestParseSpec:
    def test_json(self) -> None:
        spec = parse_spec(JSON_SPEC)
        assert isinstance(spec["paths"], dict)
        assert "/users/{id}" in spec["paths"]

    def test_yaml(self) -> None:
        spec = parse_spec(YAML_SPEC)
        assert isinstance(spec["paths"], dict)
        assert "/users/{id}" in spec["paths"]

    def test_json_and_yaml_agree(self) -> None:
        from_json = extract_operations(parse_spec(JSON_SPEC))
        from_yaml = extract_operations(parse_spec(YAML_SPEC))
        assert from_json == from_yaml

    def test_invalid_text_is_spec_invalid(self) -> None:
        # Parses as neither JSON nor YAML: an unclosed flow collection.
        with pytest.raises(SpecInvalid) as caught:
            parse_spec("{[}")
        assert caught.value.exit_code == ExitCode.VALIDATION

    def test_json_without_paths_is_spec_invalid(self) -> None:
        with pytest.raises(SpecInvalid):
            parse_spec(json.dumps({"openapi": "3.0.0"}))

    def test_paths_that_is_not_a_mapping_is_spec_invalid(self) -> None:
        with pytest.raises(SpecInvalid):
            parse_spec(json.dumps({"paths": ["/a", "/b"]}))

    def test_a_scalar_document_is_spec_invalid(self) -> None:
        # Valid YAML, but it parses to a bare string, not a mapping.
        with pytest.raises(SpecInvalid):
            parse_spec("just a string")

    def test_a_number_document_is_spec_invalid(self) -> None:
        with pytest.raises(SpecInvalid):
            parse_spec("42")

    def test_spec_invalid_carries_exit_four(self) -> None:
        with pytest.raises(SpecInvalid) as caught:
            parse_spec("null")
        assert caught.value.exit_code == ExitCode.VALIDATION


class TestExtractOperations:
    def test_the_key_format_is_exactly_method_space_path(self) -> None:
        spec: dict[str, Any] = {"paths": {"/users/{id}": {"get": {}}}}
        (op,) = extract_operations(spec)
        assert op.key == "GET /users/{id}"
        assert op.method == "GET"
        assert op.path == "/users/{id}"

    def test_missing_operation_id_and_tags_become_none_and_empty(self) -> None:
        spec = {"paths": {"/a": {"get": {"summary": "hi"}}}}
        (op,) = extract_operations(spec)
        assert op.operation_id is None
        assert op.tags == ()
        assert op.summary == "hi"

    def test_non_method_keys_under_a_path_are_skipped(self) -> None:
        spec = {
            "paths": {
                "/a": {
                    "parameters": [{"name": "q"}],
                    "servers": [{"url": "https://x"}],
                    "summary": "path summary",
                    "description": "path description",
                    "$ref": "#/somewhere",
                    "x-internal": True,
                    "get": {"operationId": "getA"},
                }
            }
        }
        ops = extract_operations(spec)
        assert [op.key for op in ops] == ["GET /a"]

    def test_a_path_item_that_is_not_a_mapping_contributes_nothing(self) -> None:
        spec = {"paths": {"/ref": "#/paths/shared", "/a": {"get": {}}}}
        assert [op.key for op in extract_operations(spec)] == ["GET /a"]

    def test_ordering_is_path_then_method_order_not_alphabetical(self) -> None:
        spec: dict[str, Any] = {
            "paths": {
                "/b": {"get": {}},
                "/a": {"delete": {}, "get": {}, "post": {}},
            }
        }
        # /a before /b (path sort); within /a, get, post, delete -- method order,
        # not the alphabetical delete, get, post.
        assert [op.key for op in extract_operations(spec)] == [
            "GET /a",
            "POST /a",
            "DELETE /a",
            "GET /b",
        ]

    def test_all_eight_methods_are_recognised(self) -> None:
        methods = ["get", "post", "put", "patch", "delete", "head", "options", "trace"]
        spec: dict[str, Any] = {"paths": {"/a": {m: {} for m in methods}}}
        assert [op.method for op in extract_operations(spec)] == [m.upper() for m in methods]

    def test_uppercase_method_keys_are_normalised(self) -> None:
        (op,) = extract_operations({"paths": {"/a": {"GET": {}}}})
        assert op.method == "GET"
        assert op.key == "GET /a"


def _op(method: str, path: str, tags: tuple[str, ...] = ()) -> Operation:
    return Operation(
        key=f"{method} {path}",
        method=method,
        path=path,
        operation_id=None,
        summary=None,
        tags=tags,
    )


class TestFilterOperations:
    def _ops(self) -> list[Operation]:
        return [
            _op("GET", "/users", ("users",)),
            _op("POST", "/users", ("users", "admin")),
            _op("GET", "/orders", ("orders",)),
            _op("DELETE", "/orders/{id}", ("orders", "admin")),
        ]

    def test_no_filters_keeps_everything(self) -> None:
        ops = self._ops()
        assert filter_operations(ops) == ops

    def test_tags_keep_operations_with_any_of_them(self) -> None:
        kept = filter_operations(self._ops(), tags=("admin",))
        assert [op.key for op in kept] == ["POST /users", "DELETE /orders/{id}"]

    def test_tags_are_an_or_within_the_filter(self) -> None:
        kept = filter_operations(self._ops(), tags=("users", "orders"))
        assert len(kept) == 4

    def test_methods_are_case_insensitive(self) -> None:
        kept = filter_operations(self._ops(), methods=("get",))
        assert [op.key for op in kept] == ["GET /users", "GET /orders"]

    def test_path_prefixes_match_by_startswith(self) -> None:
        kept = filter_operations(self._ops(), path_prefixes=("/orders",))
        assert [op.key for op in kept] == ["GET /orders", "DELETE /orders/{id}"]

    def test_filters_are_anded_across(self) -> None:
        kept = filter_operations(
            self._ops(), tags=("admin",), methods=("delete",), path_prefixes=("/orders",)
        )
        assert [op.key for op in kept] == ["DELETE /orders/{id}"]

    def test_an_impossible_combination_is_empty(self) -> None:
        assert filter_operations(self._ops(), methods=("get",), tags=("admin",)) == []
