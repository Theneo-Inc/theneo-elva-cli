from __future__ import annotations

from rich.table import Table  # noqa: TC002
from rich.text import Text

from elva_cli.core.services.mcp_logs_result import LogEntry, McpLogsResult  # noqa: TC001
from elva_cli.ui.renderables.base import render, table


@render.register
def _(result: McpLogsResult) -> Table | Text:
    if not result.entries:
        if result.total == 0:
            return Text("No log entries yet for this MCP server.", style="elva.dim")
        return Text(f"No log entries on page {result.page}.", style="elva.dim")
    return table(
        ["TIME", "TOOL", "STATUS", "DURATION", "AGENT", "ERROR"],
        [
            (
                e.time,
                e.tool,
                str(e.status),
                f"{e.duration_ms}ms",
                e.agent or "-",
                e.error or "",
            )
            for e in result.entries
        ],
    )


def format_log_line(entry: LogEntry) -> str:
    """One plain, append-only line for `--follow`"""
    line = (
        f"{entry.time}  {entry.tool:<24}  {entry.status:<3}  "
        f"{entry.duration_ms:>6}ms  {entry.agent or '-'}"
    )
    if entry.error:
        line += f"  error: {entry.error}"
    return line
