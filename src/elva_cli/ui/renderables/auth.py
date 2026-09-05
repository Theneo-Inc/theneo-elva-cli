from __future__ import annotations

from rich.text import Text

from elva_cli.core.services.auth_result import LoginResult, LogoutResult, LogoutStatus
from elva_cli.ui.renderables.base import render


@render.register
def _(result: LoginResult) -> Text:
    return Text(f"Signed in as {result.email}.", style="elva.ok")


@render.register
def _(result: LogoutResult) -> Text:
    if result.status is LogoutStatus.NOT_SIGNED_IN:
        return Text("You weren't signed in.", style="elva.dim")
    if result.status is LogoutStatus.REVOCATION_FAILED:
        return Text(
            "Couldn't reach the server to end your session, so you're still signed "
            "in. Your credentials were kept — check your connection and run "
            "'elva auth logout' again.",
            style="elva.warn",
        )
    return Text("Signed out.", style="elva.ok")
