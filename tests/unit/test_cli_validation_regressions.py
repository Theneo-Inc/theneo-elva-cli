"""Regressions found by exercising the CLI against production and a real PTY."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from elva_cli import auth, main
from elva_cli.core.api import http
from elva_cli.core.api.timeout import request_timeout, use_timeout
from elva_cli.core.services import mcp_create, whoami
from elva_cli.core.services.mcp_common import runtime_url
from elva_cli.core.services.mcp_create import _create_error
from elva_cli.core.services.mcp_publish import _publish_error
from elva_cli.errors import ForbiddenError, UsageError
from elva_cli.settings.models import Settings


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999", "0", "-1"])
def test_timeout_must_be_finite_and_positive(value: str) -> None:
    with pytest.raises(ValidationError, match="finite and greater than 0"):
        Settings(timeout=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("code", [0, 2, 130])
def test_boundary_preserves_framework_return_code(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setattr(main, "app", lambda **kwargs: code)
    assert main._run() == code


def test_canonical_url_and_legacy_full_deployment_id() -> None:
    row: dict[str, Any] = {"runtimeUrl": "https://runtime.example/", "deploymentId": "acme/widgets"}
    assert runtime_url(row) == "https://runtime.example/mcp/acme/widgets"
    assert (
        runtime_url({**row, "settings": {"customSlug": "alias"}})
        == "https://runtime.example/mcp/alias"
    )
    assert (
        runtime_url({**row, "mcpUrl": "https://canonical.example/mcp/widgets"})
        == "https://canonical.example/mcp/widgets"
    )
    assert runtime_url({"runtimeUrl": "https://runtime.example", "mcpSlug": "widgets"}) is None
    assert runtime_url({**row, "status": "draft"}) is None
    assert runtime_url({**row, "mcpUrl": None}) is None


def test_older_backend_lifecycle_errors_explain_the_required_upgrade() -> None:
    for error in [
        _create_error(http.HttpError(400, '"dryRun" is not allowed')),
        _create_error(http.HttpError(400, '"draft" is not allowed')),
        _publish_error(http.HttpError(404, "Not found"), slug="qa"),
    ]:
        assert "does not support" in str(error)
        assert "administrator" in getattr(error, "hint", "")


@pytest.mark.parametrize("preview", [False, True])
def test_empty_selection_cannot_accidentally_publish_all_operations(
    monkeypatch: pytest.MonkeyPatch, preview: bool
) -> None:
    network = Mock(side_effect=AssertionError("must reject before authentication/network"))
    monkeypatch.setattr(mcp_create, "get_access_token", network)
    action = mcp_create.dry_run_mcp if preview else mcp_create.create_mcp
    with pytest.raises(UsageError, match="no operations"):
        action(
            base_url="https://api.example",
            workspace="qa",
            collection="qa",
            body={"selectedOperations": []},
        )
    network.assert_not_called()


def test_forbidden_keeps_credentials_and_does_not_suggest_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(whoami, "get_access_token", lambda **kwargs: "valid-token")
    monkeypatch.setattr(whoami, "get_json", Mock(side_effect=http.HttpError(403, None)))
    forget = Mock()
    monkeypatch.setattr(auth, "forget_stored_credentials", forget)
    with pytest.raises(ForbiddenError) as caught:
        whoami.whoami(base_url="https://api.example")
    assert caught.value.exit_code == 3
    assert caught.value.code == "ELVA_FORBIDDEN"
    assert "login" not in (caught.value.hint or "")
    forget.assert_not_called()


def test_timeout_scope_is_nested_and_restored_after_failure() -> None:
    with use_timeout(lambda: 0.25):
        assert request_timeout(30) == 0.25
        with pytest.raises(RuntimeError), use_timeout(lambda: 1):
            assert request_timeout(30) == 1
            raise RuntimeError
        assert request_timeout(30) == 0.25
    assert request_timeout(30) == 30


def test_cli_timeout_reaches_transport_and_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock()
    response.read.return_value = json.dumps({"user": {"email": "qa@example.com"}}).encode()
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(http, "_opener", lambda: opener)
    runner = CliRunner()
    for timeout in ["0.25", "1.5"]:
        result = runner.invoke(
            main.app, ["--json", "whoami"], env={"ELVA_TOKEN": "qa", "ELVA_TIMEOUT": timeout}
        )
        assert result.exit_code == 0, result.output
        assert opener.open.call_args.kwargs["timeout"] == float(timeout)
        assert request_timeout(30) == 30


def test_invalid_timeout_can_be_repaired_without_resolving_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    Path("elva.json").write_text('{"timeout": "NaN"}', encoding="utf-8")
    result = runner.invoke(main.app, ["config", "unset", "timeout"])
    assert result.exit_code == 0, result.output
