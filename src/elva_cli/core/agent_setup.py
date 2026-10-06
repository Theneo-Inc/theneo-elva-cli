from __future__ import annotations

import os
from importlib.resources import files
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from elva_cli.errors import UsageError


def install_skill(root: Path, target: str) -> list[str]:
    if target not in {"codex", "claude", "all"}:
        raise UsageError("--target must be codex, claude or all.")
    targets = ["codex", "claude"] if target == "all" else [target]
    planned: list[tuple[Path, str]] = []
    bundle = files("elva_cli").joinpath("assets/elva-mcp")
    for name in targets:
        folder = root / (".agents" if name == "codex" else ".claude") / "skills" / "elva-mcp"
        for relative in ["SKILL.md", *(["agents/openai.yaml"] if name == "codex" else [])]:
            destination = folder / relative
            # Never follow existing symlink components or overwrite user-authored instructions.
            for parent in (destination, *destination.parents):
                if parent == root.parent:
                    break
                if parent.is_symlink():
                    raise UsageError("Skill installation refuses symlink destinations.")
            content = bundle.joinpath(relative).read_text()
            try:
                conflict = os.path.lexists(destination) and (
                    not destination.is_file() or destination.read_text() != content
                )
            except (OSError, UnicodeError) as exc:
                raise UsageError(
                    "Could not read an existing skill; it was not overwritten."
                ) from exc
            if conflict:
                raise UsageError(
                    f"Existing skill differs: {destination}. Review it before replacing it."
                )
            planned.append((destination, content))
    try:
        for destination, content in planned:
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("x", encoding="utf-8") as stream:
                    stream.write(content)
    except OSError as exc:
        raise UsageError("Could not install skill in the selected directory.") from exc
    return [str(p) for p, _ in planned]
