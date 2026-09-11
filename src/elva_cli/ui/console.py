"""Two consoles: data on stdout, everything else on stderr.

That split is what keeps `elva pull spec | jq` clean. Spinners, hints, warnings
and errors must never land in the stream a caller is parsing.

Both have Rich markup off. Nothing here writes markup -- renderables build Text
objects with explicit styles -- but plenty of what gets printed is text the CLI
did not write: a server message, a collection name, a URL. With markup on, a
`[` in any of those is read as a style tag and, when it does not parse, raises
out of the print call.
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
        markup=False,
        no_color=color is False,
        force_terminal=True if color else None,
    )
    err = Console(
        file=sys.stderr,
        stderr=True,
        theme=ELVA_THEME,
        highlight=False,
        markup=False,
        quiet=quiet,
        no_color=color is False,
        force_terminal=True if color else None,
    )
    return out, err
