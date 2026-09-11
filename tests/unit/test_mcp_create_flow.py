from __future__ import annotations

import json
from typing import Any

import pytest

from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import mcp_create as service
from elva_cli.core.services.mcp_create_result import (
    McpCreateResult,
    McpDryRunResult,
    OperationOutcome,
)
from elva_cli.errors import ApiError, UsageError, ValidationError

BASE_URL = "https://api.getelva.ai"
COMPANY = Target(id="0123456789abcdef01234567", name="Theneo")
COLLECTION = Target(id="fedcba9876543210fedcba98", name="Petstore")


class TestBuildBodyFromFlags:
    def test_minimal_body_is_just_the_name_and_auth_type(self) -> None:
        body = service.build_body_from_flags(
            name="My API",
            operations=None,
            auth_type="none",
            api_key_header=None,
            api_key_in=None,
            base_url=None,
            timeout=None,
        )
        assert body == {"mcpName": "My API", "authConfig": {"type": "none"}}

    def test_explicit_empty_operations_is_sent_as_an_empty_list(self) -> None:
        """Distinct from operations=None (the flag omitted entirely): an
        explicit empty selection must reach the server as `[]`, not be
        dropped and default to "include everything"."""
        body = service.build_body_from_flags(
            name="My API",
            operations=(),
            auth_type="none",
            api_key_header=None,
            api_key_in=None,
            base_url=None,
            timeout=None,
        )
        assert body["selectedOperations"] == []

    def test_operations_and_base_url_and_timeout_are_included_when_given(self) -> None:
        body = service.build_body_from_flags(
            name="My API",
            operations=("GET /pets", "POST /pets"),
            auth_type="none",
            api_key_header=None,
            api_key_in=None,
            base_url="https://api.example.com",
            timeout=5000,
        )
        assert body["selectedOperations"] == ["GET /pets", "POST /pets"]
        assert body["baseUrl"] == "https://api.example.com"
        assert body["timeout"] == 5000

    def test_api_key_placement_flows_into_auth_config(self) -> None:
        body = service.build_body_from_flags(
            name="My API",
            operations=(),
            auth_type="api_key",
            api_key_header="X-Api-Key",
            api_key_in="header",
            base_url=None,
            timeout=None,
        )
        assert body["authConfig"] == {
            "type": "api_key",
            "apiKeyHeaderName": "X-Api-Key",
            "apiKeyIn": "header",
        }

    def test_blank_name_is_rejected(self) -> None:
        with pytest.raises(UsageError, match="blank"):
            service.build_body_from_flags(
                name="   ",
                operations=(),
                auth_type="none",
                api_key_header=None,
                api_key_in=None,
                base_url=None,
                timeout=None,
            )

    def test_name_over_100_chars_is_rejected_naming_the_limit(self) -> None:
        with pytest.raises(UsageError, match="the limit is 100"):
            service.build_body_from_flags(
                name="x" * 101,
                operations=(),
                auth_type="none",
                api_key_header=None,
                api_key_in=None,
                base_url=None,
                timeout=None,
            )

    def test_over_5000_operations_is_rejected_naming_the_limit(self) -> None:
        with pytest.raises(UsageError, match="the limit is 5000"):
            service.build_body_from_flags(
                name="My API",
                operations=tuple(f"GET /p{i}" for i in range(5001)),
                auth_type="none",
                api_key_header=None,
                api_key_in=None,
                base_url=None,
                timeout=None,
            )

    def test_timeout_outside_the_server_range_is_rejected(self) -> None:
        with pytest.raises(UsageError, match="1000 and 300000"):
            service.build_body_from_flags(
                name="My API",
                operations=(),
                auth_type="none",
                api_key_header=None,
                api_key_in=None,
                base_url=None,
                timeout=500,
            )

    def test_an_unsupported_auth_type_is_rejected(self) -> None:
        with pytest.raises(UsageError, match="not a valid value for --auth-type"):
            service.build_body_from_flags(
                name="My API",
                operations=(),
                auth_type="oauth",
                api_key_header=None,
                api_key_in=None,
                base_url=None,
                timeout=None,
            )

    def test_api_key_flags_are_rejected_for_a_different_auth_type(self) -> None:
        with pytest.raises(UsageError, match="--auth-type api_key"):
            service.build_body_from_flags(
                name="My API",
                operations=(),
                auth_type="bearer",
                api_key_header="X-Api-Key",
                api_key_in=None,
                base_url=None,
                timeout=None,
            )

    def test_an_unsupported_api_key_placement_is_rejected(self) -> None:
        with pytest.raises(UsageError, match="not a valid value for --api-key-in"):
            service.build_body_from_flags(
                name="My API",
                operations=(),
                auth_type="api_key",
                api_key_header=None,
                api_key_in="cookie",
                base_url=None,
                timeout=None,
            )


