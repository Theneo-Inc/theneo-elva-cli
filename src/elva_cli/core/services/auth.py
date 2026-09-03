"""The browser + loopback PKCE sign-in flow (RFC 8252 + RFC 7636).

Talks to the backend's /api/auth/cli/{authorize,token} pair (the /complete
step happens server-side, driven by the browser, not by us) and hands the
result to elva_cli.auth.save_login — this module owns none of the credential
storage itself, only getting a fresh session in the first place.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import time
from typing import TYPE_CHECKING, Any

from elva_cli.auth import save_login
from elva_cli.auth.store import StoreUnavailableError
from elva_cli.core.services.auth_result import LoginResult
from elva_cli.errors import ApiError, AuthError

if TYPE_CHECKING:
    import http.server
    from collections.abc import Callable

LOGIN_TIMEOUT_SECONDS = 300.0
_EXCHANGE_TIMEOUT_SECONDS = 10.0
_STUCK_REQUEST_TIMEOUT_SECONDS = 10.0
_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"
_SUCCESS_PAGE = b"<html><body>Signed in. You can close this tab.</body></html>"
_DONE_PAGE = b"<html><body>You can close this tab and return to your terminal.</body></html>"


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
    if not interactive:
        raise AuthError(
            "elva auth login requires a browser and can't run unattended.",
            hint="In CI or scripts, set ELVA_TOKEN instead.",
        )

    import webbrowser

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)

    server, redirect_uri, callback_params = _start_loopback_listener()
    try:
        url = _build_authorize_url(base_url, redirect_uri, state, challenge)
        on_progress(f"Opening {url}")
        webbrowser.open(url)
        on_progress("If your browser didn't open, paste that URL in manually.")
        on_progress("Waiting for you to finish signing in...")
        params = _wait_for_callback(server, callback_params, timeout_seconds)
    finally:
        server.server_close()

    if not params:
        raise AuthError("Login timed out waiting for the browser.")
    if params.get("error"):
        raise AuthError(f"Login failed: {params['error']}")
    returned_state = params.get("state") or ""
    if not secrets.compare_digest(returned_state.encode("utf-8"), state.encode("utf-8")):
        raise AuthError("Login failed: state mismatch. Try again.")
    if not params.get("code"):
        raise AuthError("Login failed: no code was returned. Try again.")

    payload = _exchange_token(base_url, params["code"], verifier)
    unexpected = "The server returned an unexpected response while signing in."
    try:
        email = payload["user"]["email"]
        save_login(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(unexpected) from exc
    except (StoreUnavailableError, OSError) as exc:
        raise AuthError(
            f"Signed in, but your credentials could not be saved: {exc}",
            hint="Check permissions on your config directory, then run 'elva auth login' again.",
        ) from exc
    on_progress("Signed in.")
    return LoginResult(email=email)


def _pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256: a random verifier, and its base64url(sha256(...)) challenge."""
    verifier = "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(64))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _build_authorize_url(base_url: str, redirect_uri: str, state: str, challenge: str) -> str:
    import urllib.parse

    query = urllib.parse.urlencode(
        {
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
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
    """A loopback HTTP server on an OS-assigned port. The backend's redirect_uri
    allowlist is exactly {127.0.0.1, [::1]} with an explicit port and http://
    only (see isValidLoopbackRedirectUri) — bind literally to 127.0.0.1 so the
    redirect_uri we send matches it exactly."""
    import http.server

    result: dict[str, str] = {}
    server = http.server.HTTPServer(("127.0.0.1", 0), _make_callback_handler(result))
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/callback", result


def _wait_for_callback(
    server: http.server.HTTPServer, result: dict[str, str], timeout_seconds: float
) -> dict[str, str]:
    """Serve requests until the OAuth callback lands (it carries `code` or
    `error`) or the deadline passes.

    Not a single `handle_request()`: browsers routinely open speculative
    connections to a loopback port and send nothing on them, and hit paths like
    /favicon.ico. The handler carries a per-request socket timeout so a silent
    connection can't wedge the read forever, and this loop steps past it (and
    past stray hits) to the real callback."""
    deadline = time.monotonic() + timeout_seconds
    while not result.keys() & {"code", "error"}:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        server.timeout = remaining
        server.handle_request()
    return result


def _exchange_token(base_url: str, code: str, verifier: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{base_url}/api/auth/cli/token",
        data=json.dumps({"code": code, "code_verifier": verifier}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_EXCHANGE_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401):
            raise AuthError("Login failed: the code was invalid or expired. Try again.") from exc
        raise ApiError(f"Signing in failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError("Could not reach the server to complete sign-in.") from exc

    unexpected = "The server returned an unexpected response while signing in."
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(unexpected) from exc
    if not isinstance(body, dict) or "tokens" not in body or "user" not in body:
        raise ApiError(unexpected)
    return body
