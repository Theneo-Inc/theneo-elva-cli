"""Lazy command dispatch.

Only the command a user actually typed gets imported. That keeps `elva --version`
away from pydantic, httpx and anything else a command pulls in.

Adding a command means adding a line here.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from typer.core import TyperGroup

if TYPE_CHECKING:
    from typer._click.core import Command, Context


@dataclass(frozen=True)
class Lazy:
    module: str
    help: str


class LazyGroup(TyperGroup):
    commands_: ClassVar[dict[str, Lazy]] = {
        "auth": Lazy("elva_cli.commands.auth", "Sign in and manage credentials."),
        "config": Lazy("elva_cli.commands.config", "Inspect resolved configuration."),
        "whoami": Lazy("elva_cli.commands.whoami", "Show who you're signed in as."),
    }

    def list_commands(self, ctx: Context) -> list[str]:
        return sorted({*super().list_commands(ctx), *self.commands_})

    def get_command(self, ctx: Context, cmd_name: str) -> Command | None:
        lazy = self.commands_.get(cmd_name)
        if lazy is None:
            return super().get_command(ctx, cmd_name)

        import typer.main

        module = importlib.import_module(lazy.module)
        command = typer.main.get_command(module.app)
        command.name = cmd_name
        command.short_help = lazy.help
        return command
