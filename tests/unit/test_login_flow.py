from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message

import pytest

from elva_cli.core.services import auth as auth_service
from elva_cli.core.services.auth_result import LoginResult
from elva_cli.errors import ApiError, AuthError, ExitCode

BASE_URL = "https://api.getelva.ai"
VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")  # mirrors the backend's Joi pattern


def _noop(_message: str) -> None:
    return


class TestPkcePair:
    def test_verifier_matches_the_backends_accepted_pattern(self) -> None:
        verifier, _ = auth_service._pkce_pair()
        assert VERIFIER_RE.match(verifier)

    def test_challenge_is_base64url_sha256_of_the_verifier_no_padding(self) -> None:
        verifier, challenge = auth_service._pkce_pair()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        assert challenge == expected
        assert "=" not in challenge

    def test_successive_pairs_are_distinct(self) -> None:
        first, _ = auth_service._pkce_pair()
        second, _ = auth_service._pkce_pair()
        assert first != second


class TestUnattendedRefusal:
    def test_refuses_before_touching_the_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def forbidden() -> None:
            raise AssertionError("must not start the listener when not interactive")

        monkeypatch.setattr(auth_service, "_start_loopback_listener", forbidden)

        with pytest.raises(AuthError) as exc_info:
            auth_service.login(base_url=BASE_URL, on_progress=_noop, interactive=False)

        assert exc_info.value.exit_code == ExitCode.AUTH
        assert "ELVA_TOKEN" in (exc_info.value.hint or "")


class TestExchangeToken:
    def test_success_returns_the_parsed_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {"user": {"email": "a@b.com"}, "tokens": {"access": {}, "refresh": {}}}

        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(body).encode()

        monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: FakeResponse())
        assert auth_service._exchange_token(BASE_URL, "code", "verifier") == body

    def test_http_401_raises_autherror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_401(*_a: object, **_kw: object) -> None:
            raise urllib.error.HTTPError(BASE_URL, 401, "unauthorized", Message(), None)

        monkeypatch.setattr("urllib.request.urlopen", raise_401)
        with pytest.raises(AuthError):
            auth_service._exchange_token(BASE_URL, "code", "verifier")

    def test_http_500_raises_apierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_500(*_a: object, **_kw: object) -> None:
            raise urllib.error.HTTPError(BASE_URL, 500, "boom", Message(), None)

        monkeypatch.setattr("urllib.request.urlopen", raise_500)
        with pytest.raises(ApiError):
            auth_service._exchange_token(BASE_URL, "code", "verifier")

    def test_network_failure_raises_apierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_url_error(*_a: object, **_kw: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", raise_url_error)
        with pytest.raises(ApiError):
            auth_service._exchange_token(BASE_URL, "code", "verifier")

    def test_malformed_response_raises_apierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *_a: object) -> None:
                return None

            def read(self) -> bytes:
                return b"not json"

        monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: FakeResponse())
        with pytest.raises(ApiError):
            auth_service._exchange_token(BASE_URL, "code", "verifier")


class TestFullFlowAgainstARealListener:
    """No mocked http.server -- a real loopback listener, driven by an
    actual HTTP request from this test, exactly like a browser callback
    would arrive. webbrowser.open is mocked (never actually open a browser
    in CI) and its captured argument is how the test learns the listener's
    real, OS-assigned port."""

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
                outcome["result"] = auth_service.login(
                    base_url=BASE_URL,
                    on_progress=_noop,
                    interactive=True,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # surfaced to the test thread below
                outcome["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        if not browser_opened.wait(timeout=10):
            thread.join(timeout=5)
            error = outcome.get("error")
            detail = (
                f"login() raised before opening a browser: {error!r}"
                if error
                else (
                    f"login() neither opened a browser nor raised within 10s "
                    f"(thread alive: {thread.is_alive()})"
                )
            )
            pytest.fail(detail)
        return thread, browser_opened, captured, outcome

    @staticmethod
    def _redirect_and_state(captured: dict[str, str]) -> tuple[str, str]:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        return params["redirect_uri"][0], params["state"][0]

    def test_matching_state_completes_and_persists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        saved: list[dict[str, object]] = []
        monkeypatch.setattr(auth_service, "save_login", saved.append)
        body = {"user": {"email": "person@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda base_url, code, verifier: body)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert "error" not in outcome
        assert outcome["result"] == LoginResult(email="person@example.com")
        assert saved == [body]

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

    def test_no_callback_ever_arriving_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def forbidden(*_a: object, **_kw: object) -> dict[str, object]:
            raise AssertionError("must not exchange after a timeout with no callback")

        monkeypatch.setattr(auth_service, "_exchange_token", forbidden)

        thread, _, _captured, outcome = self._run_in_background(monkeypatch, timeout_seconds=0.3)
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert isinstance(outcome.get("error"), AuthError)
        assert "timed out" in str(outcome["error"]).lower()

    def test_a_stray_request_does_not_consume_the_callback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Browsers hit a loopback OAuth listener with things like /favicon.ico
        # and speculative connections; the wait must step over those and still
        # land the real callback rather than giving up after one request.
        monkeypatch.setattr(auth_service, "save_login", lambda _payload: None)
        body = {"user": {"email": "person@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda *_a: body)

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri.rsplit('/', 1)[0]}/favicon.ico", timeout=5).read()
        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert outcome.get("error") is None
        assert outcome["result"] == LoginResult(email="person@example.com")

    def test_malformed_exchange_payload_surfaces_as_apierror_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _exchange_token only guarantees top-level "tokens"/"user" keys exist;
        # a structurally wrong body must not escape login() as a bare KeyError.
        monkeypatch.setattr(auth_service, "save_login", lambda _payload: None)
        monkeypatch.setattr(
            auth_service, "_exchange_token", lambda *_a: {"user": "nope", "tokens": {}}
        )

        thread, _, captured, outcome = self._run_in_background(monkeypatch)
        redirect_uri, state = self._redirect_and_state(captured)

        urllib.request.urlopen(f"{redirect_uri}?state={state}&code=the-code", timeout=5).read()
        thread.join(timeout=5)

        assert not thread.is_alive()
        error = outcome.get("error")
        assert isinstance(error, ApiError)
        assert error.exit_code == ExitCode.API

    def test_unsavable_credentials_surface_as_autherror_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Sign-in succeeded but the token store can't be written (read-only
        # config dir, no keyring). That must be a clean AuthError, not a bare
        # OSError escaping login().
        body = {"user": {"email": "person@example.com"}, "tokens": {"access": {}, "refresh": {}}}
        monkeypatch.setattr(auth_service, "_exchange_token", lambda *_a: body)

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


class TestRenderImportBudget:
    def test_importing_renderables_does_not_pull_in_the_browser_flow(self) -> None:
        # The LoginResult renderer is registered whenever output is rendered
        # (`elva config ...` etc.). It must not drag http.server / urllib /
        # webbrowser -- and so ssl -- into every rendered command.
        code = (
            "import sys, elva_cli.ui.renderables\n"
            "for m in ('webbrowser', 'http.server', 'urllib.request', 'ssl',\n"
            "          'elva_cli.core.services.auth'):\n"
            "    assert m not in sys.modules, m\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)
