from __future__ import annotations

from rich.text import Text

from elva_cli.core.services.whoami_result import WhoamiResult  # noqa: TC001
from elva_cli.ui.renderables.base import render


@render.register
def _(result: WhoamiResult) -> Text:
    if result.company_name:
        return Text(
            f"Signed in as {result.email} "
            f"(personal access token scoped to {result.company_name}).",
            style="elva.ok",
        )
    return Text(f"Signed in as {result.email}.", style="elva.ok")
