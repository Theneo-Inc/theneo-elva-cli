from __future__ import annotations

from rich.console import Group
from rich.text import Text

# Imported at runtime, not under TYPE_CHECKING: singledispatch resolves the
# annotation when register() runs, so the class has to actually exist.
from elva_cli.core.services.config import ConfigPaths, ConfigValues  # noqa: TC001
from elva_cli.ui.renderables.base import aligned_rows, render


@render.register
def _(result: ConfigPaths) -> Text:
    entries = [
        ("config dir", Text(result.config_dir), Text("")),
        ("cache dir", Text(result.cache_dir), Text("")),
    ]
    for file in result.files:
        state = Text("found", style="elva.ok") if file.exists else Text("absent", style="elva.dim")
        entries.append((f"{file.kind} config", Text(file.path), state))
    return aligned_rows(entries)


@render.register
def _(result: ConfigValues) -> Group:
    entries = []
    for setting in result.settings:
        if setting.value is None:
            value = Text("-", style="elva.dim")
        elif setting.value is True:
            value = Text("true")
        elif setting.value is False:
            value = Text("false")
        else:
            value = Text(str(setting.value))
        entries.append((setting.key, value, Text(setting.origin, style="elva.origin")))

    table = aligned_rows(entries)
    if not result.profiles:
        return Group(table)
    return Group(table, Text(""), Text(f"profiles: {', '.join(result.profiles)}", style="elva.dim"))
