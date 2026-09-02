from __future__ import annotations

import pytest

from elva_cli.errors import (
    ApiError,
    AuthError,
    ConfigError,
    ElvaError,
    ExitCode,
    UsageError,
    ValidationError,
)

EVERY_ERROR = [ElvaError, UsageError, ConfigError, AuthError, ValidationError, ApiError]


@pytest.mark.parametrize("cls", EVERY_ERROR)
def test_every_error_carries_a_code_and_message(cls: type[ElvaError]) -> None:
    error = cls("something went wrong")
    assert error.message == "something went wrong"
    assert str(error) == "something went wrong"
    assert error.code.startswith("ELVA_")
    assert isinstance(error.exit_code, ExitCode)


@pytest.mark.parametrize("cls", EVERY_ERROR)
def test_every_error_is_catchable_as_elva_error(cls: type[ElvaError]) -> None:
    with pytest.raises(ElvaError):
        raise cls("boom")


def test_subclass_codes_and_exit_codes() -> None:
    assert (UsageError("x").code, UsageError("x").exit_code) == ("ELVA_USAGE", ExitCode.USAGE)
    assert (ConfigError("x").code, ConfigError("x").exit_code) == ("ELVA_CONFIG", ExitCode.USAGE)
    assert (AuthError("x").code, AuthError("x").exit_code) == ("ELVA_AUTH", ExitCode.AUTH)
    assert (ValidationError("x").code, ValidationError("x").exit_code) == (
        "ELVA_VALIDATION",
        ExitCode.VALIDATION,
    )
    assert (ApiError("x").code, ApiError("x").exit_code) == ("ELVA_API", ExitCode.API)


def test_default_hint_supplies_a_next_action() -> None:
    assert AuthError("session expired").hint == "Run 'elva auth login' to sign in."
    assert UsageError("bad flag").hint is not None
    assert ApiError("timed out").hint is not None


def test_explicit_hint_overrides_the_default() -> None:
    assert AuthError("nope", hint="Set ELVA_TOKEN.").hint == "Set ELVA_TOKEN."


def test_hint_can_be_specific_where_no_default_makes_sense() -> None:
    assert ValidationError("bad spec").hint is None
    assert ValidationError("bad spec", hint="Fix line 12.").hint == "Fix line 12."


def test_code_and_exit_code_can_be_overridden_per_instance() -> None:
    error = ElvaError("odd", code="ELVA_WEIRD", exit_code=ExitCode.API)
    assert error.code == "ELVA_WEIRD"
    assert error.exit_code == ExitCode.API


def test_overriding_an_instance_does_not_mutate_the_class() -> None:
    ElvaError("odd", code="ELVA_WEIRD", exit_code=ExitCode.API)
    assert ElvaError("plain").code == "ELVA_ERROR"
    assert ElvaError("plain").exit_code == ExitCode.UNEXPECTED
