"""The browser + loopback PKCE sign-in flow (RFC 8252 + RFC 7636), register,
and logout.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from elva_cli.auth import logout as logout_credentials
from elva_cli.auth import save_login
from elva_cli.auth.store import StoreUnavailableError
from elva_cli.core.api.identity import client_headers
from elva_cli.core.services.auth_result import LoginResult, LogoutResult, RegisterResult
from elva_cli.errors import ApiError, AuthError

if TYPE_CHECKING:
    import http.server
    from collections.abc import Callable

LOGIN_TIMEOUT_SECONDS = 300.0
REGISTER_TIMEOUT_SECONDS = 1800.0
_EXCHANGE_TIMEOUT_SECONDS = 10.0
_STUCK_REQUEST_TIMEOUT_SECONDS = 10.0
_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"
_SUCCESS_PAGE = b"<html><body>All set. You can close this tab.</body></html>"
_DONE_PAGE = b"<html><body>You can close this tab and return to your terminal.</body></html>"


@dataclass(frozen=True)
class _FlowText:
    """The wording that differs between login() and register()"""

    command: str
    unattended_hint: str
    intent: str
    waiting: tuple[str, ...]
    timeout_message: str
    timeout_hint: str | None
    failure_prefix: str
    exchange_gerund: str
    exchange_noun: str
    unexpected: str
    unsaved_prefix: str
    done: str


_LOGIN_TEXT = _FlowText(
    command="elva auth login",
    unattended_hint="In CI or scripts, set ELVA_TOKEN instead.",
    intent="login",
    waiting=("Waiting for you to finish signing in...",),
    timeout_message="Login timed out waiting for the browser.",
    timeout_hint=None,
    failure_prefix="Login failed",
    exchange_gerund="Signing in",
    exchange_noun="sign-in",
    unexpected="The server returned an unexpected response while signing in.",
    unsaved_prefix="Signed in, but your credentials could not be saved",
    done="Signed in.",
)

_REGISTER_TEXT = _FlowText(
    command="elva auth register",
    unattended_hint="Run 'elva auth register' on a machine with a browser.",
    intent="register",
    waiting=(
        "Create your account in the browser, then check your email to verify it.",
        "Waiting for you to verify your email -- this can take a while.",
    ),
    timeout_message="Didn't detect a verified account in time.",
    timeout_hint="Once you've verified your email, run 'elva auth login' to sign in.",
    failure_prefix="Registration failed",
    exchange_gerund="Completing registration",
    exchange_noun="registration",
    unexpected="The server returned an unexpected response while completing registration.",
    unsaved_prefix="Account created, but your credentials could not be saved",
    done="Account created.",
)


def login(
    *,
    base_url: str,
    on_progress: Callable[[str], None],
    interactive: bool,
    timeout_seconds: float = LOGIN_TIMEOUT_SECONDS,
) -> LoginResult:
    """Run the full flow and persist the result. Raises AuthError if this
    environment can't do it, the state doesn't match, or the backend rejects
    the login; ApiError if the backend can't be reached at all."""
    email = _browser_pkce_flow(
        base_url=base_url,
        on_progress=on_progress,
        interactive=interactive,
        timeout_seconds=timeout_seconds,
        text=_LOGIN_TEXT,
    )
    return LoginResult(email=email)


def register(
    *,
    base_url: str,
    on_progress: Callable[[str], None],
    interactive: bool,
    timeout_seconds: float = REGISTER_TIMEOUT_SECONDS,
) -> RegisterResult:
    """Create an account via the browser, then wait for the user to verify
    their email"""
    email = _browser_pkce_flow(
        base_url=base_url,
        on_progress=on_progress,
        interactive=interactive,
        timeout_seconds=timeout_seconds,
        text=_REGISTER_TEXT,
    )
    return RegisterResult(email=email)


