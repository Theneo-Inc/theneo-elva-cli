from __future__ import annotations

import contextlib
import json
import threading
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

from elva_cli.auth import session
from elva_cli.auth.models import Credentials
from elva_cli.auth.session import RefreshFailedError
from elva_cli.auth.store import StoreUnavailableError
from elva_cli.errors import ApiError, AuthError, ExitCode

BASE_URL = "https://api.getelva.ai"


@pytest.fixture(autouse=True)
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep the refresh lock file — and any real store writes — inside tmp."""
    directory = tmp_path / "config"
    monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: directory)
    return directory


class FakeStore:
    def __init__(self, creds: Credentials | None = None) -> None:
        self._creds = creds
        self.saved: list[Credentials] = []
        self.cleared = False

    def load(self) -> Credentials | None:
        return self._creds

    def save(self, creds: Credentials) -> None:
        self.saved.append(creds)
        self._creds = creds

    def clear(self) -> None:
        self.cleared = True
        self._creds = None


def _session_creds(
    *, access_in: timedelta, refresh_in: timedelta, access_token: str = "access-1"
) -> Credentials:
    now = datetime.now(UTC)
    return Credentials(
        kind="session",
        access_token=access_token,
        access_expires_at=now + access_in,
        refresh_token="refresh-1",
        refresh_expires_at=now + refresh_in,
    )


def _patch_stores(monkeypatch: pytest.MonkeyPatch, stores: list[FakeStore]) -> None:
    monkeypatch.setattr(session, "_stores", lambda: stores)


def _forbid_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> Credentials:
        raise AssertionError("_refresh must not be called")

    monkeypatch.setattr(session, "_refresh", fail)


def _raise_http_error(status: int) -> Callable[..., None]:
    def fake_urlopen(*_a: object, **_kw: object) -> None:
        raise urllib.error.HTTPError(
            "https://api.getelva.ai/api/auth/refresh-tokens", status, "err", Message(), None
        )

    return fake_urlopen


class TestPrecedence:
    def test_elva_token_env_var_bypasses_both_stores(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ELVA_TOKEN", "ci-token")

        def fail(*_args: object, **_kwargs: object) -> tuple[Credentials | None, object]:
            raise AssertionError("stores must not be consulted when ELVA_TOKEN is set")

        monkeypatch.setattr(session, "_load_from_first_available_store", fail)
        assert session.get_access_token(base_url=BASE_URL) == "ci-token"

    def test_falls_through_to_second_store_when_first_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        first = FakeStore(creds=None)
        second = FakeStore(creds=Credentials.from_pat("pat-from-second"))
        _patch_stores(monkeypatch, [first, second])

        assert session.get_access_token(base_url=BASE_URL) == "pat-from-second"

    def test_not_logged_in_raises_autherror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        _patch_stores(monkeypatch, [FakeStore(), FakeStore()])

        with pytest.raises(AuthError) as exc_info:
            session.get_access_token(base_url=BASE_URL)
        assert exc_info.value.exit_code == ExitCode.AUTH
        assert "elva auth login" in (exc_info.value.hint or "")


class TestPatCredentials:
    def test_pat_returned_as_is_no_refresh_attempted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        store = FakeStore(creds=Credentials.from_pat("elva_pat_xyz"))
        _patch_stores(monkeypatch, [store])
        _forbid_refresh(monkeypatch)

        assert session.get_access_token(base_url=BASE_URL) == "elva_pat_xyz"
        assert store.saved == []


class TestSessionRefresh:
    def test_fresh_token_returned_without_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        creds = _session_creds(access_in=timedelta(hours=1), refresh_in=timedelta(days=7))
        store = FakeStore(creds=creds)
        _patch_stores(monkeypatch, [store])
        _forbid_refresh(monkeypatch)

        assert session.get_access_token(base_url=BASE_URL) == creds.access_token
        assert store.saved == []

    def test_near_expiry_token_refreshes_and_is_persisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        stale = _session_creds(access_in=timedelta(seconds=10), refresh_in=timedelta(days=7))
        _patch_stores(monkeypatch, [FakeStore(creds=stale)])

        fresh = _session_creds(
            access_in=timedelta(hours=1), refresh_in=timedelta(days=7), access_token="access-2"
        )
        monkeypatch.setattr(session, "_refresh", lambda *_a, **_kw: fresh)

        saved: list[Credentials] = []
        monkeypatch.setattr(session, "_save_preferring_keyring", saved.append)

        assert session.get_access_token(base_url=BASE_URL) == "access-2"
        assert saved == [fresh]  # persisted via the same both-stores path as login

    def test_expired_refresh_token_raises_without_any_http_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        dead = _session_creds(access_in=timedelta(seconds=-10), refresh_in=timedelta(seconds=-1))
        store = FakeStore(creds=dead)
        _patch_stores(monkeypatch, [store])
        _forbid_refresh(monkeypatch)

        with pytest.raises(AuthError) as exc_info:
            session.get_access_token(base_url=BASE_URL)
        assert exc_info.value.exit_code == ExitCode.AUTH
        assert store.cleared

    def test_refresh_call_rejected_clears_stores_and_raises_autherror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        stale = _session_creds(access_in=timedelta(seconds=10), refresh_in=timedelta(days=7))
        store = FakeStore(creds=stale)
        _patch_stores(monkeypatch, [store])

        def raise_refresh_failed(*_a: object, **_kw: object) -> Credentials:
            raise RefreshFailedError("401")

        monkeypatch.setattr(session, "_refresh", raise_refresh_failed)

        with pytest.raises(AuthError) as exc_info:
            session.get_access_token(base_url=BASE_URL)
        assert exc_info.value.exit_code == ExitCode.AUTH
        assert store.cleared

    def test_transient_refresh_failure_keeps_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        # Access token already expired -> no skew-window fallback possible.
        stale = _session_creds(access_in=timedelta(seconds=-5), refresh_in=timedelta(days=7))
        store = FakeStore(creds=stale)
        _patch_stores(monkeypatch, [store])

        def raise_api_error(*_a: object, **_kw: object) -> Credentials:
            raise ApiError("Could not reach the server to refresh your session.")

        monkeypatch.setattr(session, "_refresh", raise_api_error)

        with pytest.raises(ApiError) as exc_info:
            session.get_access_token(base_url=BASE_URL)
        assert exc_info.value.exit_code == ExitCode.API
        assert not store.cleared

    def test_transient_refresh_failure_within_skew_uses_current_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        # Inside the skew window but not actually expired yet.
        creds = _session_creds(access_in=timedelta(seconds=30), refresh_in=timedelta(days=7))
        store = FakeStore(creds=creds)
        _patch_stores(monkeypatch, [store])

        def raise_api_error(*_a: object, **_kw: object) -> Credentials:
            raise ApiError("offline")

        monkeypatch.setattr(session, "_refresh", raise_api_error)

        assert session.get_access_token(base_url=BASE_URL) == creds.access_token
        assert not store.cleared

    def test_corrupt_session_credential_reports_not_logged_in(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        corrupt = Credentials(
            kind="session",
            access_token="a",
            access_expires_at=None,
            refresh_token=None,
            refresh_expires_at=None,
        )
        _patch_stores(monkeypatch, [FakeStore(creds=corrupt)])
        _forbid_refresh(monkeypatch)

        with pytest.raises(AuthError) as exc_info:
            session.get_access_token(base_url=BASE_URL)
        assert exc_info.value.exit_code == ExitCode.AUTH


class TestConcurrentRefresh:
    def test_waiter_returns_the_token_the_lock_holder_saved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        stale = _session_creds(access_in=timedelta(seconds=10), refresh_in=timedelta(days=7))
        store = FakeStore(creds=stale)
        _patch_stores(monkeypatch, [store])
        _forbid_refresh(monkeypatch)

        fresh = _session_creds(
            access_in=timedelta(hours=1), refresh_in=timedelta(days=7), access_token="winner-access"
        )

        @contextlib.contextmanager
        def another_process_held_it_first() -> Iterator[None]:
            store._creds = fresh  # the process that had the lock refreshed and saved
            yield

        monkeypatch.setattr(session, "_refresh_lock", another_process_held_it_first)

        assert session.get_access_token(base_url=BASE_URL) == "winner-access"
        assert store.saved == []  # we made no network call, so nothing to persist

    def test_lock_serialises_racing_threads_so_the_refresh_token_is_spent_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        stale = _session_creds(access_in=timedelta(seconds=10), refresh_in=timedelta(days=7))
        store = FakeStore(creds=stale)
        _patch_stores(monkeypatch, [store])

        spent: list[str] = []
        spent_lock = threading.Lock()
        start = threading.Barrier(2)

        def single_use_refresh(token: str, *, base_url: str) -> Credentials:
            with spent_lock:
                spent.append(token)
            if token != "refresh-1":
                raise RefreshFailedError("refresh token already consumed")
            return _session_creds(
                access_in=timedelta(hours=1),
                refresh_in=timedelta(days=7),
                access_token="access-2",
            )

        monkeypatch.setattr(session, "_refresh", single_use_refresh)

        def persist(creds: Credentials) -> None:
            store._creds = creds  # what a real _save_preferring_keyring would land

        monkeypatch.setattr(session, "_save_preferring_keyring", persist)

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            start.wait()
            try:
                results.append(session.get_access_token(base_url=BASE_URL))
            except Exception as exc:  # surface any failure to the test body
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert results == ["access-2", "access-2"]
        assert spent == ["refresh-1"]  # the waiter re-read the store and skipped the network

    def test_refresh_still_proceeds_when_the_filesystem_has_no_locks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import fcntl

        def no_locks(*_args: object) -> None:
            raise OSError("no locks available on this filesystem")

        monkeypatch.setattr(fcntl, "flock", no_locks)

        ran = False
        with session._refresh_lock():
            ran = True
        assert ran

    def test_lock_is_released_so_a_second_acquisition_does_not_deadlock(
        self, config_dir: Path
    ) -> None:
        with session._refresh_lock():
            pass
        with session._refresh_lock():
            pass
        assert (config_dir / "refresh.lock").exists()


class TestRefreshPersistence:
    @pytest.fixture(autouse=True)
    def _no_real_store_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("elva_cli.auth.session.KeyringStore.clear", lambda self: None)
        monkeypatch.setattr("elva_cli.auth.session.FileStore.clear", lambda self: None)

    def _stale_then_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ELVA_TOKEN", raising=False)
        stale = _session_creds(access_in=timedelta(seconds=10), refresh_in=timedelta(days=7))
        _patch_stores(monkeypatch, [FakeStore(creds=stale)])
        fresh = _session_creds(
            access_in=timedelta(hours=1), refresh_in=timedelta(days=7), access_token="access-2"
        )
        monkeypatch.setattr(session, "_refresh", lambda *_a, **_kw: fresh)

    def test_falls_back_to_file_when_the_keyring_save_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stale_then_refresh(monkeypatch)

        def keyring_unavailable(self: object, creds: Credentials) -> None:
            raise StoreUnavailableError("no backend")

        file_saved: list[Credentials] = []
        monkeypatch.setattr("elva_cli.auth.session.KeyringStore.save", keyring_unavailable)
        monkeypatch.setattr(
            "elva_cli.auth.session.FileStore.save", lambda self, creds: file_saved.append(creds)
        )

        assert session.get_access_token(base_url=BASE_URL) == "access-2"
        assert [c.access_token for c in file_saved] == ["access-2"]

    def test_warns_but_still_returns_the_token_when_no_store_can_save(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._stale_then_refresh(monkeypatch)

        def boom(_creds: Credentials) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr(session, "_save_preferring_keyring", boom)

        with caplog.at_level("WARNING", logger="elva_cli.auth.session"):
            token = session.get_access_token(base_url=BASE_URL)
        assert token == "access-2"  # the current call still works
        assert "elva auth login" in caplog.text


class TestSaveAndLogout:
    @pytest.fixture(autouse=True)
    def _no_real_store_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _save_preferring_keyring clears the store it isn't using; keep that
        # off the real keyring / real config dir during these tests.
        monkeypatch.setattr("elva_cli.auth.session.KeyringStore.clear", lambda self: None)
        monkeypatch.setattr("elva_cli.auth.session.FileStore.clear", lambda self: None)

    def test_save_login_prefers_keyring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        keyring_saved = []
        file_saved = []
        monkeypatch.setattr(
            "elva_cli.auth.session.KeyringStore.save",
            lambda self, creds: keyring_saved.append(creds),
        )
        monkeypatch.setattr(
            "elva_cli.auth.session.FileStore.save", lambda self, creds: file_saved.append(creds)
        )

        payload = {
            "user": {"id": "u1"},
            "tokens": {
                "access": {"token": "a", "expires": "2026-01-01T00:00:00+00:00"},
                "refresh": {"token": "r", "expires": "2026-01-08T00:00:00+00:00"},
            },
        }
        session.save_login(payload)

        assert len(keyring_saved) == 1
        assert keyring_saved[0].access_token == "a"
        assert file_saved == []

    def test_save_login_accepts_bare_auth_tokens_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keyring_saved = []
        monkeypatch.setattr(
            "elva_cli.auth.session.KeyringStore.save",
            lambda self, creds: keyring_saved.append(creds),
        )
        session.save_login(
            {
                "access": {"token": "a", "expires": "2026-01-01T00:00:00+00:00"},
                "refresh": {"token": "r", "expires": "2026-01-08T00:00:00+00:00"},
            }
        )
        assert keyring_saved[0].refresh_token == "r"

    def test_save_login_falls_back_to_file_when_keyring_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file_saved = []

        def raise_unavailable(self: object, creds: Credentials) -> None:
            raise StoreUnavailableError("no backend")

        monkeypatch.setattr("elva_cli.auth.session.KeyringStore.save", raise_unavailable)
        monkeypatch.setattr(
            "elva_cli.auth.session.FileStore.save", lambda self, creds: file_saved.append(creds)
        )

        session.save_pat("elva_pat_123")
        assert len(file_saved) == 1
        assert file_saved[0].access_token == "elva_pat_123"

    def test_logout_clears_every_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stores = [FakeStore(), FakeStore()]
        _patch_stores(monkeypatch, stores)
        session.logout(base_url=BASE_URL)
        assert all(s.cleared for s in stores)

    def test_logout_revokes_session_server_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        creds = _session_creds(access_in=timedelta(hours=1), refresh_in=timedelta(days=7))
        _patch_stores(monkeypatch, [FakeStore(creds=creds)])

        revoked: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> object:
            revoked["url"] = request.full_url  # type: ignore[attr-defined]
            revoked["auth"] = request.get_header("Authorization")  # type: ignore[attr-defined]

            class _Resp:
                def __enter__(self) -> object:
                    return self

                def __exit__(self, *_a: object) -> None:
                    return None

            return _Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        session.logout(base_url=BASE_URL)

        assert revoked["url"] == f"{BASE_URL}/api/auth/logout"
        assert revoked["auth"] == f"Bearer {creds.access_token}"

    def test_logout_survives_server_revocation_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        creds = _session_creds(access_in=timedelta(hours=1), refresh_in=timedelta(days=7))
        store = FakeStore(creds=creds)
        _patch_stores(monkeypatch, [store])

        def boom(*_a: object, **_kw: object) -> None:
            raise urllib.error.URLError("offline")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        session.logout(base_url=BASE_URL)  # must not raise
        assert store.cleared

    def test_logout_refreshes_a_stale_access_token_before_revoking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _session_creds(access_in=timedelta(seconds=-30), refresh_in=timedelta(days=7))
        _patch_stores(monkeypatch, [FakeStore(creds=stale)])

        fresh = _session_creds(
            access_in=timedelta(hours=1), refresh_in=timedelta(days=7), access_token="fresh-access"
        )
        monkeypatch.setattr(session, "_refresh", lambda *_a, **_kw: fresh)

        revoked: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> object:
            revoked["auth"] = request.get_header("Authorization")  # type: ignore[attr-defined]

            class _Resp:
                def __enter__(self) -> object:
                    return self

                def __exit__(self, *_a: object) -> None:
                    return None

            return _Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        session.logout(base_url=BASE_URL)

        assert revoked["auth"] == "Bearer fresh-access"

    def test_logout_uses_a_short_timeout_for_its_network_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _session_creds(access_in=timedelta(seconds=-30), refresh_in=timedelta(days=7))
        _patch_stores(monkeypatch, [FakeStore(creds=stale)])

        fresh = _session_creds(
            access_in=timedelta(hours=1), refresh_in=timedelta(days=7), access_token="fresh-access"
        )
        timeouts: list[float] = []

        def fake_refresh(*_a: object, timeout: float = 10, **_kw: object) -> Credentials:
            timeouts.append(timeout)
            return fresh

        monkeypatch.setattr(session, "_refresh", fake_refresh)

        def fake_urlopen(request: object, timeout: float) -> object:
            timeouts.append(timeout)

            class _Resp:
                def __enter__(self) -> object:
                    return self

                def __exit__(self, *_a: object) -> None:
                    return None

            return _Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        session.logout(base_url=BASE_URL)

        assert timeouts == [session._LOGOUT_TIMEOUT, session._LOGOUT_TIMEOUT]
        assert session._LOGOUT_TIMEOUT < session._HTTP_TIMEOUT

    def test_logout_skips_revocation_when_the_refresh_also_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _session_creds(access_in=timedelta(seconds=-30), refresh_in=timedelta(days=7))
        store = FakeStore(creds=stale)
        _patch_stores(monkeypatch, [store])

        def refresh_rejected(*_a: object, **_kw: object) -> Credentials:
            raise RefreshFailedError("dead")

        monkeypatch.setattr(session, "_refresh", refresh_rejected)

        def no_network(*_a: object, **_kw: object) -> None:
            raise AssertionError("logout must not reach the network with no usable token")

        monkeypatch.setattr("urllib.request.urlopen", no_network)
        session.logout(base_url=BASE_URL)  # must not raise
        assert store.cleared

    def test_logout_does_not_spend_an_already_expired_refresh_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dead = _session_creds(access_in=timedelta(seconds=-30), refresh_in=timedelta(seconds=-1))
        _patch_stores(monkeypatch, [FakeStore(creds=dead)])
        _forbid_refresh(monkeypatch)  # _refresh must not be called

        def no_network(*_a: object, **_kw: object) -> None:
            raise AssertionError("logout must not reach the network")

        monkeypatch.setattr("urllib.request.urlopen", no_network)
        session.logout(base_url=BASE_URL)  # must not raise


class TestRefreshHttpCall:
    def test_posts_refresh_token_to_the_expected_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "access": {"token": "new-access", "expires": "2026-01-01T00:00:00+00:00"},
                        "refresh": {"token": "new-refresh", "expires": "2026-01-08T00:00:00+00:00"},
                    }
                ).encode("utf-8")

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            captured["url"] = request.full_url  # type: ignore[attr-defined]
            captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
            return FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        creds = session._refresh("refresh-tok", base_url="https://api.getelva.ai")

        assert captured["url"] == "https://api.getelva.ai/api/auth/refresh-tokens"
        assert captured["body"] == {"refreshToken": "refresh-tok"}
        assert creds.access_token == "new-access"

    def test_network_failure_raises_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(*_a: object, **_kw: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        with pytest.raises(ApiError):
            session._refresh("refresh-tok", base_url="https://api.getelva.ai")

    def test_http_401_raises_refresh_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("urllib.request.urlopen", _raise_http_error(401))

        with pytest.raises(RefreshFailedError):
            session._refresh("refresh-tok", base_url="https://api.getelva.ai")

    def test_http_500_raises_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("urllib.request.urlopen", _raise_http_error(500))

        with pytest.raises(ApiError):
            session._refresh("refresh-tok", base_url="https://api.getelva.ai")

    def test_non_json_error_page_raises_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"<html>captive portal</html>"

        monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: FakeResponse())

        with pytest.raises(ApiError):
            session._refresh("refresh-tok", base_url="https://api.getelva.ai")
