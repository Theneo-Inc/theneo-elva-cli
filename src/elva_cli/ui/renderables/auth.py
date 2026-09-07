from __future__ import annotations

from rich.text import Text

from elva_cli.core.services.auth_result import LoginResult  # noqa: TC001
from elva_cli.ui.renderables.base import render


@render.register
def _(result: LoginResult) -> Text:
    return Text(f"Signed in as {result.email}.", style="elva.ok")
