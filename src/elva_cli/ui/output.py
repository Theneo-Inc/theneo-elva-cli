"""The single place a Result turns into bytes on a stream.

Commands hand their Result here and stop. The human/JSON branch happens once, at
the last moment, so --json costs nothing per command and can never drift from
what a person sees.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

from elva_cli.ui.renderables import render

if TYPE_CHECKING:
    from rich.console import Console

    from elva_cli.errors import ElvaError


def as_data(result: object) -> Any:
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return dataclasses.asdict(result)
    msg = f"Results must be dataclasses, got {type(result).__name__}"
    raise TypeError(msg)


class Output:
    def __init__(self, *, stdout: Console, stderr: Console, json_mode: bool, quiet: bool) -> None:
        self._out = stdout
        self._err = stderr
        self.json_mode = json_mode
        self.quiet = quiet

    def result(self, result: object) -> None:
        """Emit a command's payload. Exactly one call per command."""
        if self.json_mode:
            self._out.file.write(json.dumps(as_data(result), indent=2, default=str) + "\n")
            self._out.file.flush()
            return
        self._out.print(render(result), soft_wrap=True)

    def hint(self, message: str) -> None:
        self._err.print(message, style="elva.dim")

    def warn(self, message: str) -> None:
        self._err.print(f"warning: {message}", style="elva.warn")

    def error(self, error: ElvaError) -> None:
        write_error(self._err, error)


def write_error(console: Console, error: ElvaError) -> None:
    console.print(f"{error.code}: {error.message}", style="elva.error", soft_wrap=True)
    if error.hint:
        console.print(f"  -> {error.hint}", style="elva.dim", soft_wrap=True)


def report_error(error: ElvaError, *, color: bool | None = None) -> None:
    """Render an error when no Ctx exists, which is the case in the boundary."""
    from elva_cli.ui.console import build_consoles

    _, err = build_consoles(color=color, quiet=False)
    write_error(err, error)
