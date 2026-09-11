from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.text import Text

from elva_cli.core.services.mcp_create_result import McpCreateResult, McpDryRunResult  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render, secret_note, table

if TYPE_CHECKING:
    from rich.table import Table


@render.register
def _(result: McpCreateResult) -> Group:
    headline = _headline(result)
    status_note = (
        Text("not serving traffic", style="elva.warn") if result.status == "draft" else Text("")
    )
    rows = [
        ("Deployment", Text(result.deployment_id), Text("")),
        ("Slug", Text(result.slug), Text("")),
        ("Status", Text(result.status), status_note),
        ("Tools", Text(str(result.tool_count)), Text("")),
        ("Auth type", Text(result.auth_type), Text("")),
        ("Secret", secret_note(result.has_secret), Text("")),
        ("URL", Text(result.runtime_url or "", style="elva.accent"), Text("")),
    ]
    body = [headline, Text(""), aligned_rows(rows)]
    if result.status == "draft" and result.action == "create":
        body += [
            Text(""),
            Text(f"Publish it with: elva mcp publish {result.slug}", style="elva.dim"),
        ]
    return Group(*body)


def _headline(result: McpCreateResult) -> Text:
    if result.action == "publish":
        if result.already_published:
            return Text(f"{result.name!r} is already published.", style="elva.dim")
        return Text(f"Published {result.name!r}.", style="elva.ok")
    if result.status == "draft":
        return Text(f"Created {result.name!r} as a draft.", style="elva.ok")
    return Text(f"Created {result.name!r}.", style="elva.ok")


@render.register
def _(result: McpDryRunResult) -> Group:
    headline = Text(
        f"Would create an MCP server with {result.tool_count} tool(s).", style="elva.accent"
    )
    body: list[Text | Table] = [headline]
    if result.operations:
        rows = [
            (
                op.operation_key or f"{op.method} {op.path}",
                "included" if op.included else (op.reason or "excluded"),
            )
            for op in result.operations
        ]
        body += [Text(""), table(["OPERATION", "RESULT"], rows)]
    body += [Text(""), Text("Nothing was created. Drop --dry-run to do it.", style="elva.dim")]
    return Group(*body)
