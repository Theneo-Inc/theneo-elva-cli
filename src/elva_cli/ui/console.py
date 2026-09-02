"""Two consoles: data on stdout, everything else on stderr.

That split is what keeps `elva pull spec | jq` clean. Spinners, hints, warnings
and errors must never land in the stream a caller is parsing.
"""

from __future__ import annotations

import sys

from rich.console import Console

from elva_cli.ui.theme import ELVA_THEME


def build_consoles(*, color: bool | None, quiet: bool) -> tuple[Console, Console]:
    out = Console(
        file=sys.stdout,
        theme=ELVA_THEME,
        highlight=False,
        no_color=color is False,
        force_terminal=True if color else None,
    )
    err = Console(
        file=sys.stderr,
        stderr=True,
        theme=ELVA_THEME,
        highlight=False,
        quiet=quiet,
        no_color=color is False,
        force_terminal=True if color else None,
    )
    return out, err
