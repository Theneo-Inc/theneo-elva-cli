"""The auth flow's result types, kept apart from the flows themselves.

elva_cli.ui.renderables.auth has to import these classes at runtime
(singledispatch resolves the annotation when it registers the renderer).
Keeping them here means that import — and so `import elva_cli.ui.renderables`,
which every rendered command pulls in — does not drag in http.server / urllib
/ webbrowser.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


@dataclass(frozen=True)
class LoginResult:
    email: str


class LogoutStatus(enum.StrEnum):
    """Why `elva auth logout` ended the way it did.

    NOT_SIGNED_IN: there was no stored credential to sign out of.

    SIGNED_OUT: the local credentials were cleared *and* there is nothing
    left alive server-side (session was revoked, or nothing to revoke).

    REVOCATION_FAILED: the server couldn't be reached to revoke a session
    that may well still be live.
    """

    NOT_SIGNED_IN = "not_signed_in"
    SIGNED_OUT = "signed_out"
    REVOCATION_FAILED = "revocation_failed"


@dataclass(frozen=True)
class LogoutResult:
    status: LogoutStatus
