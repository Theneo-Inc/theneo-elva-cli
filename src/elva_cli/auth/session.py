"""Precedence between credential sources, and transparent session refresh.

Order: ELVA_TOKEN env var, then whichever TokenStore (keyring, then file)
has something. A session's access token refreshes itself silently on a
near-expiry read; a PAT is used as-is (no expiry the client knows about).
A refresh token that's also expired, or a refresh the backend positively
rejects (401/403), surfaces as AuthError — exit code 3, "Run 'elva auth
login' to sign in." A transient refresh failure (network down, timeout,
5xx) surfaces as ApiError and leaves stored credentials intact.

The refresh itself is serialised across concurrent `elva` processes with a
file lock (see _refresh_lock): the backend spends a refresh token on first
use, so two processes racing to refresh the same near-expiry session would
have one 401 and, on that 401, clear the credentials the other just saved.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from elva_cli.auth.models import Credentials
from elva_cli.auth.store import FileStore, KeyringStore, StoreUnavailableError, TokenStore
from elva_cli.errors import ApiError, AuthError
from elva_cli.settings import paths

if TYPE_CHECKING:
    from collections.abc import Iterator

_logger = logging.getLogger(__name__)

_ENV_TOKEN = "ELVA_TOKEN"
_SKEW = timedelta(seconds=60)
_LOCK_FILE = "refresh.lock"
_HTTP_TIMEOUT = 10
_LOGOUT_TIMEOUT = 5


class RefreshFailedError(Exception):
    """The backend positively rejected this refresh token (401/403) — the
    session is dead and its credentials should be cleared.

    A transient failure (network down, timeout, 5xx, a captive-portal error
    page) is NOT this — it raises ApiError instead and leaves credentials
    untouched, so a flaky connection can't force a full re-login."""


def _stores() -> list[TokenStore]:
    return [KeyringStore(), FileStore()]


def _load_from_first_available_store() -> tuple[Credentials | None, TokenStore | None]:
    for store in _stores():
        creds = store.load()
        if creds is not None:
            return creds, store
    return None, None


def _clear_all_stores() -> None:
    for store in _stores():
        store.clear()


def _save_preferring_keyring(creds: Credentials) -> None:
    """Persist to exactly one store and clear the other, so a stale copy in
    the store we're *not* using can never shadow this one on the next read
    (get_access_token checks the keyring first)."""
    try:
        KeyringStore().save(creds)
    except StoreUnavailableError:
        FileStore().save(creds)
        KeyringStore().clear()
    else:
        FileStore().clear()


def _persist_refreshed(creds: Credentials) -> None:
    """Save a freshly refreshed session.

    The refresh token that produced it is already spent server-side, so if
    this doesn't land the next run is a forced re-login. Go through
    _save_preferring_keyring so a single failing store falls back to the
    other one, and if even that fails, say so instead of failing silently.
    This module sits below the ui/ boundary (see tests/unit/test_boundary.py)
    and must not print — logging is the escape hatch for a below-boundary
    module that still needs to surface something; elva_cli.logging is what
    wires a handler up to it."""
    try:
        _save_preferring_keyring(creds)
    except (StoreUnavailableError, OSError):
        _logger.warning(
            "your session was refreshed but could not be saved; "
            "you may need to run 'elva auth login' again."
        )


def _acquire_lock_fd() -> int | None:
    """An fd holding an exclusive advisory lock on the refresh lock file, or
    None if locking isn't available here (non-POSIX, or a filesystem with no
    working flock — NFS without lockd, some container overlays). A None means
    "couldn't serialise"; the caller then just refreshes unlocked, exactly as
    it did before this lock existed."""
    try:
        import fcntl
    except ImportError:  # non-POSIX
        return None

    try:
        directory = paths.config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / _LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None

    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        with contextlib.suppress(OSError):
            os.close(fd)
        return None
    return fd


@contextlib.contextmanager
def _refresh_lock() -> Iterator[None]:
    """Hold the cross-process refresh lock for the duration of the block.

    Best-effort: if the lock can't be taken the block still runs, just
    without serialisation. The caller must re-read the store inside the
    block — by the time a waiter gets in, the process that held the lock has
    usually already saved a fresh token."""
    fd = _acquire_lock_fd()
    if fd is None:
        yield
        return
    try:
        yield
    finally:
        import fcntl

        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(fd)

# one refresh + one revoke, so the total stays within a single _HTTP_TIMEOUT.

