from __future__ import annotations

from pathlib import Path  # noqa: TC003

import typer

from elva_cli.context import get_ctx

app = typer.Typer(
    name="import",
    help="Import an API spec into a collection.",
    no_args_is_help=True,
)

STDIN = "-"


@app.callback()
def main() -> None:
    """Keeps `import` a command group for future `import github` subcommands."""


@app.command("spec")
def spec(
    click_ctx: typer.Context,
    file: Path | None = typer.Argument(
        None,
        metavar="[FILE]",
        help="OpenAPI document to upload, or - to read one from stdin.",
    ),
    url: str | None = typer.Option(
        None, "--url", metavar="URL", help="Have Elva fetch the spec from here instead."
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        metavar="NAME",
        help="Name for the new collection. Defaults to the spec's info.title.",
    ),
    update: bool = typer.Option(
        False,
        "--update",
        help="Replace the spec of the existing --collection instead of creating one.",
    ),
    format_: str | None = typer.Option(
        None,
        "--format",
        metavar="FORMAT",
        help="Skip detection and say what the file is: openapi or postman.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would be imported without sending anything."
    ),
) -> None:
    """Create a collection from an OpenAPI document.

    Reads a local file, stdin, or a URL Elva fetches itself. Creating is the
    default; --update replaces the spec of the collection named by --collection.
    """
    from elva_cli.core.services.import_spec import import_spec
    from elva_cli.ui import prompts

    ctx = get_ctx(click_ctx)

    stdin: bytes | None = None
    path: Path | None = file
    if file is not None and str(file) == STDIN:
        path = None
        stdin = read_stdin()

    result = import_spec(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        path=path,
        stdin=stdin,
        spec_url=url,
        name=name,
        prompt_for_name=lambda: prompts.text(
            None, prompt="Name for the new collection", flag="--name", ctx=ctx
        ),
        collection=ctx.settings.collection,
        update=update,
        spec_format=format_,
        dry_run=dry_run,
    )
    ctx.out.result(result)


def read_stdin() -> bytes:
    """The spec piped in. Commands own the stdin boundary; nothing below them
    reads a stream."""
    import sys

    return sys.stdin.buffer.read()
