from __future__ import annotations

from rich.table import Table  # noqa: TC002
from rich.text import Text

from elva_cli.core.services.mcp_result import McpListResult, McpShowResult  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render, table


@render.register
def _(result: McpListResult) -> Table | Text:
    if not result.servers:
        return Text("No MCP servers in this workspace.", style="elva.dim")
    return table(
        ["SLUG", "NAME", "STATUS", "TOOLS", "COLLECTION"],
        [
            (
                s.slug,
                s.name,
                s.status,
                str(s.tool_count),
                s.collection_id or "",
            )
            for s in result.servers
        ],
    )


@render.register
def _(result: McpShowResult) -> Text:
    s = result.server
    status_note = (
        Text("not serving traffic", style="elva.warn") if s.status == "draft" else Text("")
    )
    if s.has_secret is None:
        secret_note = Text("n/a")
    else:
        secret_note = Text("set") if s.has_secret else Text("not set")
    rows = [
        ("Slug", Text(s.slug), Text("")),
        ("Name", Text(s.name), Text("")),
        ("Status", Text(s.status), status_note),
        ("Deployment", Text(s.deployment_id or ""), Text("")),
        ("Version", Text(s.version or ""), Text("")),
        ("Auth type", Text(s.auth_type or ""), Text("")),
        ("Secret", secret_note, Text("")),
        ("Operations", Text(str(len(s.selected_operations or ()))), Text("")),
        ("Collection", Text(s.collection_name or s.collection_id or ""), Text("")),
        ("URL", Text(s.runtime_url or "", style="elva.accent"), Text("")),
    ]
    return aligned_rows(rows)
