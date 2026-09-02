"""The exit-code contract.

These assertions exist to fail loudly if anyone renumbers a shipped code. Exit
codes are a public API: CI pipelines and agents branch on them, so changing one
breaks callers we cannot see.
"""

from __future__ import annotations

from elva_cli.errors import ExitCode


def test_exact_values_are_frozen() -> None:
    assert ExitCode.OK.value == 0
    assert ExitCode.UNEXPECTED.value == 1
    assert ExitCode.USAGE.value == 2
    assert ExitCode.AUTH.value == 3
    assert ExitCode.VALIDATION.value == 4
    assert ExitCode.API.value == 5
    assert ExitCode.INTERRUPTED.value == 130


def test_validation_is_distinct_from_unexpected() -> None:
    """The whole point of code 4: "your spec is wrong" != "the tool broke"."""
    assert len({ExitCode.VALIDATION.value, ExitCode.UNEXPECTED.value}) == 2


def test_values_are_unique() -> None:
    values = [code.value for code in ExitCode]
    assert len(values) == len(set(values))


def test_codes_are_valid_posix_statuses() -> None:
    assert all(0 <= code.value <= 255 for code in ExitCode)
