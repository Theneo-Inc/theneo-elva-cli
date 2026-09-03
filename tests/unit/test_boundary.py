"""Enforces the rule that only ui/ may touch the terminal.

Conventions decay. A red build does not. If this test starts failing, the fix is
almost always to return a Result and let ui/ render it, not to add an exemption.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "elva_cli"

# ui/ owns rendering and input. main.py is the entry point and error boundary, so
# it alone may exit the process and print the version before any Ctx exists.
EXEMPT = {SRC / "main.py"}
UI = SRC / "ui"

BANNED_CALLS = {"print", "input", "breakpoint"}
BANNED_ATTR_CALLS = {
    ("typer", "echo"),
    ("typer", "secho"),
    ("typer", "prompt"),
    ("typer", "confirm"),
}
BANNED_IMPORTS = {"questionary", "rich"}


def modules_below_the_boundary() -> list[Path]:
    return sorted(
        path for path in SRC.rglob("*.py") if UI not in path.parents and path not in EXEMPT
    )


def test_there_are_modules_to_check() -> None:
    """Guards against the glob silently matching nothing."""
    assert len(modules_below_the_boundary()) > 5


@pytest.mark.parametrize("path", modules_below_the_boundary(), ids=lambda p: p.name)
def test_module_does_not_touch_the_terminal(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                offences.append(f"line {node.lineno}: calls {func.id}()")
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and (func.value.id, func.attr) in BANNED_ATTR_CALLS
            ):
                offences.append(f"line {node.lineno}: calls {func.value.id}.{func.attr}()")
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "exit"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sys"
            ):
                offences.append(f"line {node.lineno}: calls sys.exit()")

    assert not offences, f"{path.relative_to(SRC)} is below the ui boundary but " + "; ".join(
        offences
    )


def test_core_cannot_reach_prompts_or_rendering() -> None:
    """The strong form: core/ must not even be able to import them."""
    offences: list[str] = []

    for path in sorted((SRC / "core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in BANNED_IMPORTS or name.startswith("elva_cli.ui"):
                    offences.append(f"{path.relative_to(SRC)}:{node.lineno} imports {name}")

    assert not offences, "core/ must stay free of ui and prompt libraries: " + "; ".join(offences)


def test_the_check_would_actually_catch_a_violation(tmp_path: Path) -> None:
    """Proves the AST walk works, so a passing suite means something."""
    bad = tmp_path / "bad.py"
    bad.write_text("import typer\ndef f():\n    typer.echo('nope')\n", encoding="utf-8")

    tree = ast.parse(bad.read_text(encoding="utf-8"))
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and (node.func.value.id, node.func.attr) in BANNED_ATTR_CALLS
    ]
    assert len(found) == 1
