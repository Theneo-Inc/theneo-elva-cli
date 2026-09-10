"""The collection listing service: resolution, sorting and error mapping.

Mirrors test_targets.py's approach -- the network call is replaced with a
recorder, so nothing here reaches out. The workspace resolver (ELVA-156) is
covered by test_targets.py; here it is stubbed so these tests stay about the
listing itself.
"""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from elva_cli.core import collections as service
from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.collections import AmbiguousCollection, CollectionSummaries
from elva_cli.errors import ApiError, AuthError, ExitCode, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
ID_ALPHA = "a" * 24
ID_ZEBRA = "b" * 24

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


def ctx(workspace: str | None = None) -> Any:
    """The slice of Ctx the service actually reads."""
    return SimpleNamespace(settings=SimpleNamespace(base_url=BASE_URL, workspace=workspace))


def responder(monkeypatch: pytest.MonkeyPatch, payload: Any) -> list[str]:
    """Replace the collections GET and record the URLs asked for."""
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0) -> Any:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))


@pytest.mark.usefixtures("signed_in")
class TestListCollections:
    def test_summaries_come_back_sorted_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = responder(monkeypatch, TWO)
        result = service.list_collections(ctx())
        assert [summary.name for summary in result] == ["Alpha", "Zebra"]
        assert seen == [f"{BASE_URL}/api/companies/{COMPANY}/collections"]

    def test_spec_uploaded_is_derived_from_spec_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(monkeypatch, TWO)
        alpha, zebra = service.list_collections(ctx())
        assert alpha.spec_uploaded is False  # specTitle was empty
        assert zebra.spec_uploaded is True

    def test_the_rest_of_the_fields_survive_the_round_trip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(monkeypatch, TWO)
        alpha, zebra = service.list_collections(ctx())
        assert (zebra.endpoint_count, zebra.labels, zebra.is_demo) == (3, ("public",), False)
        assert alpha.is_demo is True

    def test_no_company_id_leaks_into_a_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        for summary in service.list_collections(ctx()):
            assert COMPANY not in (summary.id, summary.name)

    def test_a_malformed_payload_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"collections": "nope"})
        with pytest.raises(ApiError):
            service.list_collections(ctx())


@pytest.mark.usefixtures("signed_in")
class TestResolveCollection:
    def test_matched_by_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        assert service.resolve_collection(ctx(), ID_ALPHA).name == "Alpha"

    def test_matched_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        assert service.resolve_collection(ctx(), "Zebra").id == ID_ZEBRA

    def test_an_unknown_ref_is_usage_and_names_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, TWO)
        with pytest.raises(UsageError) as caught:
            service.resolve_collection(ctx(), "Nope")
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
            service.resolve_collection(ctx(), "api")
        assert caught.value.exit_code == ExitCode.USAGE
        assert {candidate.id for candidate in caught.value.candidates} == {"c" * 24, "d" * 24}


@pytest.mark.usefixtures("signed_in")
class TestErrorMapping:
    def test_401_is_an_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError) as caught:
            service.list_collections(ctx())
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_server_error_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(503, None))
        with pytest.raises(ApiError) as caught:
            service.list_collections(ctx())
        assert caught.value.exit_code == ExitCode.API

    def test_a_connection_failure_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # get_json turns a dead socket into ApiError before the caller sees it.
        responder(monkeypatch, ApiError("Could not reach the server."))
        with pytest.raises(ApiError) as caught:
            service.list_collections(ctx())
        assert caught.value.exit_code == ExitCode.API

    def test_403_and_404_point_at_the_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for status in (403, 404):
            responder(monkeypatch, HttpError(status, None))
            with pytest.raises(UsageError) as caught:
                service.list_collections(ctx())
            assert caught.value.exit_code == ExitCode.USAGE
            assert "--workspace" in (caught.value.hint or "")


class TestWorkspaceResolution:
    def test_an_unresolvable_workspace_names_both_the_flag_and_the_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")

        def ambiguous(**_: Any) -> Target:
            raise UsageError(
                "more than one workspace, so there is no obvious default",
                hint="Pass --workspace with one of: Theneo, Side",
            )

        monkeypatch.setattr(service, "resolve_workspace", ambiguous)
        with pytest.raises(UsageError) as caught:
            service.list_collections(ctx())
        assert caught.value.exit_code == ExitCode.USAGE
        assert "--workspace" in (caught.value.hint or "")
        assert "ELVA_WORKSPACE" in (caught.value.hint or "")


@pytest.mark.usefixtures("signed_in")
class TestOutputParity:
    """--json and the human table start from the same summaries."""

    @staticmethod
    def _human(envelope: CollectionSummaries) -> str:
        from elva_cli.ui.renderables import render
        from elva_cli.ui.theme import ELVA_THEME

        buffer = StringIO()
        Console(file=buffer, width=120, no_color=True, theme=ELVA_THEME).print(render(envelope))
        return buffer.getvalue()

    def test_json_is_an_unwrapped_array_matching_the_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from elva_cli.ui.output import as_data

        responder(monkeypatch, TWO)
        envelope = CollectionSummaries(service.list_collections(ctx()))

        data = as_data(envelope)
        assert isinstance(data, list)  # unwrapped: no {"collections": ...} key
        parsed = json.loads(json.dumps(data, default=str))
        assert [row["name"] for row in parsed] == ["Alpha", "Zebra"]
        assert parsed[0]["spec_uploaded"] is False

        table = self._human(envelope)
        for row in parsed:
            assert row["name"] in table
            assert row["id"] in table
