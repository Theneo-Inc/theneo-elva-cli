"""Versioned command discovery without authentication or subprocess help parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import typer
from rich.text import Text

from elva_cli.context import get_ctx
from elva_cli.ui.renderables.base import render

app = typer.Typer(name="schema", add_completion=False)


@dataclass(frozen=True)
class CommandSchema:
    version: int
    commands: list[dict[str, Any]]
    exit_codes: dict[str, int]


@render.register
def _render(result: CommandSchema) -> Text:
    import dataclasses
    import json

    return Text(json.dumps(dataclasses.asdict(result), indent=2))


@app.command()
def schema(click_ctx: typer.Context) -> None:
    """Describe commands, arguments, options and exit codes as a versioned schema."""
    from typer._click.core import Context
    from typer.core import TyperArgument, TyperGroup
    from typer.main import get_command

    from elva_cli.errors import ExitCode
    from elva_cli.main import app as root_app

    commands: list[dict[str, Any]] = []

    def visit(command: Any, path: str) -> None:
        commands.append(
            {
                "command": path,
                "help": command.help or "",
                "parameters": [
                    {
                        "name": p.name,
                        "kind": "argument" if isinstance(p, TyperArgument) else "option",
                        "options": []
                        if isinstance(p, TyperArgument)
                        else [*p.opts, *p.secondary_opts],
                        "is_flag": getattr(p, "is_flag", False),
                        "default": p.default if not callable(p.default) else None,
                        "envvar": p.envvar,
                        "required": p.required,
                        "multiple": p.multiple,
                        "nargs": p.nargs,
                        "type": p.type.name,
                        "choices": getattr(p.type, "choices", None),
                        "help": getattr(p, "help", None),
                    }
                    for p in command.params
                    if not getattr(p, "hidden", False)
                ],
            }
        )
        if isinstance(command, TyperGroup):
            context = Context(command)
            for name in command.list_commands(context):
                child = command.get_command(context, name)
                if child:
                    visit(child, f"{path} {name}")

    visit(get_command(root_app), "elva")
    get_ctx(click_ctx).out.result(
        CommandSchema(
            1,
            commands,
            {code.name.lower(): int(code) for code in ExitCode},
        )
    )
