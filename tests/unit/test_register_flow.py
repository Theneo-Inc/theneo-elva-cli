from __future__ import annotations

import threading
import urllib.parse
import urllib.request

import pytest

from elva_cli.core.services import auth as auth_service
from elva_cli.core.services.auth_result import RegisterResult
from elva_cli.errors import ApiError, AuthError, ExitCode

BASE_URL = "https://api.getelva.ai"


@pytest.fixture(scope="module", autouse=True)
def _warm_up_loopback_binding() -> None:
    """See test_login_flow.py's fixture of the same name -- same reasoning,
    duplicated here because this is a separate real-listener test module."""
    import http.server

    for _ in range(2):
        http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler).server_close()


def _noop(_message: str) -> None:
    return


class TestBuildAuthorizeUrl:
    def test_register_intent_is_present(self) -> None:
        url = auth_service._build_authorize_url(
            BASE_URL, "http://127.0.0.1:1/callback", "state", "challenge", intent="register"
        )
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert params["intent"] == ["register"]

    def test_plain_login_omits_intent_entirely(self) -> None:
        url = auth_service._build_authorize_url(
            BASE_URL, "http://127.0.0.1:1/callback", "state", "challenge"
        )
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert "intent" not in params


class TestUnattendedRefusal:
    def test_refuses_before_touching_the_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def forbidden() -> None:
            raise AssertionError("must not start the listener when not interactive")

        monkeypatch.setattr(auth_service, "_start_loopback_listener", forbidden)

        with pytest.raises(AuthError) as exc_info:
            auth_service.register(base_url=BASE_URL, on_progress=_noop, interactive=False)

        assert exc_info.value.exit_code == ExitCode.AUTH
        # not "set ELVA_TOKEN" -- that's login's fallback; register has no
        # account to point a token at yet.
        assert "browser" in (exc_info.value.hint or "")


class TestFullFlowAgainstARealListener:
    """Same approach as test_login_flow.py's equivalent class: a real
    loopback listener driven by an actual HTTP request, webbrowser.open
    mocked to capture the authorize URL instead of opening anything."""

    def _run_in_background(
        self, monkeypatch: pytest.MonkeyPatch, *, timeout_seconds: float = 5
    ) -> tuple[threading.Thread, threading.Event, dict[str, str], dict[str, object]]:
        browser_opened = threading.Event()
        captured: dict[str, str] = {}

        def fake_open(url: str) -> bool:
            captured["url"] = url
            browser_opened.set()
            return True

        monkeypatch.setattr("webbrowser.open", fake_open)

        outcome: dict[str, object] = {}

        def run() -> None:
            try:
                outcome["result"] = auth_service.register(
                    base_url=BASE_URL,
                    on_progress=_noop,
                    interactive=True,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # surfaced to the test thread below
                outcome["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        assert browser_opened.wait(timeout=2), "webbrowser.open was never called"
        return thread, browser_opened, captured, outcome

    @staticmethod
    def _redirect_and_state(captured: dict[str, str]) -> tuple[str, str]:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        return params["redirect_uri"][0], params["state"][0]

    def test_authorize_url_carries_the_register_intent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_a: object, **_kw: object) -> dict[str, object]:
            raise AssertionError("not needed for this test")

        monkeypatch.setattr(auth_service, "_exchange_token", forbidden)

        thread, _, captured, outcome = self._run_in_background(monkeypatch, timeout_seconds=0.3)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        thread.join(timeout=5)

        assert params["intent"] == ["register"]
        assert isinstance(outcome.get("error"), AuthError)  # the 0.3s timeout firing

    def test_verification_completes_and_persists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        saved: list[dict[str, object]] = []
        monkeypatch.setattr(auth_service, "save_login", saved.append)
        body = {"user": {"email": "new@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda *_a, **_kw: body)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert "error" not in outcome
        assert outcome["result"] == RegisterResult(email="new@example.com")
        assert saved == [body]

    def test_no_verification_ever_arriving_times_out_with_a_login_fallback_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_a: object, **_kw: object) -> dict[str, object]:
            raise AssertionError("must not exchange after a timeout with no callback")

        monkeypatch.setattr(auth_service, "_exchange_token", forbidden)

        thread, _, _captured, outcome = self._run_in_background(monkeypatch, timeout_seconds=0.3)
        thread.join(timeout=5)

        assert not thread.is_alive()
        error = outcome.get("error")
        assert isinstance(error, AuthError)
        assert "elva auth login" in (error.hint or "")

    def test_mismatched_state_is_rejected_without_exchanging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_a: object, **_kw: object) -> dict[str, object]:
            raise AssertionError("must not exchange a code behind a mismatched state")

        monkeypatch.setattr(auth_service, "_exchange_token", forbidden)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, _real_state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state=not-the-real-state&code=x", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert isinstance(outcome.get("error"), AuthError)
        assert "state" in str(outcome["error"]).lower()

    def test_malformed_exchange_payload_surfaces_as_apierror_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(auth_service, "save_login", lambda _payload: None)
        monkeypatch.setattr(
            auth_service, "_exchange_token", lambda *_a, **_kw: {"user": "nope", "tokens": {}}
        )

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        error = outcome.get("error")
        assert isinstance(error, ApiError)
        assert error.exit_code == ExitCode.API

    def test_error_param_is_surfaced_without_exchanging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_a: object, **_kw: object) -> dict[str, object]:
            raise AssertionError("must not exchange when the callback carries an error")

        monkeypatch.setattr(auth_service, "_exchange_token", forbidden)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(
            f"{redirect_uri}?state={state}&error=access_denied", timeout=5
        ).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert isinstance(outcome.get("error"), AuthError)

    def test_a_stray_request_does_not_consume_the_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(auth_service, "save_login", lambda _payload: None)
        body = {"user": {"email": "new@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda *_a, **_kw: body)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri.rsplit('/', 1)[0]}/favicon.ico", timeout=5).read()
        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert outcome.get("error") is None
        assert outcome["result"] == RegisterResult(email="new@example.com")

    def test_unsavable_credentials_surface_as_autherror_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {"user": {"email": "new@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda *_a, **_kw: body)

        def unwritable(_payload: object) -> None:
            raise OSError("Read-only file system")

        monkeypatch.setattr(auth_service, "save_login", unwritable)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        error = outcome.get("error")
        assert isinstance(error, AuthError)
        assert error.exit_code == ExitCode.AUTH