def _refresh(refresh_token: str, *, base_url: str, timeout: float = _HTTP_TIMEOUT) -> Credentials:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{base_url}/api/auth/refresh-tokens",
        data=json.dumps({"refreshToken": refresh_token}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RefreshFailedError(f"backend rejected refresh token (HTTP {exc.code})") from exc
        raise ApiError(f"Refreshing your session failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError("Could not reach the server to refresh your session.") from exc

    unexpected = "The server returned an unexpected response while refreshing your session."
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(unexpected) from exc
    if not isinstance(body, dict):
        raise ApiError(unexpected)
    try:
        return Credentials.from_auth_tokens(body)
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(unexpected) from exc


def get_access_token(*, base_url: str) -> str:
    """The bearer token to send on this request. Refreshes a near-expiry
    session transparently; raises AuthError if there's nothing usable."""
    env_token = os.environ.get(_ENV_TOKEN)
    if env_token:
        return env_token

    creds, store = _load_from_first_available_store()
    if creds is None or store is None:
        raise AuthError("You're not logged in.")

    if creds.kind == "pat":
        return creds.access_token

    now = datetime.now(UTC)
    if (
        creds.access_expires_at is None
        or creds.refresh_expires_at is None
        or creds.refresh_token is None
    ):
        raise AuthError("You're not logged in.")

    if creds.access_expires_at - now > _SKEW:
        return creds.access_token

    if creds.refresh_expires_at <= now:
        _clear_all_stores()
        raise AuthError("Your session has expired.")

    return _refresh_session(base_url=base_url)


def _refresh_session(*, base_url: str) -> str:
    """Refresh the stored session under the cross-process lock and return the
    new access token.

    The store is re-read *inside* the lock: a process that waited for the
    lock normally finds that the holder already refreshed and saved, and
    returns that token without a network call. This is what stops a
    single-use refresh token from being spent twice — the second spend 401s,
    and the 401 handler would wipe the other process's fresh credentials."""
    with _refresh_lock():
        creds, store = _load_from_first_available_store()
        if (
            creds is None
            or store is None
            or creds.kind != "session"
            or creds.access_expires_at is None
            or creds.refresh_expires_at is None
            or creds.refresh_token is None
        ):
            raise AuthError("Your session has expired.")

        now = datetime.now(UTC)
        if creds.access_expires_at - now > _SKEW:
            return creds.access_token

        if creds.refresh_expires_at <= now:
            _clear_all_stores()
            raise AuthError("Your session has expired.")

        try:
            refreshed = _refresh(creds.refresh_token, base_url=base_url)
        except RefreshFailedError as exc:
            _clear_all_stores()
            raise AuthError("Your session has expired.") from exc
        except ApiError:
            if creds.access_expires_at - datetime.now(UTC) > timedelta(0):
                return creds.access_token
            raise

        _persist_refreshed(refreshed)
        return refreshed.access_token


def save_login(payload: dict[str, Any]) -> None:
    """Persist a fresh OAuth session from the CLI login exchange.

    POST /api/auth/cli/token responds with {"user": ..., "tokens": {...}};
    the refresh endpoint responds with the bare {"access", "refresh"} shape.
    Accept either so callers don't have to care which one they hold."""
    tokens = payload.get("tokens", payload)
    _save_preferring_keyring(Credentials.from_auth_tokens(tokens))


def save_pat(token: str) -> None:
    """Persist a Personal Access Token."""
    _save_preferring_keyring(Credentials.from_pat(token))


def _revoke_server_side(
    access_token: str, *, base_url: str, timeout: float = _HTTP_TIMEOUT
) -> None:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"{base_url}/api/auth/logout",
        data=b"",
        headers={"Authorization": f"Bearer {access_token}"},
        method="POST",
    )
    with (
        contextlib.suppress(urllib.error.URLError, TimeoutError),
        urllib.request.urlopen(request, timeout=timeout),
    ):
        pass


def _revocation_token(
    creds: Credentials, *, base_url: str, timeout: float = _HTTP_TIMEOUT
) -> str | None:
    """An access token that will still authenticate the logout call.

    The stored one is used if it's still fresh; otherwise the refresh token
    is spent for a new one, because a stale access token would just 401 and
    leave the session alive server-side. Spending the refresh token is fine
    here — the logout endpoint invalidates all of them anyway. Returns None
    if nothing usable is left (offline, everything expired)."""
    now = datetime.now(UTC)
    if creds.access_expires_at is not None and creds.access_expires_at - now > _SKEW:
        return creds.access_token
    if (
        creds.refresh_token is None
        or creds.refresh_expires_at is None
        or creds.refresh_expires_at <= now
    ):
        return None
    try:
        return _refresh(creds.refresh_token, base_url=base_url, timeout=timeout).access_token
    except (RefreshFailedError, ApiError):
        return None


def logout(*, base_url: str) -> None:
    """Forget the stored credentials and, best-effort, revoke the session
    server-side (POST /api/auth/logout).

    The backend endpoint deletes *all* of the account's refresh tokens, so
    this also ends any browser session for the same account. That is
    deliberate — `elva auth logout` is meant to fully sign out, e.g. on a
    shared machine. If the stored access token has expired, the refresh
    token is spent to get one so the revocation still goes through;
    revocation is skipped only when the network is down or nothing usable is
    left. The local credentials are cleared either way, and the network calls
    run on a short timeout (_LOGOUT_TIMEOUT) so this can't hang on a dead
    connection.
    """
    creds, _ = _load_from_first_available_store()
    _clear_all_stores()
    if creds is None or creds.kind != "session":
        return
    token = _revocation_token(creds, base_url=base_url, timeout=_LOGOUT_TIMEOUT)
    if token is not None:
        _revoke_server_side(token, base_url=base_url, timeout=_LOGOUT_TIMEOUT)
