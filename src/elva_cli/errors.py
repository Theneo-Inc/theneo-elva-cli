"""Error taxonomy and the exit-code contract.

Exit codes are a public API that pipelines branch on. Never renumber a shipped
value, and never collapse VALIDATION into UNEXPECTED, callers rely on the
difference between "your spec is wrong" and "the tool broke".

Every ElvaError carries a stable machine code, a human message, and where one
exists, the next action to take. Anything that escapes as a bare Exception is a
"""

from __future__ import annotations

import enum


class ExitCode(enum.IntEnum):
    """Process exit statuses. Documented in docs/exit-codes.md."""

    OK = 0
    UNEXPECTED = 1
    USAGE = 2
    AUTH = 3
    VALIDATION = 4
    API = 5
    INTERRUPTED = 130


class ElvaError(Exception):
    """Base class for every failure the user is meant to see."""

    code: str = "ELVA_ERROR"
    exit_code: ExitCode = ExitCode.UNEXPECTED
    default_hint: str | None = None

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        code: str | None = None,
        exit_code: ExitCode | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = self.default_hint if hint is None else hint
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code

    def __str__(self) -> str:
        return self.message


class UsageError(ElvaError):
    """The command was invoked wrongly, or needs an answer it cannot ask for."""

    code = "ELVA_USAGE"
    exit_code = ExitCode.USAGE
    default_hint = "Run 'elva --help' to see the available commands and options."


class ConfigError(ElvaError):
    """Configuration is missing or malformed."""

    code = "ELVA_CONFIG"
    exit_code = ExitCode.USAGE


class AuthError(ElvaError):
    """Not authenticated, or the stored credentials no longer work."""

    code = "ELVA_AUTH"
    exit_code = ExitCode.AUTH
    default_hint = "Run 'elva auth login' to sign in."


class ValidationError(ElvaError):
    """The input spec is invalid. The CLI itself worked correctly."""

    code = "ELVA_VALIDATION"
    exit_code = ExitCode.VALIDATION


class ApiError(ElvaError):
    """The Elva API could not be reached, or returned a server error."""

    code = "ELVA_API"
    exit_code = ExitCode.API
    default_hint = "Check your connection and try again."
