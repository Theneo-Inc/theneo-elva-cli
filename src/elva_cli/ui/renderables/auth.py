from __future__ import annotations

from rich.text import Text

from elva_cli.core.services.auth_result import (
    AuthFailure,
    EmailAuthResult,
    LoginResult,
    LogoutResult,
    LogoutStatus,
    RegisterResult,
)
from elva_cli.ui.renderables.base import render


@render.register
def _(result: LoginResult) -> Text:
    return Text(f"Signed in as {result.email}.", style="elva.ok")


@render.register
def _(result: RegisterResult) -> Text:
    return Text(f"Account created. Signed in as {result.email}.", style="elva.ok")


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


@render.register
def _(result: EmailAuthResult) -> Text:
    lines = [result.message or result.status]
    if result.session_id:
        lines.append(f"Session: {result.session_id}")
    if result.next_action:
        lines.append(result.next_action)
    return Text("\n".join(lines))


@render.register
def _(result: AuthFailure) -> Text:
    return Text(result.message)