def _browser_pkce_flow(
    *,
    base_url: str,
    on_progress: Callable[[str], None],
    interactive: bool,
    timeout_seconds: float,
    text: _FlowText,
) -> str:
    """The shared login()/register() control flow."""
    if not interactive:
        raise AuthError(
            f"{text.command} requires a browser and can't run unattended.",
            hint=text.unattended_hint,
        )

    import webbrowser

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)

    server, redirect_uri, callback_params = _start_loopback_listener()
    try:
        url = _build_authorize_url(base_url, redirect_uri, state, challenge, intent=text.intent)
        on_progress(f"Opening {url}")
        webbrowser.open(url)
        on_progress("If your browser didn't open, paste that URL in manually.")
        for line in text.waiting:
            on_progress(line)
        params = _wait_for_callback(server, callback_params, timeout_seconds)
    finally:
        server.server_close()

    if not params:
        raise AuthError(text.timeout_message, hint=text.timeout_hint)
    if params.get("error"):
        raise AuthError(f"{text.failure_prefix}: {params['error']}")
    returned_state = params.get("state") or ""
    if not secrets.compare_digest(returned_state.encode("utf-8"), state.encode("utf-8")):
        raise AuthError(f"{text.failure_prefix}: state mismatch. Try again.")
    if not params.get("code"):
        raise AuthError(f"{text.failure_prefix}: no code was returned. Try again.")

    payload = _exchange_token(
        base_url,
        params["code"],
        verifier,
        failure_prefix=text.failure_prefix,
        action_gerund=text.exchange_gerund,
        action_noun=text.exchange_noun,
        unexpected=text.unexpected,
    )
    try:
        email: str = payload["user"]["email"]
        save_login(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(text.unexpected) from exc
    except (StoreUnavailableError, OSError) as exc:
        raise AuthError(
            f"{text.unsaved_prefix}: {exc}",
            hint="Check permissions on your config directory, then run 'elva auth login' again.",
        ) from exc
    on_progress(text.done)
    return email


def logout(*, base_url: str) -> LogoutResult:
    return logout_credentials(base_url=base_url)


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256: a random verifier, and its base64url(sha256(...)) challenge."""
    verifier = "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(64))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _build_authorize_url(
    base_url: str, redirect_uri: str, state: str, challenge: str, *, intent: str = "login"
) -> str:
    import urllib.parse

    params = {
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if intent != "login":
        params["intent"] = intent
    query = urllib.parse.urlencode(params)
    return f"{base_url}/api/auth/cli/authorize?{query}"


def _make_callback_handler(result: dict[str, str]) -> type[http.server.BaseHTTPRequestHandler]:
    import http.server
    import urllib.parse

    class _Handler(http.server.BaseHTTPRequestHandler):
        # A speculative browser connection that never sends a byte would
        # otherwise block the read forever; time it out so the wait loop moves on.
        timeout = _STUCK_REQUEST_TIMEOUT_SECONDS

        def do_GET(self) -> None:
            query = urllib.parse.urlparse(self.path).query
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            landed = result.get("code") and "error" not in result
            self.wfile.write(_SUCCESS_PAGE if landed else _DONE_PAGE)

        def log_message(self, *_args: object) -> None:
            return

    return _Handler


def _start_loopback_listener() -> tuple[http.server.HTTPServer, str, dict[str, str]]:
    """A loopback HTTP server on an OS-assigned port."""
    import http.server

    result: dict[str, str] = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), _make_callback_handler(result))
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/callback", result


def _wait_for_callback(
    server: http.server.HTTPServer, result: dict[str, str], timeout_seconds: float
) -> dict[str, str]:
    """Serve requests until the callback lands (`code` or `error`) or the deadline passes."""
    deadline = time.monotonic() + timeout_seconds
    while not result.keys() & {"code", "error"}:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server.timeout = remaining
        server.handle_request()
    return result


def _exchange_token(
    base_url: str,
    code: str,
    verifier: str,
    *,
    failure_prefix: str = "Login failed",
    action_gerund: str = "Signing in",
    action_noun: str = "sign-in",
    unexpected: str = "The server returned an unexpected response while signing in.",
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{base_url}/api/auth/cli/token",
        data=json.dumps({"code": code, "code_verifier": verifier}).encode("utf-8"),
        headers={"Content-Type": "application/json", **client_headers()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_EXCHANGE_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401):
            raise AuthError(
                f"{failure_prefix}: the code was invalid or expired. Try again."
            ) from exc
        raise ApiError(f"{action_gerund} failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f"Could not reach the server to complete {action_noun}.") from exc

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(unexpected) from exc
    if not isinstance(body, dict) or "tokens" not in body or "user" not in body:
        raise ApiError(unexpected)
    return body
