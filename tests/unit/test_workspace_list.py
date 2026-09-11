from __future__ import annotations

from typing import Any

import pytest

from elva_cli.core.api.http import HttpError
from elva_cli.core.services import workspace_list
from elva_cli.errors import ApiError, AuthError

BASE_URL = "https://api.getelva.ai"
OID = "0123456789abcdef01234567"


def responder(monkeypatch: pytest.MonkeyPatch, payload: Any) -> list[str]:
    seen: list[str] = []

    def fake_get(url: str, *, token: str, timeout: float = 30.0) -> Any:
        seen.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(workspace_list, "get_json", fake_get)
    monkeypatch.setattr(workspace_list, "get_access_token", lambda *, base_url: "t")
    return seen


class TestListWorkspaces:
    def test_empty_list_with_nothing_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": []})
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace=None, active_origin="default"
        )
        assert result.workspaces == []
        assert result.configured_matched is True
        assert result.configured_workspace is None
        assert result.configured_origin is None

    def test_empty_list_with_configured_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": []})
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace="payments-old", active_origin="project"
        )
        assert result.workspaces == []
        assert result.configured_matched is False
        assert result.configured_workspace == "payments-old"
        assert result.configured_origin == "project"

    def test_single_row_auto_selects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace=None, active_origin="default"
        )
        [item] = result.workspaces
        assert item.active is True
        assert item.active_source == "auto"
        assert result.configured_matched is True

    def test_matched_by_name_case_insensitively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {
                "workspaces": [
                    {"id": OID, "name": "Theneo", "companySlug": "theneo"},
                    {"id": "b" * 24, "name": "Side"},
                ]
            },
        )
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace="  THENEO ", active_origin="project"
        )
        active = [w for w in result.workspaces if w.active]
        assert len(active) == 1
        assert active[0].name == "Theneo"
        assert active[0].active_source == "project"
        assert result.configured_matched is True

    def test_matched_by_company_slug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo Inc", "companySlug": "theneo"}]},
        )
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace="theneo", active_origin="user"
        )
        [item] = result.workspaces
        assert item.active is True
        assert item.active_source == "user"

    def test_matched_by_lowercase_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace=OID, active_origin="user"
        )
        assert result.workspaces[0].active is True
        assert result.configured_matched is True

    def test_matched_by_uppercase_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": [{"id": OID, "name": "Theneo"}]})
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace=OID.upper(), active_origin="user"
        )
        assert result.workspaces[0].active is True
        assert result.configured_matched is True

    def test_configured_value_matches_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {
                "workspaces": [
                    {"id": OID, "name": "Payments Team"},
                    {"id": "b" * 24, "name": "Platform"},
                ]
            },
        )
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace="payments-old", active_origin="project"
        )
        assert all(not w.active for w in result.workspaces)
        assert result.configured_matched is False
        assert result.configured_workspace == "payments-old"
        assert result.configured_origin == "project"

    def test_malformed_rows_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo"}, {"id": "x" * 24}, "junk"]},
        )
        result = workspace_list.list_workspaces(
            base_url=BASE_URL, active_workspace=None, active_origin="default"
        )
        assert [w.name for w in result.workspaces] == ["Theneo"]

    def test_unexpected_payload_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responder(monkeypatch, {"workspaces": "not a list"})
        with pytest.raises(ApiError):
            workspace_list.list_workspaces(
                base_url=BASE_URL, active_workspace=None, active_origin="default"
            )

    def test_unauthenticated_lookup_becomes_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responder(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError):
            workspace_list.list_workspaces(
                base_url=BASE_URL, active_workspace=None, active_origin="default"
            )
