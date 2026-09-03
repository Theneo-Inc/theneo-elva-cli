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

    return str(questionary.text(prompt, default=default or "").unsafe_ask())


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

    return str(questionary.select(prompt, choices=list(choices)).unsafe_ask())


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
