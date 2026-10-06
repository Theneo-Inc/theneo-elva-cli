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
        "agent": Lazy(
            "elva_cli.commands.agent", "Build MCPs with your own agent; upload only API artifacts."
        ),
        "schema": Lazy("elva_cli.commands.schema", "Discover the CLI command schema."),
        "apply": Lazy("elva_cli.commands.apply", "Apply or resume a reviewed AI plan."),
        "plan": Lazy("elva_cli.commands.plan", "Inspect and resume AI planning jobs."),
        "auth": Lazy("elva_cli.commands.auth", "Sign in and manage credentials."),
        "collection": Lazy("elva_cli.commands.collection", "Inspect collections in a workspace."),
        "config": Lazy("elva_cli.commands.config", "Inspect resolved configuration."),
        "contract": Lazy("elva_cli.commands.contract", "Manage API contracts and releases."),
        "import": Lazy("elva_cli.commands.import_", "Import an API into a collection."),
        "insights": Lazy("elva_cli.commands.insights", "Review API quality and security."),
        "mcp": Lazy("elva_cli.commands.mcp", "Manage MCP servers."),
        "repo": Lazy("elva_cli.commands.repo", "Connect and sync GitHub repositories."),
        "whoami": Lazy("elva_cli.commands.whoami", "Show who you're signed in as."),
        "workspace": Lazy("elva_cli.commands.workspace", "Manage workspaces."),
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