class TestBuildBodyFromFile:
    def test_valid_file_is_returned_as_is(self, tmp_path: Any) -> None:
        payload = {"mcpName": "My API", "authConfig": {"type": "oauth", "oauth": {}}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload))

        body = service.build_body_from_file(path)
        assert body == payload

    def test_missing_file_is_a_usage_error(self, tmp_path: Any) -> None:
        with pytest.raises(UsageError, match="no such file"):
            service.build_body_from_file(tmp_path / "nope.json")

    def test_malformed_json_is_a_usage_error(self, tmp_path: Any) -> None:
        path = tmp_path / "config.json"
        path.write_text("{ not json")
        with pytest.raises(UsageError, match="not valid JSON"):
            service.build_body_from_file(path)

    def test_a_json_array_is_rejected(self, tmp_path: Any) -> None:
        path = tmp_path / "config.json"
        path.write_text("[]")
        with pytest.raises(UsageError, match="JSON object"):
            service.build_body_from_file(path)

    def test_missing_mcp_name_is_rejected(self, tmp_path: Any) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"authConfig": {"type": "none"}}))
        with pytest.raises(UsageError, match="mcpName"):
            service.build_body_from_file(path)

    def test_over_limit_filter_array_is_rejected_naming_the_field_and_limit(
        self, tmp_path: Any
    ) -> None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"mcpName": "x", "includeTags": [f"t{i}" for i in range(101)]}))
        with pytest.raises(UsageError, match=r"includeTags.*the limit is 100"):
            service.build_body_from_file(path)

    def test_embedded_oauth_client_secret_is_rejected(self, tmp_path: Any) -> None:
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "mcpName": "x",
                    "authConfig": {"type": "oauth", "oauth": {"clientSecret": "leaked"}},
                }
            )
        )
        with pytest.raises(UsageError, match="embeds authConfig"):
            service.build_body_from_file(path)

    def test_embedded_oidc_client_secret_is_rejected(self, tmp_path: Any) -> None:
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(
                {
                    "mcpName": "x",
                    "authConfig": {"type": "openid_connect", "oidcClientSecret": "leaked"},
                }
            )
        )
        with pytest.raises(UsageError, match="embeds authConfig"):
            service.build_body_from_file(path)


class TestMergeSecret:
    def test_oauth_secret_merges_into_the_nested_oauth_object(self) -> None:
        body: dict[str, Any] = {
            "mcpName": "x",
            "authConfig": {"type": "oauth", "oauth": {"tokenUrl": "https://t"}},
        }
        merged = service.merge_secret(body, "shh")
        assert merged["authConfig"]["oauth"]["clientSecret"] == "shh"
        assert merged["authConfig"]["oauth"]["tokenUrl"] == "https://t"
        # original is untouched
        assert "clientSecret" not in body["authConfig"]["oauth"]

    def test_openid_connect_secret_merges_at_the_top_level(self) -> None:
        body = {"mcpName": "x", "authConfig": {"type": "openid_connect"}}
        merged = service.merge_secret(body, "shh")
        assert merged["authConfig"]["oidcClientSecret"] == "shh"

    def test_rejected_for_auth_types_with_no_secret_slot(self) -> None:
        for auth_type in ("none", "basic", "bearer", "jwt", "api_key"):
            body = {"mcpName": "x", "authConfig": {"type": auth_type}}
            with pytest.raises(UsageError, match="oauth or openid_connect"):
                service.merge_secret(body, "shh")

    def test_oauth_without_an_oauth_object_is_rejected(self) -> None:
        body = {"mcpName": "x", "authConfig": {"type": "oauth"}}
        with pytest.raises(UsageError, match=r"authConfig\.oauth"):
            service.merge_secret(body, "shh")


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: COMPANY)
    monkeypatch.setattr(service, "resolve_collection", lambda **_: COLLECTION)


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


