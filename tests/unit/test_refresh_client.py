"""ELVA-200: the CLI as a first-class refresh client.

Covers the X-Elva-Client marker, proactive + forced refresh, the shared HTTP
layer's 401->refresh->retry (GET/HEAD only), transient backoff, the legacy
re-login mapping, and crash-safe token persistence.
"""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import TYPE_CHECKING, Any

import pytest

from elva_cli.auth import session
from elva_cli.auth.models import Credentials
from elva_cli.auth.session import RefreshFailedError
from elva_cli.core.api import http
from elva_cli.core.api.identity import CLIENT_HEADER
from elva_cli.errors import ApiError, AuthError, ExitCode

if TYPE_CHECKING:
    from pathlib import Path

BASE_URL = "https://api.getelva.ai"


def _tokens_body(access: str = "new-access", refresh: str = "new-refresh") -> bytes:
    later = "2099-01-01T00:00:00Z"
    return json.dumps(
        {
            "access": {"token": access, "expires": later},
            "refresh": {"token": refresh, "expires": later},
        }
    ).encode()


class _Resp:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        f"{BASE_URL}/api/auth/refresh-tokens", status, "err", Message(), io.BytesIO(body)
    )


class TestClientMarker:
    def test_refresh_sends_the_cli_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, *_a: object, **_k: object) -> _Resp:
            captured["request"] = request
            return _Resp(_tokens_body())

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        session._refresh("refresh-1", base_url=BASE_URL)

        request = captured["request"]
        assert request.get_header(CLIENT_HEADER.capitalize()) == "cli"
        assert request.get_header("User-agent", "").startswith("elva-cli/")

    def test_every_shared_http_request_carries_the_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        class _Opener:
            def open(self, request: Any, timeout: float | None = None) -> _Resp:
                captured["request"] = request
                return _Resp(b'{"ok": true}')

        monkeypatch.setattr(http, "_opener", lambda: _Opener())
        http.get_json(f"{BASE_URL}/api/auth/me", token="tok")

        assert captured["request"].get_header(CLIENT_HEADER.capitalize()) == "cli"


class TestRefreshResilience:
    def test_429_then_success_backs_off_and_recovers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def fake_urlopen(*_a: object, **_k: object) -> _Resp:
            calls["n"] += 1
            if calls["n"] < 3:
                raise _http_error(429)
            return _Resp(_tokens_body(access="recovered"))

        slept: list[float] = []
        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        creds = session._refresh("refresh-1", base_url=BASE_URL, sleep=slept.append)

        assert creds.access_token == "recovered"
        assert calls["n"] == 3
        assert slept == [1.0, 2.0]  # backed off before the two retries

    def test_persistent_5xx_gives_up_as_a_transient_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def always_503(*_a: object, **_k: object) -> None:
            raise _http_error(503)

        monkeypatch.setattr("urllib.request.urlopen", always_503)
        with pytest.raises(ApiError):
            session._refresh("refresh-1", base_url=BASE_URL, sleep=lambda _s: None)

    def test_legacy_token_is_a_terminal_refresh_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps({"code": 401, "data": "REFRESH_TOKEN_LEGACY"}).encode()

        def legacy_401(*_a: object, **_k: object) -> None:
            raise _http_error(401, body)

        monkeypatch.setattr("urllib.request.urlopen", legacy_401)
        with pytest.raises(RefreshFailedError) as caught:
            session._refresh("refresh-1", base_url=BASE_URL)
        assert "legacy" in str(caught.value)

    def test_a_dead_session_maps_to_auth_error_exit_3(self) -> None:
        # A RefreshFailedError becomes AuthError, whose exit code is AUTH (3),
        # with the "run elva auth login" hint.
        err = AuthError("Your session has expired.")
        assert err.exit_code == ExitCode.AUTH
        assert err.hint is not None and "elva auth login" in err.hint


