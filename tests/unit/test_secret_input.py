"""How a Postman API key is allowed to reach the CLI.

The rule this file exists to hold: never as a flag value. argv is readable by
every other process on the machine (`ps`, /proc) and a shell writes it to
history, so a secret passed that way outlives the command that used it. The
supported ways in are the environment, a hidden prompt, and stdin.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import typer.main

from elva_cli.commands import import_ as command
from elva_cli.context import Ctx, GlobalOptions
from elva_cli.errors import ExitCode, UsageError

SECRET_NAMES = ("key", "token", "secret", "password", "credential", "apikey")


def ctx(*, tty: bool = False, **env: str) -> Ctx:
    return Ctx(GlobalOptions(), cwd=Path("/"), env=env, tty=tty)


def params() -> list[Any]:
    group = typer.main.get_command(command.app)
    postman = group.commands["postman"]  # type: ignore[attr-defined]
    return list(postman.params)


class TestNoFlagCarriesTheKey:
    def test_the_command_was_actually_found(self) -> None:
        assert params(), "the postman command has no parameters, the walk is broken"

    def test_no_parameter_that_takes_a_value_is_named_like_a_secret(self) -> None:
        """--key-stdin is a switch: it says where to read from, it is not the
        key. Anything that takes a value must not be one either."""
        offenders = [
            param.name
            for param in params()
            if not getattr(param, "is_flag", False)
            and any(word in (param.name or "") for word in SECRET_NAMES)
        ]
        assert offenders == []

    def test_the_key_stdin_switch_takes_no_value(self) -> None:
        switch = next(param for param in params() if param.name == "key_stdin")
        assert getattr(switch, "is_flag", False)

    def test_no_parameter_is_bound_to_the_key_environment_variable(self) -> None:
        """Typer's envvar= would also mint a flag for it. The variable is read
        explicitly instead, in read_api_key."""
        for param in params():
            assert getattr(param, "envvar", None) != command.ENV_POSTMAN_KEY


class TestReadApiKey:
    def test_the_environment_answers_without_asking(self) -> None:
        got = command.read_api_key(ctx(tty=True, ELVA_POSTMAN_API_KEY="PMAK-abc"), from_stdin=False)
        assert got == "PMAK-abc"

    def test_nothing_set_and_nobody_to_ask_is_usage(self) -> None:
        with pytest.raises(UsageError, match="ELVA_POSTMAN_API_KEY is required") as caught:
            command.read_api_key(ctx(tty=False), from_stdin=False)
        assert caught.value.exit_code == ExitCode.USAGE

    def test_key_stdin_beats_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Someone who piped a key in meant that one."""
        monkeypatch.setattr("sys.stdin", io.StringIO("PMAK-piped\n"))
        got = command.read_api_key(ctx(tty=True, ELVA_POSTMAN_API_KEY="PMAK-env"), from_stdin=True)
        assert got == "PMAK-piped"

    @pytest.mark.parametrize(
        ("piped", "expected"),
        [
            pytest.param("PMAK-abc\n", "PMAK-abc", id="unix-newline"),
            pytest.param("PMAK-abc\r\n", "PMAK-abc", id="windows-newline"),
            pytest.param("PMAK-abc", "PMAK-abc", id="no-newline"),
            pytest.param("", "", id="nothing-piped"),
        ],
    )
    def test_only_the_first_line_is_taken(
        self, monkeypatch: pytest.MonkeyPatch, piped: str, expected: str
    ) -> None:
        """The newline a shell adds is not part of the key, and the rest of
        the stream is not ours to consume."""
        rest = "leftover\n" if piped.endswith("\n") else ""
        monkeypatch.setattr("sys.stdin", io.StringIO(piped + rest))
        assert command.read_stdin_line() == expected

    def test_key_stdin_on_a_terminal_is_refused_rather_than_echoed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        monkeypatch.setattr("sys.stdin", Tty("typed-in-the-clear\n"))
        with pytest.raises(UsageError, match="nothing piped into it"):
            command.read_stdin_line()


class TestSecretPrompt:
    def test_a_supplied_value_is_not_asked_for(self) -> None:
        from elva_cli.ui import prompts

        got = prompts.secret("given", prompt="?", source="ELVA_X", ctx=ctx(tty=True))
        assert got == "given"

    def test_without_a_terminal_it_names_the_variable_to_set(self) -> None:
        from elva_cli.ui import prompts

        with pytest.raises(UsageError) as caught:
            prompts.secret(None, prompt="?", source="ELVA_X", ctx=ctx(tty=False))
        assert "ELVA_X" in (caught.value.hint or "")
        assert "flag" in (caught.value.hint or "")

    def test_end_of_input_is_not_answered_with_the_string_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """questionary returns None on end-of-input. str(None) would hand the
        caller a four-character 'key' and a confusing 401."""
        from elva_cli.ui import prompts

        class Answer:
            def unsafe_ask(self) -> None:
                return None

        monkeypatch.setattr("questionary.password", lambda *a, **k: Answer())
        with pytest.raises(UsageError, match="no value was entered"):
            prompts.secret(None, prompt="?", source="ELVA_X", ctx=ctx(tty=True))