class TestCreateMcp:
    def test_posts_to_the_collection_scoped_route_and_maps_the_response(
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
            },
        )
        result = service.create_mcp(
            base_url=BASE_URL, workspace=None, collection="Petstore", body={"mcpName": "My API"}
        )
        assert result == McpCreateResult(
            deployment_id="acme/my-api",
            slug="my-api",
            name="My API",
            tool_count=3,
            runtime_url="https://runtime.getelva.ai",
            auth_type="oauth",
            has_secret=True,
        )
        assert seen == [
            {
                "url": f"{BASE_URL}/api/companies/{COMPANY.id}/collections/{COLLECTION.id}/mcps",
                "method": "POST",
                "payload": {"mcpName": "My API"},
            }
        ]

    def test_400_is_a_validation_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(400, "mcpName is required"))
        with pytest.raises(ValidationError, match="mcpName is required"):
            service.create_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})

    def test_402_is_a_usage_error_about_the_plan_limit(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(402, "Upgrade to create more servers"))
        with pytest.raises(UsageError, match="Upgrade"):
            service.create_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})

    def test_403_is_a_usage_error_about_editor_access_not_an_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(403, None))
        with pytest.raises(UsageError, match="editor access"):
            service.create_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})

    def test_409_is_a_usage_error_about_a_conflict(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, HttpError(409, "This collection already has an MCP deployment"))
        with pytest.raises(UsageError, match="already has an MCP deployment"):
            service.create_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})

    def test_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, ["not", "a", "dict"])
        with pytest.raises(ApiError):
            service.create_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})


class TestDryRunMcp:
    def test_sends_dry_run_true_and_maps_the_operations(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        seen = responder(
            monkeypatch,
            {
                "toolCount": 1,
                "operations": [
                    {
                        "operationKey": "GET /pets",
                        "method": "GET",
                        "path": "/pets",
                        "included": True,
                    },
                    {
                        "operationKey": "DELETE /pets",
                        "method": "DELETE",
                        "path": "/pets",
                        "included": False,
                        "reason": "not in selectedOperations",
                    },
                ],
            },
        )
        result = service.dry_run_mcp(
            base_url=BASE_URL, workspace=None, collection="Petstore", body={"mcpName": "x"}
        )
        assert result == McpDryRunResult(
            tool_count=1,
            operations=(
                OperationOutcome(
                    operation_key="GET /pets", method="GET", path="/pets", included=True
                ),
                OperationOutcome(
                    operation_key="DELETE /pets",
                    method="DELETE",
                    path="/pets",
                    included=False,
                    reason="not in selectedOperations",
                ),
            ),
        )
        assert seen[0]["payload"]["dryRun"] is True
        assert seen[0]["payload"]["mcpName"] == "x"

    def test_no_operations_key_in_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        responder(monkeypatch, {"toolCount": 0})
        with pytest.raises(ApiError):
            service.dry_run_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})

    def test_a_collection_with_no_spec_uploaded_is_a_validation_error(
        self, monkeypatch: pytest.MonkeyPatch, resolved: None
    ) -> None:
        """The '400 not 500/1' acceptance criterion, on the dry-run path too --
        dry-run hits the same spec-exists check a real create would."""
        responder(monkeypatch, HttpError(400, "Collection has no spec uploaded"))
        with pytest.raises(ValidationError, match="Collection has no spec uploaded"):
            service.dry_run_mcp(base_url=BASE_URL, workspace=None, collection="Petstore", body={})
