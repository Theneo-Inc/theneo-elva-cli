from __future__ import annotations

from typing import Any

import pytest

from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import mcp_publish as service
from elva_cli.core.services.mcp_create_result import McpCreateResult
from elva_cli.errors import ApiError, UsageError, ValidationError

BASE_URL = "https://api.getelva.ai"
COMPANY = Target(id="0123456789abcdef01234567", name="Theneo")


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: COMPANY)


def responder(monkeypatch: pytest.MonkeyPatch, response: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake_send(
        url: str, *, token: str, method: str, payload: dict[str, Any], **_kwargs: Any
    ) -> Any:
        seen.append({"url": url, "method": method, "payload": payload})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(service, "send_json", fake_send)
    return seen


class TestPublishMcp:
    def test_posts_to_the_slug_scoped_publish_route_and_maps_the_response(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        seen = responder(
            monkeypatch,
            {
                "deploymentId": "acme/my-api",
                "mcpSlug": "my-api",
                "apiName": "My API",
                "toolCount": 3,
                "runtimeUrl": "https://runtime.getelva.ai",
                "authConfig": {"type": "oauth", "hasSecret": True},
                "status": "published",
            },
        )
        result = service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")
        assert result == McpCreateResult(
            deployment_id="acme/my-api",
            slug="my-api",
            name="My API",
            tool_count=3,
            runtime_url="https://runtime.getelva.ai",
            auth_type="oauth",
            has_secret=True,
            status="published",
            action="publish",
            already_published=False,
        )
        assert seen == [
            {
                "url": f"{BASE_URL}/api/companies/{COMPANY.id}/mcps/my-api/publish",
                "method": "POST",
                "payload": {},
            }
        ]

    def test_slug_is_url_escaped(self, monkeypatch: pytest.MonkeyPatch, resolved: None) -> None:
        seen = responder(
            monkeypatch,
            {
                "deploymentId": "acme/weird slug",
                "mcpSlug": "weird slug",
                "apiName": "Weird",
                "toolCount": 0,
                "runtimeUrl": None,
                "authConfig": {"type": "none"},
            },
        )
        service.publish_mcp(base_url=BASE_URL, workspace=None, slug="weird slug")
        assert seen[0]["url"].endswith("/mcps/weird%20slug/publish")

    def test_already_published_is_reported_as_a_no_op(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(
            monkeypatch,
            {
                "deploymentId": "acme/my-api",
                "mcpSlug": "my-api",
                "apiName": "My API",
                "toolCount": 3,
                "runtimeUrl": "https://runtime.getelva.ai",
                "authConfig": {"type": "none"},
                "status": "published",
                "alreadyPublished": True,
            },
        )
        result = service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")
        assert result.already_published is True
        assert result.action == "publish"

    def test_400_is_a_validation_error_naming_the_reason(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        """E.g. the linked collection was deleted -- the same class of
        rejection `mcp create` maps to ValidationError (exit 4), so
        publish does too."""
        responder(monkeypatch, HttpError(400, "Collection has no spec uploaded"))
        with pytest.raises(ValidationError, match="Collection has no spec uploaded"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_400_without_detail_is_a_validation_error_with_a_generic_message(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        """A detail-less 400 must not fall back to 'no MCP server named
        X' -- that's specifically what a 404 means."""
        responder(monkeypatch, HttpError(400, None))
        with pytest.raises(ValidationError, match="rejected this publish request"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_404_is_a_usage_error_naming_the_slug(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(404, None))
        with pytest.raises(UsageError, match="my-api"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_404_mcp_not_found_is_a_usage_error_naming_the_slug(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        """resolveDeployment's own 404 when the slug itself doesn't resolve
        -- the generic 'no such server' message is the right one here."""
        responder(monkeypatch, HttpError(404, "MCP not found"))
        with pytest.raises(UsageError, match="my-api"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_404_with_a_specific_reason_surfaces_that_reason(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        """E.g. the draft's linked collection was deleted -- getCollectionById's
        404 propagates un-caught with its own message (see publishMcp's
        controller), and the AC's 'exits 2 with the reason' means that
        message must survive, not get overwritten by the generic
        no-such-server text."""
        responder(monkeypatch, HttpError(404, "Collection not found"))
        with pytest.raises(UsageError, match="Collection not found"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_402_is_a_usage_error_about_the_plan_limit(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(402, "Upgrade to create more servers"))
        with pytest.raises(UsageError, match="Upgrade"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_403_is_a_usage_error_about_editor_access_not_an_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(403, None))
        with pytest.raises(UsageError, match="editor access"):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")

    def test_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, ["not", "a", "dict"])
        with pytest.raises(ApiError):
            service.publish_mcp(base_url=BASE_URL, workspace=None, slug="my-api")
