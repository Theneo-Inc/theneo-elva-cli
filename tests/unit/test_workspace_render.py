from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

import elva_cli.ui.renderables.workspace  # noqa: F401
from elva_cli.core.services.workspace_list_result import WorkspaceItem, WorkspaceListResult
from elva_cli.ui.output import Output
from elva_cli.ui.renderables.base import render
from elva_cli.ui.theme import ELVA_THEME


def _output(*, json_mode: bool) -> tuple[Output, StringIO]:
    buf = StringIO()
    err = StringIO()
    stdout = Console(file=buf, theme=ELVA_THEME, no_color=True, width=120)
    stderr = Console(file=err, theme=ELVA_THEME, no_color=True, width=120)
    return Output(stdout=stdout, stderr=stderr, json_mode=json_mode, quiet=False), buf


def test_json_carries_configured_mismatch() -> None:
    output, buf = _output(json_mode=True)
    result = WorkspaceListResult(
        workspaces=[
            WorkspaceItem(
                name="Payments Team", slug="pay", role="admin", active=False, active_source=None
            ),
        ],
        configured_workspace="payments-old",
        configured_origin="project",
        configured_matched=False,
    )
    output.result(result)
    parsed = json.loads(buf.getvalue())
    assert parsed["configured_matched"] is False
    assert parsed["configured_workspace"] == "payments-old"
    assert parsed["configured_origin"] == "project"


def test_human_renderer_warns_on_configured_mismatch() -> None:
    result = WorkspaceListResult(
        workspaces=[
            WorkspaceItem(
                name="Payments Team", slug="pay", role="admin", active=False, active_source=None
            ),
            WorkspaceItem(
                name="Platform", slug="plat", role="member", active=False, active_source=None
            ),
        ],
        configured_workspace="payments-old",
        configured_origin="project",
        configured_matched=False,
    )
    buf = StringIO()
    console = Console(file=buf, theme=ELVA_THEME, no_color=True, width=120)
    console.print(render(result), soft_wrap=True)
    text = buf.getvalue()
    assert "payments-old" in text
    assert "project file" in text
    assert "not in this list" in text


def test_human_renderer_omits_warning_when_matched() -> None:
    result = WorkspaceListResult(
        workspaces=[
            WorkspaceItem(
                name="Theneo", slug="theneo", role="owner", active=True, active_source="project"
            ),
        ],
        configured_matched=True,
    )
    buf = StringIO()
    console = Console(file=buf, theme=ELVA_THEME, no_color=True, width=120)
    console.print(render(result), soft_wrap=True)
    text = buf.getvalue()
    assert "not in this list" not in text
    assert "* Theneo" in text


def test_human_renderer_warns_when_list_empty_but_configured() -> None:
    result = WorkspaceListResult(
        workspaces=[],
        configured_workspace="ghost",
        configured_origin="user",
        configured_matched=False,
    )
    buf = StringIO()
    console = Console(file=buf, theme=ELVA_THEME, no_color=True, width=120)
    console.print(render(result), soft_wrap=True)
    text = buf.getvalue()
    assert "ghost" in text
    assert "not a member" in text
