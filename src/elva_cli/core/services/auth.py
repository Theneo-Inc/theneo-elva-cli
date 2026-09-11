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
_FAVICON_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAEuklEQVR4AcSXW0wcVRjH/wydZROWRKQ8UGh4ABKg"
    "ShY3XJqIEZM2Rdtq0jSgPBi1pawhqQ/QoKRIaqNSX4gpEQXqJaGhTUB5KaatISaacAl2I1SCxBhpeAAq1BSBZYD1"
    "/E88ZBiY3dmXdru/ft935rv8z9nZCxrEIxQKaS0tLWfKysruFBcXrxUUFISipbCwMGRHUVFRiIiea16v9052dnaV"
    "GCtnaxxeU1PTVV9f39bf3+8dHBzUR0ZGEC3Dw8OwY2hoCET01AOBgHdycvJzIaBLoGm1tbWnOjo6KlZXV0X8aJ5i"
    "0xxUIf47rfX29vqDwaDwH8uzWpuZmTnwWEaLoTExMQc0wzB04Uf1FIWwI5pGoocu70SnRaIAmqZhz549ktjYWJjh"
    "NcI8OHxoDvO2dhwfH4+UlBQkJiZC13UpgIKUECXAqQjHAiiUzT0eDxoaGnH27Dm89WYdXq2ow7FjdTh86BwqX/sK"
    "brdHimW+ExwL4I5IYmIyxsZ+R0tLM75o/xhdV5vR19eMW7c/wcLCXzCMFSdzpUj2cySAiYqCgqPo6rqCxcVFrK+v"
    "Y2NjA5ubm0hKysT8/BT+f4+HFcFeTKCNSoCuxyG4GoeHDx/IoRzMRsSX9wrGxr+TAuxEcCBhvrIRBahE2tzcFzE8"
    "cmPHEJfuRrxLFyeyIo+W9wrziRpm50cUwAaq4b4UL+7d+2VLAJuSYu9R/DpxQw53u91ISEhAXFycjHmdPYjyaRUa"
    "HV60g9fJ3r0ZuH//Dzlc5fKoiUvs/qDvEF4/WQv/G+/io6bLUoQSznz22M2GPQEWKfKePiFe42/lrsyNKODWT1fx"
    "Tc8lfHntEmYX/sTEVEC8HOtMk7AHHbOlT8IKYJEic38eDj97CieP1CI/9/ktIeo6m/mr3sHc/Czar7RiaWlp22nx"
    "OnNpifIjCuAOydfdp3H75w7MLU4BMRtSAI+YeOI9OP/eRQz8eBM/DHwvPgsM+fZkHcTDPFCE8sk1EvYeYAPCt1tw"
    "bQXBtWU8levD+OSgbMLhqalpON9wAW3tn+K3iXE5mJ8NrGMSh1gt1wjXI54AkwgbPvlEMv75dxYh8Y/D8/OfQXXV"
    "2/jgw0bMzc3u+GxgHVHDaAnXCH3HApj80pETuDnQI78Rjx9/GSUlJbhw8X0sLy/LnfOkKJTNCWtoidVnTMIKYALh"
    "bvltl7IvGYsP/obf7xdfx7Fobb0sd203lIPNsJc5pr9DAJMUTFB+cdFBjE8E0NjYCP747Ovrk3e5edcql3UKrimf"
    "lrGZrZtQLTJpN9L2p6H0hefQ2dmJ0dHRXY9c1Vl7MVbXrFaeQLgEFvCIr1+/BvELGtPT09uOnbXhYD1ROfQJY1p5"
    "Agzs4HDCo1YwZjGxqzOvM0+h1hnTlwIY7AYTCAcSClB5XI8GVWe1mmhq2DVisvXabmvWHL5riHWdtWbEb0mD98Bd"
    "8yJ9a6FdbB3CmKh8+lbUNdqkpKS7fAnaGJgJJ4INmaus8s0x1yLhcrng8/k+4x8m7SK5WyC/YKK11sGMI8HhpaWl"
    "3Tk5OR18CTYNw6hMTU09k56eHsjIyDAyMzPhFJG/LZcxUfW0jElWVpYh/jwPlJeXV/f09FQ2NTVt/gcAAP//9u3d"
    "PgAAAAZJREFUAwA1UAUkXF9d2QAAAABJRU5ErkJggg=="
)
_CALLBACK_PAGE = string.Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<link rel="icon" type="image/png" href="data:image/png;base64,$favicon">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap">
<style>
  html, body { margin: 0; height: 100%; }
  body {
    background: #080808;
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .page {
    position: relative; display: flex; align-items: center; justify-content: center;
    min-height: 100vh; padding: 25px; box-sizing: border-box; overflow: hidden;
  }
  .page > svg { position: absolute; top: 0; left: 0; width: 100%; height: auto; }
  .message { position: relative; z-index: 1; text-align: center; }
  h1 { margin: 0 0 10px; font-size: 24px; line-height: 36px; font-weight: 600; color: #FFFFFF; }
  p { margin: 0; font-size: 16px; line-height: 24px; color: rgba(255, 255, 255, 0.6); }
</style>
</head>
<body>
<main class="page">
  <svg viewBox="0 0 1817 432" fill="none" aria-hidden="true">
    <defs>
      <filter id="blur" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur stdDeviation="50"/>
      </filter>
      <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
        <stop stop-color="#8669DC" stop-opacity="0.4"/>
        <stop offset="1" stop-color="#8669DC" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <g fill="url(#beam)">
      <rect filter="url(#blur)" fill-opacity="0.8" x="741.068" y="-271.24" width="251"
            height="577"/>
      <rect filter="url(#blur)" fill-opacity="0.8" x="500.867" y="-294.009" width="251" height="577"
            transform="rotate(15.1572 500.867 -294.009)"/>
      <rect filter="url(#blur)" fill-opacity="0.8" x="250.867" y="-354" width="251" height="577"
            transform="rotate(15.1572 250.867 -354)"/>
      <rect filter="url(#blur)" fill-opacity="0.8" x="1006.48" y="-207.562" width="251" height="577"
            transform="rotate(-20.8806 1006.48 -207.562)"/>
      <rect filter="url(#blur)" x="1276.48" y="-207.555" width="251" height="577"
            transform="rotate(-20.8806 1276.48 -207.555)"/>
    </g>
  </svg>
  <div class="message">
    <h1>$heading</h1>
    <p>$message</p>
  </div>
</main>
</body>
</html>
""")
_SUCCESS_PAGE = _CALLBACK_PAGE.substitute(
    favicon=_FAVICON_PNG_BASE64,
    title="Signed in - Elva",
    heading="You're signed in to Elva",
    message="Your terminal has what it needs. "
    "You can close this tab and carry on where you left off.",
).encode("utf-8")
_DONE_PAGE = _CALLBACK_PAGE.substitute(
    favicon=_FAVICON_PNG_BASE64,
    title="Elva",
    heading="You can close this tab",
    message="Return to your terminal to continue.",
).encode("utf-8")


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
