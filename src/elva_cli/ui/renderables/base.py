from __future__ import annotations

from functools import singledispatch
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import RenderableType


@singledispatch
def render(result: object) -> RenderableType:
    msg = f"no renderer registered for {type(result).__name__}"
    raise NotImplementedError(msg)


def aligned_rows(entries: Sequence[tuple[str, Text, Text]]) -> Text:
    """Lay out rows as aligned plain lines."""
    if not entries:
        return Text("")

    label_width = max(len(label) for label, _, _ in entries) + 2
    value_width = max(value.cell_len for _, value, _ in entries) + 2

    lines: list[Text] = []
    for label, value, note in entries:
        line = Text()
        line.append(label.ljust(label_width), style="elva.key")
        line.append_text(value)
        if note.plain:
            line.append(" " * max(1, value_width - value.cell_len))
            line.append_text(note)
        lines.append(line)
    return Text("\n").join(lines)
