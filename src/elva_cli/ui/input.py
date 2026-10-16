"""Bounded piped input for commands accepting a file or stdin."""

from __future__ import annotations

import sys

from elva_cli.errors import UsageError


def read_stdin(*, max_bytes: int) -> bytes:
    if sys.stdin.isatty():
        raise UsageError(
            "No input is piped to stdin.", hint="Pass a file path, or pipe data to '-'."
        )
    data = sys.stdin.buffer.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UsageError(f"Piped input exceeds the {max_bytes}-byte limit.")
    return data
