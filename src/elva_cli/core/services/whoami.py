"""Who is the current bearer token for? (GET /api/auth/me)

Local credentials (elva_cli.auth.Credentials) are opaque -- just tokens and
expiry, no email -- so the network round-trip here is the point, not
something to optimize away.
"""

from __future__ import annotations

import json
from typing import Any

from elva_cli import auth
from elva_cli.auth import get_access_token
from elva_cli.core.services.whoami_result import WhoamiResult
from elva_cli.errors import ApiError, AuthError

_HTTP_TIMEOUT = 10.0
_UNEXPECTED_RESPONSE = "The server returned an unexpected response while checking who you are."


def whoami(*, base_url: str) -> WhoamiResult:
    """Raises AuthError if nothing is stored (or the stored token is dead);
    ApiError if the backend can't be reached or returns something unexpected."""
    token = get_access_token(base_url=base_url)
    try:
        body = _fetch_me(base_url, token)
    except AuthError as exc:
        raise _rejected_token_error() from exc

    try:
        email = body["user"]["email"]
    except (KeyError, TypeError) as exc:
        raise ApiError(_UNEXPECTED_RESPONSE) from exc

    pat = body.get("pat")
    company_name = pat.get("companyName") if isinstance(pat, dict) else None
    return WhoamiResult(email=email, company_name=company_name)


def _rejected_token_error() -> AuthError:
    """The backend rejected the token get_access_token handed us."""
    identity = auth.current_identity()
    if identity != "env":
        auth.forget_stored_credentials()
    if identity == "env":
        hint = f"The {auth.ENV_TOKEN} value was rejected -- check it's a current token."
    elif identity == "pat":
        hint = "Your access token was rejected -- generate a new one and try again."
    else:
        hint = "Run 'elva auth login' to sign in again."
    return AuthError("Your credentials are no longer valid.", hint=hint)


def _fetch_me(base_url: str, token: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{base_url}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("Your credentials are no longer valid.") from exc
        raise ApiError(f"Could not verify who you are (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError("Could not reach the server.") from exc

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(_UNEXPECTED_RESPONSE) from exc
    if not isinstance(body, dict) or "user" not in body:
        raise ApiError(_UNEXPECTED_RESPONSE)
    return body
