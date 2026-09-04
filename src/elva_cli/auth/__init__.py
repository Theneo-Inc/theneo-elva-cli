"""Credentials and the login flow.

Token storage sits behind a Protocol (keyring, with a 0600 file fallback for
headless Linux and containers). ELVA_TOKEN overrides both in CI. A session's
access token refreshes itself transparently on a near-expiry read; a dead
session raises AuthError (exit code 3).

The browser handoff needs a /auth/cli endpoint on the JWT side of the
backend. The cookie-session auth used by the catalog and GitHub routes is
deliberately out of scope: a CLI has no cookie jar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.auth.models import Credentials

if TYPE_CHECKING:
    from elva_cli.auth.session import get_access_token, logout, save_login, save_pat

__all__ = ["Credentials", "get_access_token", "logout", "save_login", "save_pat"]

_LAZY = frozenset(__all__) - {"Credentials"}


def __getattr__(name: str) -> object:
    if name in _LAZY:
        from elva_cli.auth import session

        return getattr(session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
