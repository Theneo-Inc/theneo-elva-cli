from __future__ import annotations

from typing import Any

import pytest

from elva_cli.core.api import targets
from elva_cli.core.api.http import HttpError
from elva_cli.errors import ApiError, AuthError, UsageError

BASE_URL = "https://api.getelva.ai"
OID = "0123456789abcdef01234567"


def responder(monkeypatch: pytest.MonkeyPatch, payload: Any) -> list[str]:
    """Replace the GET and record which URLs were asked for."""
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0, reauth: Any = None) -> Any:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(targets, "get_json", fake_get)
    return seen


class TestResolveWorkspace:
    def test_an_id_skips_the_lookup_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = responder(monkeypatch, {"workspaces": []})
        target = targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=OID)
        assert target.id == OID
        assert seen == []

    def test_a_single_workspace_needs_no_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        target = targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=None)
        assert target.id == OID
        assert target.name == "Theneo"

    def test_several_workspaces_and_no_flag_lists_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo"}, {"id": "b" * 24, "name": "Side"}]},
        )
        with pytest.raises(UsageError) as caught:
            targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=None)
        assert caught.value.hint is not None
        assert "Theneo" in caught.value.hint
        assert "Side" in caught.value.hint

    def test_matched_by_name_case_insensitively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        target = targets.resolve_workspace(base_url=BASE_URL, token="t", workspace="  theneo ")
        assert target.id == OID

    def test_matched_by_company_slug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo Inc", "companySlug": "theneo"}]},
        )
        target = targets.resolve_workspace(base_url=BASE_URL, token="t", workspace="theneo")
        assert target.id == OID

    def test_an_unknown_name_lists_what_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        with pytest.raises(UsageError) as caught:
            targets.resolve_workspace(base_url=BASE_URL, token="t", workspace="nope")
        assert caught.value.hint is not None
        assert "Theneo" in caught.value.hint

    def test_an_account_with_no_workspaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": []})
        with pytest.raises(UsageError, match="no workspaces"):
            targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=None)

    def test_a_rejected_lookup_becomes_an_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError):
            targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=None)

    def test_a_malformed_payload_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": "not a list"})
        with pytest.raises(ApiError):
            targets.resolve_workspace(base_url=BASE_URL, token="t", workspace=None)


class TestResolveCollection:
    def test_an_id_skips_the_lookup_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = responder(monkeypatch, {"collections": []})
        target = targets.resolve_collection(
            base_url=BASE_URL, token="t", company_id=OID, collection=OID
        )
        assert target.id == OID
        assert seen == []

    def test_matched_by_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = responder(
            monkeypatch, {"collections": [{"id": "c" * 24, "name": "test-collection"}]}
        )
        target = targets.resolve_collection(
            base_url=BASE_URL, token="t", company_id=OID, collection="test-collection"
        )
        assert target.id == "c" * 24
        assert seen == [f"{BASE_URL}/api/companies/{OID}/collections"]

    def test_an_unknown_name_lists_what_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"collections": [{"id": "c" * 24, "name": "payments"}]})
        with pytest.raises(UsageError) as caught:
            targets.resolve_collection(
                base_url=BASE_URL, token="t", company_id=OID, collection="typo"
            )
        assert caught.value.hint is not None
        assert "payments" in caught.value.hint

    def test_duplicate_names_ask_for_an_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {"collections": [{"id": "c" * 24, "name": "api"}, {"id": "d" * 24, "name": "api"}]},
        )
        with pytest.raises(UsageError) as caught:
            targets.resolve_collection(
                base_url=BASE_URL, token="t", company_id=OID, collection="api"
            )
        assert caught.value.hint is not None
        assert "c" * 24 in caught.value.hint

    def test_an_empty_workspace_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"collections": []})
        with pytest.raises(UsageError) as caught:
            targets.resolve_collection(
                base_url=BASE_URL, token="t", company_id=OID, collection="api"
            )
        assert caught.value.hint is not None
        assert "no collections yet" in caught.value.hint

    def test_a_404_points_at_the_workspace_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, HttpError(404, None))
        with pytest.raises(UsageError) as caught:
            targets.resolve_collection(
                base_url=BASE_URL, token="t", company_id=OID, collection="api"
            )
        assert caught.value.hint is not None
        assert "--workspace" in caught.value.hint
