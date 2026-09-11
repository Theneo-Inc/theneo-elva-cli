"""Resolve a secret flag's value from somewhere other than argv.

A `--client-secret VALUE` flag would sit in shell history and process
listings for as long as the shell keeps them, so this package never accepts
one directly -- only a reference to where the real value lives. Lives in
`ui/` alongside the rest of this package's stdin/env boundary (see
`commands/import_.py`'s `read_stdin` for the same reasoning).
"""

from __future__ import annotations

import os
from pathlib import Path

from elva_cli.errors import UsageError


def read_secret(ref: str, *, flag: str) -> str:
    """`ref` is `env:NAME`, `file:PATH`, or `-` for stdin"""
    if ref == "-":
        import sys

        value: str | None = sys.stdin.read().strip()
    elif ref.startswith("env:"):
        name = ref.removeprefix("env:")
        value = os.environ.get(name)
        if value is None:
            raise UsageError(f"{flag}: environment variable {name!r} is not set")
    elif ref.startswith("file:"):
        path = Path(ref.removeprefix("file:"))
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise UsageError(f"{flag}: no such file: {path}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"{flag}: cannot read {path}: {exc}") from exc
    else:
        raise UsageError(
            f"{flag} does not accept a plain value",
            hint="Use env:NAME, file:PATH, or - for stdin -- never the secret itself.",
        )

    if not value:
        raise UsageError(f"{flag} resolved to an empty value")
    return value
