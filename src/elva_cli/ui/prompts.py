"""Prompts that always have a non-interactive equivalent.

Every helper takes the flag value first. If it was supplied, nothing is asked. If
it was not and there is nobody to ask, the result is a usage error rather than a
hang, because a CLI that blocks waiting for input in CI is the worst failure mode
there is.

These live in ui/ so nothing under core/ can reach them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from elva_cli.context import Ctx


def _refuse(flag: str) -> UsageError:
    return UsageError(
        f"{flag} is required when there is no terminal to prompt on",
        hint=f"Pass {flag} on the command line, or run this in an interactive shell.",
    )


def text(
    value: str | None,
    *,
    prompt: str,
    flag: str,
    ctx: Ctx,
    default: str | None = None,
) -> str:
    if value is not None:
        return value
    if not ctx.interactive:
        raise _refuse(flag)

    import questionary

    answer = questionary.text(prompt, default=default or "").unsafe_ask()
    return "" if answer is None else str(answer)


def select(
    value: str | None,
    *,
    prompt: str,
    choices: Sequence[str],
    flag: str,
    ctx: Ctx,
) -> str:
    if value is not None:
        if value not in choices:
            raise UsageError(
                f"{value!r} is not a valid value for {flag}",
                hint=f"Choose one of: {', '.join(choices)}",
            )
        return value
    if not ctx.interactive:
        raise _refuse(flag)

    import questionary

    answer = questionary.select(prompt, choices=list(choices)).unsafe_ask()
    if answer is None:
        raise UsageError(f"nothing was chosen for {flag}")
    return str(answer)


def confirm(
    value: bool | None,
    *,
    prompt: str,
    ctx: Ctx,
    default: bool = False,
) -> bool:
    """Ask for a yes or no. --yes answers every one of these without asking."""
    if value is not None:
        return value
    if ctx.assume_yes:
        return True
    if not ctx.interactive:
        raise UsageError(
            f"cannot ask for confirmation: {prompt}",
            hint="Pass --yes to confirm without prompting.",
        )

    import questionary

    return bool(questionary.confirm(prompt, default=default).unsafe_ask())


def secret(
    value: str | None,
    *,
    prompt: str,
    source: str,
    ctx: Ctx,
) -> str:
    """Ask for a credential, without echoing it and without a flag equivalent.

    There is deliberately no `--...` to pass one of these on. argv is readable
    by every process on the machine and lands in shell history, so a secret on
    a command line outlives the command. `source` names the environment
    variable to set instead when there is nobody to ask.

    An answer of None is end-of-input rather than an empty key, and the caller
    should not be handed the string "None".
    """
    if value is not None:
        return value
    if not ctx.interactive:
        raise UsageError(
            f"{source} is required when there is no terminal to prompt on",
            hint=f"Set {source}, or pipe the value in on stdin. Never pass it as a flag.",
        )

    import questionary

    answer = questionary.password(prompt).unsafe_ask()
    if answer is None:
        raise UsageError(f"no value was entered for {source}")
    return str(answer)
