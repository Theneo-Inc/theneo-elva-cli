from __future__ import annotations

from typing import Any

import pytest

from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import mcp as service
from elva_cli.core.services.mcp_result import McpListResult, McpServer, McpShowResult
from elva_cli.errors import ApiError, AuthError, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"

LIST_BODY = {
    "mcps": [
        {
            "mcpSlug": "widgets",
            "mcpName": "Widgets",
            "status": "published",
            "toolCount": 5,
            "collectionId": "c1",
        },
        {
            "mcpSlug": "gadgets",
            "mcpName": "Gadgets",
            "status": "draft",
            "toolCount": 0,
            "collectionId": "c2",
        },
    ]
}

SHOW_BODY = {
    "mcp": {
        "mcpSlug": "widgets",
        "mcpName": "Widgets",
        "status": "published",
        "toolCount": 5,
        "collectionId": "c1",
        "deploymentId": "acme/widgets",
        "version": "1.0.0",
        "selectedOperations": ["GET /widgets", "POST /widgets"],
        "authConfig": {"type": "oauth", "hasSecret": True},
        "collection": {"id": "c1", "name": "Widgets API"},
        "runtimeUrl": "https://runtime.getelva.ai",
        "settings": {},
    }
}


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))


def responder(monkeypatch: pytest.MonkeyPatch, response: Any) -> list[str]:
    seen: list[str] = []

    def fake_get(url: str, **_kwargs: Any) -> Any:
        seen.append(url)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


class TestListMcps:
    def test_maps_rows_into_summaries(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = responder(monkeypatch, LIST_BODY)
        result = service.list_mcps(base_url=BASE_URL, workspace=None)

        assert result == McpListResult(
            servers=(
                McpServer(
                    slug="widgets",
                    name="Widgets",
                    status="published",
                    tool_count=5,
                    collection_id="c1",
                ),
                McpServer(
                    slug="gadgets",
                    name="Gadgets",
                    status="draft",
                    tool_count=0,
                    collection_id="c2",
                ),
            )
        )
        assert seen == [f"{BASE_URL}/api/companies/{COMPANY}/mcps"]

    def test_no_servers_is_an_empty_list_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        responder(monkeypatch, {"mcps": []})
        result = service.list_mcps(base_url=BASE_URL, workspace=None)
        assert result == McpListResult(servers=())

    def test_403_is_a_usage_error_not_a_misleading_autherror(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        responder(monkeypatch, HttpError(403, "Forbidden"))
        with pytest.raises(UsageError) as caught:
            service.list_mcps(base_url=BASE_URL, workspace=None)
        assert "workspace" in str(caught.value)

    def test_401_is_an_auth_error(self, monkeypatch: pytest.MonkeyPatch, signed_in: None) -> None:
        responder(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError):
            service.list_mcps(base_url=BASE_URL, workspace=None)

    def test_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        responder(monkeypatch, {"nope": []})
        with pytest.raises(ApiError):
            service.list_mcps(base_url=BASE_URL, workspace=None)

    def test_not_logged_in_raises_before_any_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_not_logged_in(*, base_url: str) -> str:
            raise AuthError("You're not logged in.")

        monkeypatch.setattr(service, "get_access_token", raise_not_logged_in)

        def fail_if_called(*_a: object, **_kw: object) -> None:
            raise AssertionError("should not resolve a workspace when not logged in")

        monkeypatch.setattr(service, "resolve_workspace", fail_if_called)

        with pytest.raises(AuthError):
            service.list_mcps(base_url=BASE_URL, workspace=None)


class TestShowMcp:
    def test_maps_the_full_detail(self, monkeypatch: pytest.MonkeyPatch, signed_in: None) -> None:
        seen = responder(monkeypatch, SHOW_BODY)
        result = service.show_mcp(base_url=BASE_URL, workspace=None, slug="widgets")

        assert result == McpShowResult(
            server=McpServer(
                slug="widgets",
                name="Widgets",
                status="published",
                tool_count=5,
                collection_id="c1",
                deployment_id="acme/widgets",
                collection_name="Widgets API",
                auth_type="oauth",
                has_secret=True,
                selected_operations=("GET /widgets", "POST /widgets"),
                version="1.0.0",
                runtime_url="https://runtime.getelva.ai/mcp/widgets",
            )
        )
        assert seen == [f"{BASE_URL}/api/companies/{COMPANY}/mcps/widgets"]

    def test_no_secret_configured_is_reported_as_false_not_none(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        body = {
            "mcp": {
                **SHOW_BODY["mcp"],
                "authConfig": {"type": "api_key", "hasSecret": False},
            }
        }
        responder(monkeypatch, body)
        result = service.show_mcp(base_url=BASE_URL, workspace=None, slug="widgets")
        assert result.server.has_secret is False

    def test_never_surfaces_a_raw_secret_even_if_the_backend_forgot_to_strip_it(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Defensive: the CLI only ever reads authConfig.type/hasSecret, so
        even a backend regression that leaves a raw secret in the payload
        can't make it into the rendered result."""
        body = {
            "mcp": {
                **SHOW_BODY["mcp"],
                "authConfig": {
                    "type": "oauth",
                    "hasSecret": True,
                    "oauth": {"clientSecret": "leaked-secret"},
                },
            }
        }
        responder(monkeypatch, body)
        result = service.show_mcp(base_url=BASE_URL, workspace=None, slug="widgets")
        assert "leaked-secret" not in str(result)

    def test_404_names_the_slug_and_suggests_list(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        responder(monkeypatch, HttpError(404, None))
        with pytest.raises(UsageError) as caught:
            service.show_mcp(base_url=BASE_URL, workspace=None, slug="nope")
        assert "nope" in str(caught.value)
        assert caught.value.hint is not None
        assert "mcp list" in caught.value.hint

    def test_403_is_a_usage_error(self, monkeypatch: pytest.MonkeyPatch, signed_in: None) -> None:
        responder(monkeypatch, HttpError(403, None))
        with pytest.raises(UsageError):
            service.show_mcp(base_url=BASE_URL, workspace=None, slug="widgets")

    def test_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        responder(monkeypatch, {"nope": {}})
        with pytest.raises(ApiError):
            service.show_mcp(base_url=BASE_URL, workspace=None, slug="widgets")
