from __future__ import annotations

from rich.console import Group
from rich.text import Text

from elva_cli.core.services.workspace_list_result import WorkspaceListResult  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render


def _display_origin(origin: str | None) -> str:
    if not origin:
        return ""
    if origin.startswith("profile:"):
        return "profile"
    return {
        "project": "project file",
        "user": "config",
    }.get(origin, origin)


@render.register
def _(result: WorkspaceListResult) -> Group | Text:
    if not result.workspaces:
        return Text("You are not a member of any workspace.", style="elva.dim")

    entries: list[tuple[str, Text, Text]] = []
    for ws in result.workspaces:
        marker = "* " if ws.active else "  "
        label = f"{marker}{ws.name}"
        slug = Text(ws.slug)
        note = Text(ws.role)
        if ws.active and ws.active_source:
            note = Text.assemble(
                Text(ws.role),
                Text(f"  [from {_display_origin(ws.active_source)}]", style="elva.origin"),
            )
        entries.append((label, slug, note))

    return Group(aligned_rows(entries))
