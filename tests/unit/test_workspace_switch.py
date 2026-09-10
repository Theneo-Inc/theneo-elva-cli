from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from elva_cli.core.api.http import HttpError
from elva_cli.core.services import workspace_switch
from elva_cli.errors import ApiError, AuthError, UsageError

BASE_URL = "https://api.getelva.ai"
OID = "0123456789abcdef01234567"


def _repo(tmp_path: Path, data: dict[str, object] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    if data is not None:
        (root / "elva.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def _mock_api(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    def fake_get(url: str, *, token: str, timeout: float = 30.0) -> Any:
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(workspace_switch, "get_json", fake_get)
    monkeypatch.setattr(workspace_switch, "get_access_token", lambda *, base_url: "t")


class TestSwitchWorkspace:
    def test_by_name_writes_slug_to_project_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo", "companySlug": "theneo"}]},
        )
        root = _repo(tmp_path)
        result = workspace_switch.switch_workspace(
            base_url=BASE_URL, cwd=root, requested="Theneo", use_global=False
        )
        assert result.active_slug == "theneo"
        assert result.active_name == "Theneo"
        assert result.target_kind == "project"
        assert result.path == str(root / "elva.json")
        assert json.loads((root / "elva.json").read_text()) == {"workspace": "theneo"}

    def test_by_slug_case_insensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(
            monkeypatch,
            {"workspaces": [{"id": OID, "name": "Theneo Inc", "companySlug": "theneo"}]},
        )
        root = _repo(tmp_path)
        result = workspace_switch.switch_workspace(
            base_url=BASE_URL, cwd=root, requested="  THENEO ", use_global=False
        )
        assert result.active_slug == "theneo"
        assert result.active_name == "Theneo Inc"

    def test_id_input_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_api(monkeypatch, {"workspaces": []})
        root = _repo(tmp_path)
        with pytest.raises(UsageError, match="name or slug, not an id"):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested=OID, use_global=False
            )

    def test_unknown_name_lists_suggestions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(
            monkeypatch,
            {
                "workspaces": [
                    {"id": OID, "name": "Payments", "companySlug": "payments"},
                    {"id": "b" * 24, "name": "Platform", "companySlug": "platform"},
                ]
            },
        )
        root = _repo(tmp_path)
        with pytest.raises(UsageError) as excinfo:
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="paymnts", use_global=False
            )
        assert "no workspace named" in str(excinfo.value)
        assert "Payments" in (excinfo.value.hint or "")

    def test_ambiguous_match_reports_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(
            monkeypatch,
            {
                "workspaces": [
                    {"id": OID, "name": "Payments", "companySlug": "payments-a"},
                    {"id": "b" * 24, "name": "payments", "companySlug": "payments-b"},
                ]
            },
        )
        root = _repo(tmp_path)
        with pytest.raises(UsageError, match="more than one workspace"):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="payments", use_global=False
            )

    def test_no_workspaces_at_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_api(monkeypatch, {"workspaces": []})
        root = _repo(tmp_path)
        with pytest.raises(UsageError, match="no workspaces"):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="anything", use_global=False
            )

    def test_unexpected_shape_is_api_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(monkeypatch, {"workspaces": "nope"})
        root = _repo(tmp_path)
        with pytest.raises(ApiError):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="x", use_global=False
            )

    def test_401_becomes_auth_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_api(monkeypatch, HttpError(401, None))
        root = _repo(tmp_path)
        with pytest.raises(AuthError):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="x", use_global=False
            )

    def test_empty_requested_string(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_api(monkeypatch, {"workspaces": []})
        root = _repo(tmp_path)
        with pytest.raises(UsageError, match="workspace name is required"):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="   ", use_global=False
            )

    def test_rows_missing_slug_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_api(
            monkeypatch,
            {
                "workspaces": [
                    {"id": OID, "name": "NoSlug"},
                    {"id": "b" * 24, "name": "Theneo", "companySlug": "theneo"},
                ]
            },
        )
        root = _repo(tmp_path)
        with pytest.raises(UsageError, match="no workspace named"):
            workspace_switch.switch_workspace(
                base_url=BASE_URL, cwd=root, requested="NoSlug", use_global=False
            )
