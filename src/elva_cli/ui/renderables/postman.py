from __future__ import annotations

from rich.console import Group
from rich.text import Text

from elva_cli.core.services.postman_result import (  # noqa: TC001
    PostmanCollectionList,
    PostmanImportResult,
)
from elva_cli.ui.renderables.base import aligned_rows, render


@render.register
def _(result: PostmanCollectionList) -> Group:
    if not result.collections:
        return Group(
            Text("That Postman API key cannot see any collections.", style="elva.warn"),
            Text(""),
            Text(
                "Check the key's workspace access at https://postman.co/settings/me/api-keys.",
                style="elva.dim",
            ),
        )

    count = len(result.collections)
    headline = Text(
        f"{count} Postman {'collection' if count == 1 else 'collections'}.",
        style="elva.accent",
    )
    rows = [
        (
            item.name,
            Text(item.uid, style="elva.dim"),
            Text(_day(item.updated_at), style="elva.origin"),
        )
        for item in result.collections
    ]
    return Group(
        headline,
        Text(""),
        aligned_rows(rows),
        Text(""),
        Text("Import one with: elva import postman <name or id>", style="elva.dim"),
    )


@render.register
def _(result: PostmanImportResult) -> Group:
    same_name = result.postman_collection in (None, result.collection)
    origin = "Postman" if same_name else f"Postman collection {result.postman_collection!r}"
    headline = Text(f"Created {result.collection!r} from {origin}.", style="elva.ok")

    rows = [("workspace", Text(result.workspace), Text(""))]
    if result.endpoints is not None:
        rows.append(("endpoints", Text(str(result.endpoints)), Text("")))
    rows.append(("postman id", Text(result.postman_uid, style="elva.dim"), Text("")))
    rows.append(("collection id", Text(result.collection_id, style="elva.dim"), Text("")))
    if result.url is not None:
        rows.append(("url", Text(result.url, style="elva.accent"), Text("")))

    body = [headline, Text(""), aligned_rows(rows)]

    if result.endpoints == 0:
        body += [
            Text(""),
            Text(
                "No endpoints were found. The collection imported, but Elva could "
                "not read any requests out of it — check it is not empty in Postman.",
                style="elva.warn",
            ),
        ]

    return Group(*body)


def _day(timestamp: str | None) -> str:
    """Just the date out of an ISO timestamp. The time of day is noise in a
    list somebody is scanning for a name, and a value this cannot parse is
    shown as it arrived rather than dropped."""
    if not timestamp:
        return ""
    head = timestamp[:10]
    return head if len(timestamp) > 10 and timestamp[10:11] in ("T", " ") else timestamp
