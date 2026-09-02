"""The Ctx object, built once in the root callback and passed to every command.

Commands read settings from here instead of touching the environment or the
filesystem themselves, so configuration is resolved in exactly one place.

Resolution is a cached_property because it pulls in pydantic. `elva --version`
must not pay for that.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from elva_cli.errors import ElvaError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import typer
    from rich.console import Console

    from elva_cli.settings.loader import Resolution
    from elva_cli.settings.models import Settings
    from elva_cli.ui.output import Output


@dataclass(frozen=True)
class GlobalOptions:
    profile: str | None = None
    base_url: str | None = None
    workspace: str | None = None
    collection: str | None = None
    json_output: bool = False
    quiet: bool = False
    color: bool | None = None


class Ctx:
    def __init__(self, options: GlobalOptions, *, cwd: Path, env: Mapping[str, str]) -> None:
        self.options = options
        self.cwd = cwd
        self.env = env

    @property
    def color(self) -> bool | None:
        """NO_COLOR wins over everything except an explicit --color."""
        if self.options.color is None and self.env.get("NO_COLOR"):
            return False
        return self.options.color

    @cached_property
    def consoles(self) -> tuple[Console, Console]:
        from elva_cli.ui.console import build_consoles

        return build_consoles(color=self.color, quiet=self.options.quiet)

    @cached_property
    def out(self) -> Output:
        from elva_cli.ui.output import Output

        stdout, stderr = self.consoles
        return Output(
            stdout=stdout,
            stderr=stderr,
            json_mode=self.options.json_output,
            quiet=self.options.quiet,
        )

    @cached_property
    def resolution(self) -> Resolution:
        from elva_cli.settings.loader import resolve

        return resolve(
            overrides={
                "profile": self.options.profile,
                "base_url": self.options.base_url,
                "workspace": self.options.workspace,
                "collection": self.options.collection,
            },
            env=self.env,
            cwd=self.cwd,
        )

    @property
    def settings(self) -> Settings:
        return self.resolution.settings


def get_ctx(click_ctx: typer.Context) -> Ctx:
    ctx = click_ctx.obj
    if not isinstance(ctx, Ctx):
        msg = "no Ctx on the context; the root callback did not run"
        raise ElvaError(msg)
    return ctx
