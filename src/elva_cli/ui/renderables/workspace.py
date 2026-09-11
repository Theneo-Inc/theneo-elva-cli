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
    warning: Text | None = None
    if not result.configured_matched and result.configured_workspace:
        origin = _display_origin(result.configured_origin)
        suffix = f" (from {origin})" if origin else ""
        warning = Text(
            f"configured workspace {result.configured_workspace!r}{suffix} is not in this list",
            style="elva.warn",
        )

    if not result.workspaces:
        empty = Text("You are not a member of any workspace.", style="elva.dim")
        return Group(warning, empty) if warning else empty

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

    table = aligned_rows(entries)
    return Group(warning, table) if warning else Group(table)
