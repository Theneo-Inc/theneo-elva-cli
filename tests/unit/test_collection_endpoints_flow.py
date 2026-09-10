"""`get_collection_operations`: fetch the spec, read the operations, map errors.

Same recorder-for-the-network approach as test_collections_flow.py -- the GET is
replaced with a per-URL table, so nothing here reaches out. The point of most of
these is the exit-code contract: a bad spec is 4, a transport or storage fault is
5, and the two never trade places.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from elva_cli.core import collections as service
from elva_cli.core.api.http import HttpError
from elva_cli.core.openapi_ops import CollectionOperations, SpecInvalid
from elva_cli.errors import ApiError, AuthError, ExitCode, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
ID = "a" * 24

LIST_URL = f"{BASE_URL}/api/companies/{COMPANY}/collections"
SPEC_URL = f"{LIST_URL}/{ID}/spec"

ONE = {"collections": [{"id": ID, "name": "Payments", "endpointCount": 2}]}

SPEC_JSON = json.dumps(
    {
        "openapi": "3.0.0",
        "paths": {
            "/invoices": {
                "get": {"operationId": "listInvoices", "summary": "List", "tags": ["billing"]},
                "post": {"operationId": "createInvoice", "tags": ["billing"]},
            }
        },
    }
)


def routes(monkeypatch: pytest.MonkeyPatch, table: dict[str, Any]) -> list[str]:
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0) -> Any:
        seen.append(url)
        answer = table[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


class TestHappyPath:
    def test_operations_come_back_from_the_spec(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": SPEC_JSON}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert [op.key for op in ops] == ["GET /invoices", "POST /invoices"]
        assert seen == [LIST_URL, SPEC_URL]

    def test_resolves_by_name_before_fetching(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": SPEC_JSON}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, "Payments")
        assert len(ops) == 2

    def test_a_yaml_spec_is_read_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        yaml_spec = "openapi: 3.0.0\npaths:\n  /ping:\n    get:\n      operationId: ping\n"
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": yaml_spec}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert [op.key for op in ops] == ["GET /ping"]


class TestExitCodes:
    def test_no_spec_uploaded_is_usage_exit_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(
            monkeypatch,
            {LIST_URL: ONE, SPEC_URL: HttpError(404, "Collection has no spec uploaded")},
        )
        with pytest.raises(UsageError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.USAGE
        assert "Payments" in str(caught.value)

    def test_spec_missing_in_storage_is_api_exit_five(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        routes(
            monkeypatch,
            {LIST_URL: ONE, SPEC_URL: HttpError(404, "Spec file not found in storage")},
        )
        with pytest.raises(ApiError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.API

    def test_a_malformed_spec_is_validation_exit_four(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": "{[}"}})
        with pytest.raises(SpecInvalid) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.VALIDATION

    def test_401_is_auth_exit_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: HttpError(401, None)})
        with pytest.raises(AuthError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_connection_failure_is_api_exit_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_json turns a dead socket into ApiError before the caller sees it.
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: ApiError("Could not reach the server.")})
        with pytest.raises(ApiError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.API

    def test_a_server_error_is_api_exit_five(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: HttpError(503, None)})
        with pytest.raises(ApiError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.API

    def test_an_unexpected_response_shape_is_api_not_validation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No "spec" string: a server fault (5), never a bad-spec verdict (4).
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"unexpected": True}})
        with pytest.raises(ApiError) as caught:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert caught.value.exit_code == ExitCode.API

    def test_four_and_five_are_never_confused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole reason the two are kept apart: a bad spec is the user's to
        fix (4); a transport failure is worth retrying (5)."""
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": "not: [valid"}})
        with pytest.raises(SpecInvalid) as bad_spec:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert bad_spec.value.exit_code == ExitCode.VALIDATION

        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: ApiError("Could not reach the server.")})
        with pytest.raises(ApiError) as network:
            service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert network.value.exit_code == ExitCode.API


def _human(result: object) -> str:
    from elva_cli.ui.renderables import render
    from elva_cli.ui.theme import ELVA_THEME

    buffer = StringIO()
    Console(file=buffer, width=120, no_color=True, theme=ELVA_THEME).print(render(result))
    return buffer.getvalue()


class TestOutput:
    def test_json_is_an_unwrapped_array_with_the_documented_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from elva_cli.ui.output import as_data

        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": SPEC_JSON}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        data = json.loads(json.dumps(as_data(CollectionOperations(ops)), default=str))

        assert isinstance(data, list)  # unwrapped: no envelope key
        assert data[0] == {
            "key": "GET /invoices",
            "method": "GET",
            "path": "/invoices",
            "operation_id": "listInvoices",
            "summary": "List",
            "tags": ["billing"],
        }
        assert data[1]["operation_id"] == "createInvoice"
        assert data[1]["summary"] is None  # missing summary -> null

    def test_json_and_human_output_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from elva_cli.ui.output import as_data

        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": SPEC_JSON}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        envelope = CollectionOperations(ops)

        table = _human(envelope)
        for row in as_data(envelope):
            assert row["path"] in table
            assert row["method"] in table

    def test_empty_renders_nothing_to_stdout(self) -> None:
        # The command adds the stderr note; the renderable keeps stdout clean.
        assert _human(CollectionOperations(())).strip() == ""


class TestLargeSpec:
    """A 1,500-operation spec must list every path in full: no fold, no "…"."""

    def _spec(self) -> str:
        paths: dict[str, Any] = {}
        # A long summary too, so the one column that may wrap is exercised: it must
        # fold, never clip to a "…".
        long_summary = "This operation does a great many things and its summary runs on " * 3
        for i in range(1500):
            # Deliberately long and parameterised, so a naive column would truncate.
            path = f"/api/v1/resources/{i:04d}/sub-resources/{{resourceId}}/details/{i:04d}"
            paths[path] = {"get": {"operationId": f"op{i:04d}", "summary": long_summary}}
        return json.dumps({"openapi": "3.0.0", "paths": paths})

    def test_every_path_is_present_and_nothing_is_ellipsised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": self._spec()}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        assert len(ops) == 1500

        rendered = _human(CollectionOperations(ops))
        assert "…" not in rendered  # the ellipsis rich would insert on truncation
        for op in ops:
            assert op.path in rendered

    def test_the_json_array_holds_all_1500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from elva_cli.ui.output import as_data

        routes(monkeypatch, {LIST_URL: ONE, SPEC_URL: {"spec": self._spec()}})
        ops = service.get_collection_operations(BASE_URL, "tok", COMPANY, ID)
        data = as_data(CollectionOperations(ops))
        assert len(data) == 1500
        assert data[0]["key"].startswith("GET /api/v1/resources/0000")
