"""The collection services: listing, resolution, detail, and error mapping.

Mirrors test_targets.py's approach -- the network call is replaced with a
recorder, so nothing here reaches out. Workspace resolution (ELVA-156) lives in
the command layer now (see tests/unit/test_collection_show.py); these services
take the already-resolved companyId as a plain value, so there is nothing to
stub for it.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from elva_cli.core import collections as service
from elva_cli.core.api.http import HttpError
from elva_cli.core.collections import (
    AmbiguousCollection,
    CollectionDetail,
    CollectionSummaries,
)
from elva_cli.errors import ApiError, AuthError, ExitCode, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
ID_ALPHA = "a" * 24
ID_ZEBRA = "b" * 24

LIST_URL = f"{BASE_URL}/api/companies/{COMPANY}/collections"


def detail_url(collection_id: str) -> str:
    return f"{LIST_URL}/{collection_id}"


TWO = {
    "collections": [
        {
            "id": ID_ZEBRA,
            "name": "Zebra",
            "specTitle": "Zebra API",
            "endpointCount": 3,
            "labels": ["public"],
            "isDemo": False,
            "updatedAt": "2026-01-02T10:00:00Z",
        },
        {
            "id": ID_ALPHA,
            "name": "Alpha",
            "specTitle": "",
            "endpointCount": 0,
            "labels": [],
            "isDemo": True,
            "updatedAt": "2026-02-01T10:00:00Z",
        },
    ]
}

ALPHA_DETAIL = {
    "collection": {
        "id": ID_ALPHA,
        "name": "Alpha",
        "description": "The alpha collection.",
        "specTitle": "Alpha API",
        "specVersion": "1.0",
        "labels": ["public", "beta"],
        "source": "openapi",
        "isDemo": False,
        "endpoints": [
            {"path": "/a", "method": "get"},
            {"path": "/b", "method": "post"},
        ],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-02-01T10:00:00Z",
    },
    "mcps": [
        {
            "deploymentId": "dep-1",
            "mcpSlug": "alpha-mcp",
            "mcpName": "Alpha MCP",
            "status": "published",
            "toolCount": 5,
            "collectionId": ID_ALPHA,
        }
    ],
}

NO_SPEC_DETAIL = {
    "collection": {
        "id": ID_ZEBRA,
        "name": "Zebra",
        "specTitle": "",
        "labels": [],
        "isDemo": False,
        "updatedAt": "2026-01-02T10:00:00Z",
    },
    "mcps": [],
}


def responder(monkeypatch: pytest.MonkeyPatch, payload: Any) -> list[str]:
    """Replace the collections GET with a single fixed answer, recording URLs."""
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0, reauth: Any = None) -> Any:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


def routes(monkeypatch: pytest.MonkeyPatch, table: dict[str, Any]) -> list[str]:
    """Replace the collections GET with a per-URL answer, recording URLs."""
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0, reauth: Any = None) -> Any:
        seen.append(url)
        answer = table[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


class TestListCollections:
    def test_summaries_come_back_sorted_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = responder(monkeypatch, TWO)
        result = service.list_collections(BASE_URL, "tok", COMPANY)
        assert [summary.name for summary in result] == ["Alpha", "Zebra"]
        assert seen == [LIST_URL]

    def test_spec_uploaded_is_derived_from_spec_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(monkeypatch, TWO)
        alpha, zebra = service.list_collections(BASE_URL, "tok", COMPANY)
        assert alpha.spec_uploaded is False  # specTitle was empty
        assert zebra.spec_uploaded is True

    def test_the_rest_of_the_fields_survive_the_round_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(monkeypatch, TWO)
        alpha, zebra = service.list_collections(BASE_URL, "tok", COMPANY)
        assert (zebra.endpoint_count, zebra.labels, zebra.is_demo) == (3, ("public",), False)
        assert alpha.is_demo is True

    def test_no_company_id_leaks_into_a_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        for summary in service.list_collections(BASE_URL, "tok", COMPANY):
            assert COMPANY not in (summary.id, summary.name)

    def test_a_malformed_payload_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"collections": "nope"})
        with pytest.raises(ApiError):
            service.list_collections(BASE_URL, "tok", COMPANY)


class TestResolveCollection:
    def test_matched_by_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        assert service.resolve_collection(BASE_URL, "tok", COMPANY, ID_ALPHA).name == "Alpha"

    def test_matched_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        assert service.resolve_collection(BASE_URL, "tok", COMPANY, "Zebra").id == ID_ZEBRA

    def test_an_unknown_ref_is_usage_and_names_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        with pytest.raises(UsageError) as caught:
            service.resolve_collection(BASE_URL, "tok", COMPANY, "Nope")
        assert caught.value.exit_code == ExitCode.USAGE
        assert "Nope" in str(caught.value)

    def test_duplicate_names_raise_ambiguous_carrying_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(
            monkeypatch,
            {"collections": [{"id": "c" * 24, "name": "api"}, {"id": "d" * 24, "name": "api"}]},
        )
        with pytest.raises(AmbiguousCollection) as caught:
            service.resolve_collection(BASE_URL, "tok", COMPANY, "api")
        assert caught.value.exit_code == ExitCode.USAGE
        assert {candidate.id for candidate in caught.value.candidates} == {"c" * 24, "d" * 24}


class TestGetCollection:
    def test_by_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): ALPHA_DETAIL})
        detail = service.get_collection(BASE_URL, "tok", COMPANY, ID_ALPHA)
        assert detail.id == ID_ALPHA
        assert detail.name == "Alpha"
        assert detail.spec_uploaded is True
        assert (detail.spec_title, detail.spec_version) == ("Alpha API", "1.0")
        assert detail.endpoint_count == 2
        assert detail.labels == ("public", "beta")
        assert detail.source == "openapi"
        assert detail.created_at == "2026-01-01T00:00:00Z"

    def test_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): ALPHA_DETAIL})
        detail = service.get_collection(BASE_URL, "tok", COMPANY, "Alpha")
        assert detail.id == ID_ALPHA

    def test_mcps_are_carried_across(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): ALPHA_DETAIL})
        detail = service.get_collection(BASE_URL, "tok", COMPANY, ID_ALPHA)
        (mcp,) = detail.mcps
        assert (mcp.name, mcp.slug, mcp.status, mcp.tool_count) == (
            "Alpha MCP",
            "alpha-mcp",
            "published",
            5,
        )
        assert mcp.deployment_id == "dep-1"

    def test_a_collection_with_no_spec_or_mcps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ZEBRA): NO_SPEC_DETAIL})
        detail = service.get_collection(BASE_URL, "tok", COMPANY, ID_ZEBRA)
        assert detail.spec_uploaded is False
        assert detail.spec_title is None
        assert detail.endpoint_count == 0
        assert detail.mcps == ()

    def test_a_404_after_resolve_is_usage_not_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): HttpError(404, None)})
        with pytest.raises(UsageError) as caught:
            service.get_collection(BASE_URL, "tok", COMPANY, ID_ALPHA)
        assert caught.value.exit_code == ExitCode.USAGE
        assert "Alpha" in str(caught.value)

    def test_401_on_the_detail_call_is_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): HttpError(401, None)})
        with pytest.raises(AuthError) as caught:
            service.get_collection(BASE_URL, "tok", COMPANY, ID_ALPHA)
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_server_error_on_the_detail_call_is_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        routes(monkeypatch, {LIST_URL: TWO, detail_url(ID_ALPHA): HttpError(503, None)})
        with pytest.raises(ApiError) as caught:
            service.get_collection(BASE_URL, "tok", COMPANY, ID_ALPHA)
        assert caught.value.exit_code == ExitCode.API


class TestErrorMapping:
    def test_401_is_an_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError) as caught:
            service.list_collections(BASE_URL, "tok", COMPANY)
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_server_error_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(503, None))
        with pytest.raises(ApiError) as caught:
            service.list_collections(BASE_URL, "tok", COMPANY)
        assert caught.value.exit_code == ExitCode.API

    def test_a_connection_failure_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_json turns a dead socket into ApiError before the caller sees it.
        responder(monkeypatch, ApiError("Could not reach the server."))
        with pytest.raises(ApiError) as caught:
            service.list_collections(BASE_URL, "tok", COMPANY)
        assert caught.value.exit_code == ExitCode.API

    def test_403_and_404_point_at_the_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for status in (403, 404):
            responder(monkeypatch, HttpError(status, None))
            with pytest.raises(UsageError) as caught:
                service.list_collections(BASE_URL, "tok", COMPANY)
            assert caught.value.exit_code == ExitCode.USAGE
            assert "--workspace" in (caught.value.hint or "")


def _human(result: object) -> str:
    from elva_cli.ui.renderables import render
    from elva_cli.ui.theme import ELVA_THEME

    buffer = StringIO()
    Console(file=buffer, width=120, no_color=True, theme=ELVA_THEME).print(render(result))
    return buffer.getvalue()


class TestListOutputParity:
    """--json and the human table start from the same summaries."""

    def test_json_is_an_unwrapped_array_matching_the_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from elva_cli.ui.output import as_data

        responder(monkeypatch, TWO)
        envelope = CollectionSummaries(service.list_collections(BASE_URL, "tok", COMPANY))

        data = as_data(envelope)
        assert isinstance(data, list)  # unwrapped: no {"collections": ...} key
        parsed = json.loads(json.dumps(data, default=str))
        assert [row["name"] for row in parsed] == ["Alpha", "Zebra"]
        assert parsed[0]["spec_uploaded"] is False

        table = _human(envelope)
        for row in parsed:
            assert row["name"] in table
            assert row["id"] in table


class TestDetailOutputParity:
    """--json emits the detail unwrapped with mcps nested; the human view agrees."""

    def _detail(self, monkeypatch: pytest.MonkeyPatch, payload: Any, ref: str) -> CollectionDetail:
        target = payload["collection"]["id"]
        routes(monkeypatch, {LIST_URL: TWO, detail_url(target): payload})
        return service.get_collection(BASE_URL, "tok", COMPANY, ref)

    def test_json_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from elva_cli.ui.output import as_data

        detail = self._detail(monkeypatch, ALPHA_DETAIL, ID_ALPHA)
        data = json.loads(json.dumps(as_data(detail), default=str))

        assert data["id"] == ID_ALPHA
        assert data["name"] == "Alpha"
        assert data["spec_uploaded"] is True
        assert data["spec_title"] == "Alpha API"
        assert data["endpoint_count"] == 2
        assert data["labels"] == ["public", "beta"]
        # mcps nested inside the object, not a sibling envelope key.
        assert [m["name"] for m in data["mcps"]] == ["Alpha MCP"]
        assert data["mcps"][0]["tool_count"] == 5

    def test_human_view_shows_the_collection_and_its_mcps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = self._detail(monkeypatch, ALPHA_DETAIL, ID_ALPHA)
        rendered = _human(detail)
        assert "Alpha" in rendered
        assert ID_ALPHA in rendered
        assert "Alpha API" in rendered
        assert "MCP SERVERS" in rendered
        assert "alpha-mcp" in rendered

    def test_a_no_spec_collection_renders_without_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = self._detail(monkeypatch, NO_SPEC_DETAIL, ID_ZEBRA)
        rendered = _human(detail)
        assert "Zebra" in rendered
        assert "no" in rendered  # spec: no
        assert "MCP SERVERS" not in rendered  # nothing to table