class TestRefreshNow:
    @staticmethod
    def _install(monkeypatch: pytest.MonkeyPatch, creds: Credentials) -> None:
        monkeypatch.setattr(session, "_load_from_first_available_store", lambda: (creds, object()))

    def test_returns_a_siblings_token_without_spending_a_refresh(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: tmp_path)
        now = datetime.now(UTC)
        stored = Credentials(
            kind="session",
            access_token="already-rotated-by-sibling",
            access_expires_at=now + timedelta(minutes=10),
            refresh_token="refresh-2",
            refresh_expires_at=now + timedelta(days=1),
        )
        self._install(monkeypatch, stored)

        def forbidden(*_a: object, **_k: object) -> Credentials:
            raise AssertionError("must not spend a refresh when a sibling already rotated")

        monkeypatch.setattr(session, "_refresh", forbidden)

        token = session.refresh_now(base_url=BASE_URL, stale_access_token="the-stale-one")
        assert token == "already-rotated-by-sibling"

    def test_forces_a_refresh_when_the_stale_token_is_still_current(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: tmp_path)
        now = datetime.now(UTC)
        stored = Credentials(
            kind="session",
            access_token="stale",
            # Not near expiry, so the ordinary near-expiry path wouldn't refresh;
            # a 401 forces it anyway.
            access_expires_at=now + timedelta(minutes=10),
            refresh_token="refresh-3",
            refresh_expires_at=now + timedelta(days=1),
        )
        self._install(monkeypatch, stored)
        monkeypatch.setattr(session, "_persist_refreshed", lambda _c: None)
        monkeypatch.setattr(
            session,
            "_refresh",
            lambda token, *, base_url: Credentials(
                kind="session",
                access_token="forced-new",
                access_expires_at=now + timedelta(minutes=15),
                refresh_token="refresh-4",
                refresh_expires_at=now + timedelta(days=1),
            ),
        )
        assert session.refresh_now(base_url=BASE_URL, stale_access_token="stale") == "forced-new"


class TestHttpRetry:
    @staticmethod
    def _opener(monkeypatch: pytest.MonkeyPatch, sequence: list[Any]) -> dict[str, list[str]]:
        seen: dict[str, list[str]] = {"tokens": []}

        class _Opener:
            def open(self, request: Any, timeout: float | None = None) -> _Resp:
                seen["tokens"].append(request.get_header("Authorization"))
                outcome = sequence.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return _Resp(outcome)

        monkeypatch.setattr(http, "_opener", lambda: _Opener())
        return seen

    def test_get_refreshes_and_retries_once_on_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._opener(
            monkeypatch,
            [_http_error(401), b'{"ok": true}'],  # first 401, retry succeeds
        )
        refreshed: list[str] = []

        def reauth(stale: str) -> str:
            refreshed.append(stale)
            return "fresh-token"

        body = http.get_json(f"{BASE_URL}/api/auth/me", token="stale-token", reauth=reauth)

        assert body == {"ok": True}
        assert refreshed == ["stale-token"]  # reauth was handed the stale token
        assert seen["tokens"] == ["Bearer stale-token", "Bearer fresh-token"]

    def test_post_is_not_retried_after_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._opener(monkeypatch, [_http_error(401)])
        called = {"reauth": False}

        def reauth(_stale: str) -> str:
            called["reauth"] = True
            return "fresh"

        with pytest.raises(http.HttpError):
            http.send_json(
                f"{BASE_URL}/api/x", token="tok", method="POST", payload={}, reauth=reauth
            )
        assert called["reauth"] is False  # non-idempotent: never auto-replayed


class TestCrashSafePersist:
    def test_a_failed_write_leaves_the_old_credentials_intact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: tmp_path)
        from elva_cli.auth.store import FileStore

        store = FileStore()
        old = Credentials.from_pat("old-token")
        store.save(old)

        # Simulate a crash after the temp file is written but before the rename.
        import pathlib

        def boom(self: pathlib.Path, target: Any) -> None:
            raise OSError("crash before rename")

        monkeypatch.setattr(pathlib.Path, "replace", boom)

        new = Credentials.from_pat("new-token")
        with pytest.raises(OSError, match="crash before rename"):
            store.save(new)

        # The old file is still there and readable; no partial/temp file leaks.
        assert store.load() == old
        leftovers = list(tmp_path.glob("credentials.json.*.tmp"))
        assert leftovers == []
