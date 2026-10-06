from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from elva_cli.auth import session
from elva_cli.auth.models import Credentials
from elva_cli.auth.store import StoreUnavailableError
from elva_cli.core.services import email_auth as service
from elva_cli.errors import ApiError, AuthError, UsageError

BASE = "https://api.getelva.ai"
EMAIL = "cli-qa@example.com"


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setattr(service, "config_dir", lambda: tmp_path)
    calls: list[tuple[str, dict[str, Any]]] = []
    saved: list[dict[str, Any]] = []
    state: dict[str, Any] = {"calls": calls, "saved": saved, "directory": tmp_path}

    def request(_base: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((endpoint, payload))
        sid = payload["sessionId"]
        return {"status": "pending_verification", "sessionId": sid, "email": EMAIL}

    monkeypatch.setattr(service, "_request", request)
    monkeypatch.setattr(service, "save_login", lambda payload, **_kw: saved.append(payload))
    state["result"] = service.start_signup(base_url=BASE, email=EMAIL)
    state["path"] = next((tmp_path / "auth-sessions").glob("*.json"))
    state["data"] = json.loads(state["path"].read_text())
    return state


def authenticated(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "authenticated",
        "sessionId": flow["data"]["sessionId"],
        "user": {"email": EMAIL},
        "workspace": {"id": "workspace1"},
        "tokens": {},
    }


def test_only_email_and_client_proof_are_sent(flow: dict[str, Any]) -> None:
    endpoint, body = flow["calls"][0]
    assert endpoint == "start"
    assert set(body) == {"email", "sessionId", "codeChallenge"}
    assert body["codeChallenge"] != flow["data"]["verifier"]
    assert flow["path"].stat().st_mode & 0o777 == 0o600
    assert flow["path"].parent.stat().st_mode & 0o777 == 0o700
    assert flow["data"]["verifier"] not in json.dumps(asdict(flow["result"]))


def test_repeat_start_reuses_private_proof(flow: dict[str, Any]) -> None:
    service.start_signup(base_url=BASE, email=" CLI-QA@example.com ")
    assert flow["calls"][0] == flow["calls"][1]


def test_restart_uses_new_session(flow: dict[str, Any]) -> None:
    result = service.start_signup(base_url=BASE, email=EMAIL, restart=True)
    assert result.session_id != flow["result"].session_id


def test_unrelated_origins_and_corrupt_files_do_not_block_resume(flow: dict[str, Any]) -> None:
    root = flow["path"].parent
    unrelated = {**flow["data"], "apiOrigin": "https://other.invalid", "sessionId": "a" * 36}
    (root / "000-other.json").write_text(json.dumps(unrelated))
    (root / "001-corrupt.json").write_text("{bad")
    result = service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"])
    assert result.status == "pending_verification"


def test_selected_origin_mismatch_never_sends_proof(flow: dict[str, Any]) -> None:
    with pytest.raises(UsageError, match="another API server"):
        service.finish_signup(
            base_url="https://other.invalid", session_id=flow["data"]["sessionId"]
        )
    assert len(flow["calls"]) == 1


@pytest.mark.parametrize(
    "email", ["", "bad", "user@example", "a b@example.com", "x" * 250 + "@x.io"]
)
def test_invalid_email_is_offline(flow: dict[str, Any], email: str) -> None:
    with pytest.raises(UsageError):
        service.start_signup(base_url=BASE, email=email)
    assert len(flow["calls"]) == 1


@pytest.mark.parametrize("code", ["123", "123456789", "12ab5678", ""])
def test_invalid_code_is_offline(flow: dict[str, Any], code: str) -> None:
    with pytest.raises(UsageError):
        service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"], code=code)
    assert len(flow["calls"]) == 1


def test_lost_start_keeps_proof(flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any) -> Any:
        raise ApiError("network unavailable")

    monkeypatch.setattr(service, "_request", fail)
    with pytest.raises(ApiError):
        service.start_signup(base_url=BASE, email=EMAIL)
    assert json.loads(flow["path"].read_text()) == flow["data"]


def test_save_failure_never_acknowledges(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoints: list[str] = []

    def request(_base: str, endpoint: str, _payload: Any) -> Any:
        endpoints.append(endpoint)
        return authenticated(flow)

    def save(*_args: Any, **_kw: Any) -> Any:
        raise StoreUnavailableError("unavailable")

    monkeypatch.setattr(service, "_request", request)
    monkeypatch.setattr(service, "save_login", save)
    with pytest.raises(AuthError, match="could not be saved"):
        service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"], code="12345678")
    assert endpoints == ["verify"] and flow["path"].exists()


def test_success_saves_before_ack_and_returns_local_artifact(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = flow["directory"] / "api input.json"
    artifact.write_text("{}")
    data = {
        **flow["data"],
        "artifactFile": str(artifact),
        "artifactHash": hashlib.sha256(b"{}").hexdigest(),
    }
    flow["path"].write_text(json.dumps(data))

    def request(_base: str, endpoint: str, _payload: Any) -> Any:
        if endpoint == "ack":
            assert flow["saved"]
            return {"status": "completed", "sessionId": data["sessionId"]}
        return authenticated(flow)

    monkeypatch.setattr(service, "_request", request)
    result = service.finish_signup(base_url=BASE, session_id=data["sessionId"], code="12345678")
    assert result.status == "authenticated" and result.workspace_id == "workspace1"
    assert result.next_action == "elva --yes --json agent create --from '" + str(artifact) + "'"
    assert not flow["path"].exists()
    assert not any(
        word in json.dumps(asdict(result)) for word in ("12345678", data["verifier"], "tokens")
    )


def test_uncertain_ack_is_terminal_on_retry(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def request(_base: str, endpoint: str, _payload: Any) -> Any:
        if endpoint == "ack":
            raise ApiError("lost response")
        return authenticated(flow)

    monkeypatch.setattr(service, "_request", request)
    result = service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"])
    assert result.status == "authenticated" and flow["path"].exists()
    monkeypatch.setattr(
        service,
        "_request",
        lambda *_args: {"status": "completed", "sessionId": flow["data"]["sessionId"]},
    )

    def token(**kwargs: Any) -> str:
        assert kwargs == {"base_url": BASE, "use_env": False}
        return "stored-token"

    monkeypatch.setattr(service, "get_access_token", token)
    monkeypatch.setattr(service, "get_json", lambda *_a, **_k: {"user": {"email": EMAIL}})
    result = service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"])
    assert result.status == "authenticated" and not flow["path"].exists()
    assert result.next_action == "elva --json whoami"


def test_completed_different_identity_does_not_claim_success(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service,
        "_request",
        lambda *_a: {"status": "completed", "sessionId": flow["data"]["sessionId"]},
    )
    monkeypatch.setattr(service, "get_access_token", lambda **_kw: "stored-token")
    monkeypatch.setattr(
        service, "get_json", lambda *_a, **_kw: {"user": {"email": "different@example.com"}}
    )
    with pytest.raises(AuthError, match="Sign in again"):
        service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"])
    assert flow["path"].exists()


@pytest.mark.parametrize("mutation", [{"user": None}, {"workspace": None}, {"sessionId": "wrong"}])
def test_malformed_authenticated_response_is_not_saved(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch, mutation: dict[str, Any]
) -> None:
    monkeypatch.setattr(service, "_request", lambda *_a: {**authenticated(flow), **mutation})
    with pytest.raises(ApiError):
        service.finish_signup(base_url=BASE, session_id=flow["data"]["sessionId"])
    assert not flow["saved"] and flow["path"].exists()


@pytest.mark.parametrize("operation", ["read", "refresh", "force_refresh", "revoke", "logout"])
def test_all_credential_paths_reject_another_origin(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    now = datetime.now(UTC)
    creds = Credentials(
        "session", "access", now + timedelta(hours=1), "refresh", now + timedelta(days=1), BASE
    )
    creds = Credentials.from_json(creds.to_json())
    monkeypatch.delenv("ELVA_TOKEN", raising=False)
    monkeypatch.setattr(session, "_load_from_first_available_store", lambda: (creds, object()))

    def fail(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("must not send or delete another origin credentials")

    monkeypatch.setattr(session, "_refresh", fail)
    monkeypatch.setattr(session, "_clear_all_stores", fail)
    other = "https://other.invalid"
    with pytest.raises(AuthError, match="another Elva API server"):
        if operation == "read":
            session.get_access_token(base_url=other)
        elif operation == "refresh":
            session._refresh_session(base_url=other)
        elif operation == "force_refresh":
            session.refresh_now(base_url=other, stale_access_token="different")
        elif operation == "revoke":
            session._revocation_token(creds, base_url=other)
        else:
            session.logout(base_url=other)


def test_refresh_parse_keeps_origin() -> None:
    expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    body = json.dumps(
        {"access": {"token": "a", "expires": expiry}, "refresh": {"token": "r", "expires": expiry}}
    ).encode()
    assert session._parse_refresh_body(body, base_url=BASE).api_origin == BASE


def test_environment_token_prevents_misleading_continuation(
    flow: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELVA_TOKEN", "never-echo-me")
    result = service._finished(flow["data"], authenticated(flow), "Signed in.")
    assert result.next_action is None
    assert result.message is not None
    assert "Unset ELVA_TOKEN" in result.message
    assert "never-echo-me" not in json.dumps(asdict(result))
