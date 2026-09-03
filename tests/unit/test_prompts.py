from __future__ import annotations

from pathlib import Path

import pytest

from elva_cli.context import Ctx, GlobalOptions
from elva_cli.errors import UsageError
from elva_cli.ui import prompts


def ctx(*, tty: bool = False, yes: bool = False, json_output: bool = False, **env: str) -> Ctx:
    return Ctx(
        GlobalOptions(assume_yes=yes, json_output=json_output),
        cwd=Path("/"),
        env=env,
        tty=tty,
    )


def test_text_returns_the_flag_value() -> None:
    assert prompts.text("given", prompt="?", flag="--name", ctx=ctx(tty=True)) == "given"


def test_select_returns_the_flag_value() -> None:
    got = prompts.select("b", prompt="?", choices=["a", "b"], flag="--pick", ctx=ctx(tty=True))
    assert got == "b"


def test_confirm_returns_the_flag_value() -> None:
    assert prompts.confirm(False, prompt="sure?", ctx=ctx(tty=True, yes=True)) is False


def test_select_rejects_a_value_outside_the_choices() -> None:
    with pytest.raises(UsageError, match="not a valid value"):
        prompts.select("z", prompt="?", choices=["a", "b"], flag="--pick", ctx=ctx(tty=True))


def test_text_without_a_tty_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="--name is required") as caught:
        prompts.text(None, prompt="?", flag="--name", ctx=ctx(tty=False))
    assert caught.value.exit_code == 2


def test_select_without_a_tty_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="--pick is required"):
        prompts.select(None, prompt="?", choices=["a"], flag="--pick", ctx=ctx(tty=False))


def test_confirm_without_a_tty_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="cannot ask for confirmation") as caught:
        prompts.confirm(None, prompt="delete it?", ctx=ctx(tty=False))
    assert caught.value.exit_code == 2


def test_confirm_error_points_at_the_yes_flag() -> None:
    with pytest.raises(UsageError) as caught:
        prompts.confirm(None, prompt="delete it?", ctx=ctx(tty=False))
    assert "--yes" in (caught.value.hint or "")


def test_yes_answers_confirmations_without_asking() -> None:
    assert prompts.confirm(None, prompt="delete it?", ctx=ctx(tty=False, yes=True)) is True


def test_yes_does_not_invent_answers_for_value_prompts() -> None:
    """--yes covers confirmations only. It cannot guess a workspace name."""
    with pytest.raises(UsageError):
        prompts.text(None, prompt="?", flag="--name", ctx=ctx(tty=False, yes=True))


def test_ci_is_never_interactive_even_on_a_tty() -> None:
    with pytest.raises(UsageError):
        prompts.text(None, prompt="?", flag="--name", ctx=ctx(tty=True, CI="true"))


def test_json_mode_is_never_interactive() -> None:
    with pytest.raises(UsageError):
        prompts.text(None, prompt="?", flag="--name", ctx=ctx(tty=True, json_output=True))
