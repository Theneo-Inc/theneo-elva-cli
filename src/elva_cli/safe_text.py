"""Making text from elsewhere safe to put on a terminal.

Names and messages that came from a server -- Elva's, or Postman's by way of
Elva's -- are somebody else's input. Written straight to a terminal, an escape
sequence in one of them is executed rather than shown: it can retitle the
window, clear the screen, or hide the rows underneath it so that the wrong
collection appears to be the one being imported.

Rich does not do this for us. `rich.text.Text` keeps ESC in its plain text and
`rich.control.strip_control_codes` leaves it alone as well (checked against
rich 15), so the stripping has to happen before the string reaches either.

This is not the same job as escaping Rich's own `[markup]`. That is handled by
turning markup off where strings are printed -- see ui/console.py.
"""

from __future__ import annotations

_KEEP_AS_SPACE = (0x09, 0x0A, 0x0D)

_CONTROL: dict[int, str | None] = {
    **dict.fromkeys(_KEEP_AS_SPACE, " "),
    **{code: None for code in range(0x00, 0x20) if code not in _KEEP_AS_SPACE},
    0x7F: None,
    **dict.fromkeys(range(128, 160)),
}


def printable(value: str) -> str:
    """`value` with every control character taken out of it."""
    return value.translate(_CONTROL)
