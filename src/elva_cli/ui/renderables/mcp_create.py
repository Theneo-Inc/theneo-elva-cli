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
    headline = Text(f"Created {result.name!r}.", style="elva.ok")
    rows = [
        ("Deployment", Text(result.deployment_id), Text("")),
        ("Slug", Text(result.slug), Text("")),
        ("Tools", Text(str(result.tool_count)), Text("")),
        ("Auth type", Text(result.auth_type), Text("")),
        ("Secret", secret_note(result.has_secret), Text("")),
        ("URL", Text(result.runtime_url or "", style="elva.accent"), Text("")),
    ]
    return Group(headline, Text(""), aligned_rows(rows))


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
