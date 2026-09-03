from __future__ import annotations

from pathlib import Path

import pytest

from elva_cli.context import CI_VARS, Ctx, GlobalOptions


def build(env: dict[str, str] | None = None, *, tty: bool | None = None) -> Ctx:
    return Ctx(GlobalOptions(), cwd=Path("/"), env=env or {}, tty=tty)


@pytest.mark.parametrize("var", CI_VARS)
def test_each_known_ci_variable_is_detected(var: str) -> None:
    assert build({var: "true"}).is_ci is True


def test_no_ci_variables_means_not_ci() -> None:
    assert build().is_ci is False


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "FALSE", " off "])
def test_falsey_ci_values_do_not_count(value: str) -> None:
    assert build({"CI": value}).is_ci is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "anything"])
def test_truthy_ci_values_count(value: str) -> None:
    assert build({"CI": value}).is_ci is True


def test_a_tty_outside_ci_is_interactive() -> None:
    assert build(tty=True).interactive is True


def test_no_tty_is_not_interactive() -> None:
    assert build(tty=False).interactive is False


def test_ci_beats_a_tty() -> None:
    assert build({"CI": "1"}, tty=True).interactive is False


def test_json_beats_a_tty() -> None:
    ctx = Ctx(GlobalOptions(json_output=True), cwd=Path("/"), env={}, tty=True)
    assert ctx.interactive is False


def test_quiet_does_not_make_it_non_interactive() -> None:
    """--quiet lowers the noise floor, it does not say nobody is there."""
    ctx = Ctx(GlobalOptions(quiet=True), cwd=Path("/"), env={}, tty=True)
    assert ctx.interactive is True
