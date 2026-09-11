from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from elva_cli.context import Ctx
    from elva_cli.core.services.postman_result import PostmanCollection

app = typer.Typer(
    name="import",
    help="Import an API into a collection.",
    no_args_is_help=True,
)

STDIN = "-"

ENV_POSTMAN_KEY = "ELVA_POSTMAN_API_KEY"


@app.callback()
def main() -> None:
    """Keeps `import` a command group rather than a single command."""


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


@app.command("postman")
def postman(
    click_ctx: typer.Context,
    collection: str | None = typer.Argument(
        None,
        metavar="[COLLECTION]",
        help="Postman collection to import, by name or by id. Asked for if omitted.",
    ),
    list_only: bool = typer.Option(
        False,
        "--list",
        help="List the collections the key can see and stop, without importing.",
    ),
    key_stdin: bool = typer.Option(
        False,
        "--key-stdin",
        help="Read the Postman API key from the first line of stdin.",
    ),
) -> None:
    """Create a collection from one in Postman.

    The Postman API key is never taken from the command line: argv is readable
    by every process on the machine and lands in shell history. It comes from
    ELVA_POSTMAN_API_KEY, a hidden prompt, or --key-stdin.
    """
    from elva_cli.core.services import import_postman as service

    ctx = get_ctx(click_ctx)

    if list_only and collection is not None:
        raise UsageError(
            "--list does not take a COLLECTION",
            hint="Run 'elva import postman --list' to see them, then name one to import it.",
        )

    api_key = read_api_key(ctx, from_stdin=key_stdin)

    if list_only:
        ctx.out.result(
            service.list_postman_collections(
                base_url=ctx.settings.base_url,
                workspace=ctx.settings.workspace,
                api_key=api_key,
            )
        )
        return

    result = service.import_postman(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        api_key=api_key,
        collection=collection,
        choose=(lambda found: pick_collection(found, ctx)) if ctx.interactive else None,
    )
    ctx.out.result(result)


def read_api_key(ctx: Ctx, *, from_stdin: bool) -> str:
    """The Postman API key, from stdin, the environment, or a hidden prompt.

    There is deliberately no flag that carries the value. An explicit
    --key-stdin wins over the environment, because someone who piped a key in
    meant that one; otherwise a set variable answers without asking.
    """
    from elva_cli.ui import prompts

    if from_stdin:
        return read_stdin_line()
    return prompts.secret(
        ctx.env.get(ENV_POSTMAN_KEY),
        prompt="Postman API key",
        source=ENV_POSTMAN_KEY,
        ctx=ctx,
    )


def pick_collection(found: Sequence[PostmanCollection], ctx: Ctx) -> PostmanCollection:
    """Ask which collection to import.

    Labels carry the id as well as the name, so two collections sharing a name
    are still telling apart -- and so the answer maps back to exactly one row.
    """
    from elva_cli.ui import prompts

    labels = [f"{item.name}  ({item.uid})" for item in found]
    picked = prompts.select(
        None,
        prompt="Which Postman collection?",
        choices=labels,
        flag="COLLECTION",
        ctx=ctx,
    )
    return found[labels.index(picked)]


def read_stdin() -> bytes:
    """The spec piped in. Commands own the stdin boundary; nothing below them
    reads a stream."""
    import sys

    return sys.stdin.buffer.read()


def read_stdin_line() -> str:
    """The API key piped in.

    One line only: the rest of the stream is not ours to consume, and the
    newline a shell adds is not part of the key. A terminal is refused rather
    than read, because typing a secret into a plain read echoes it.
    """
    import sys

    if sys.stdin.isatty():
        raise UsageError(
            "--key-stdin has nothing piped into it",
            hint=f"Pipe the key in, set {ENV_POSTMAN_KEY}, or drop the flag to be asked for it.",
        )
    try:
        line = sys.stdin.readline()
    except UnicodeDecodeError as exc:
        raise UsageError(
            "what was piped into --key-stdin is not text",
            hint="A Postman API key is a single line of ASCII.",
        ) from exc
    return line.rstrip("\r\n")
