from __future__ import annotations

from rich.console import Group
from rich.text import Text

from elva_cli.core.services.import_result import DryRunResult, ImportSpecResult  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render


def _spec_rows(result: ImportSpecResult | DryRunResult) -> list[tuple[str, Text, Text]]:
    rows = [("format", Text(result.spec_format), Text(""))]
    if result.spec_title is not None:
        rows.append(("title", Text(result.spec_title), Text("")))
    if result.spec_version is not None:
        rows.append(("version", Text(result.spec_version), Text("")))
    if result.endpoints is not None:
        rows.append(("endpoints", Text(str(result.endpoints)), Text("")))
    return rows


@render.register
def _(result: ImportSpecResult) -> Group:
    headline = Text(
        f"{result.action.capitalize()} {result.collection!r} from {result.source}.",
        style="elva.ok",
    )

    rows = [("workspace", Text(result.workspace), Text("")), *_spec_rows(result)]
    rows.append(("collection id", Text(result.collection_id, style="elva.dim"), Text("")))
    if result.url is not None:
        rows.append(("url", Text(result.url, style="elva.accent"), Text("")))

    body = [headline, Text(""), aligned_rows(rows)]

    # A spec the backend cannot read lands as a successful import of nothing.
    # Exit 0 is the server's answer and the CLI does not overrule it, but a
    # silent zero is the one outcome a person needs told.
    if result.endpoints == 0:
        body += [
            Text(""),
            Text(
                "No endpoints were found. The file uploaded, but Elva could not "
                "read any operations out of it — check the spec is valid.",
                style="elva.warn",
            ),
        ]

    return Group(*body)


@render.register
def _(result: DryRunResult) -> Group:
    headline = Text(
        f"Would {result.action} {result.collection!r} from {result.source}.",
        style="elva.accent",
    )

    rows = _spec_rows(result)
    if result.size_bytes is not None:
        rows.append(("size", Text(f"{result.size_bytes / 1024:.1f} KB"), Text("")))

    return Group(
        headline,
        Text(""),
        aligned_rows(rows),
        Text(""),
        Text("Nothing was sent. Drop --dry-run to do it.", style="elva.dim"),
    )
