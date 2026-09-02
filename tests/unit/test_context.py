from __future__ import annotations

from pathlib import Path

import pytest
import typer

from elva_cli.context import Ctx, GlobalOptions, get_ctx
from elva_cli.errors import ElvaError


def test_flags_reach_the_resolver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: tmp_path)
    (tmp_path / ".git").mkdir()
    ctx = Ctx(GlobalOptions(workspace="payments"), cwd=tmp_path, env={})
    assert ctx.settings.workspace == "payments"
    assert ctx.resolution.origins["workspace"] == "flag"


def test_resolution_is_computed_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: tmp_path)
    (tmp_path / ".git").mkdir()
    calls = 0
    real = __import__("elva_cli.settings.loader", fromlist=["resolve"]).resolve

    def counting(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real(**kwargs)

    monkeypatch.setattr("elva_cli.settings.loader.resolve", counting)
    ctx = Ctx(GlobalOptions(), cwd=tmp_path, env={})
    assert ctx.resolution is ctx.resolution
    assert ctx.settings is not None
    assert calls == 1


def _bare_context() -> typer.Context:
    """A click Context with nothing on obj, as if the root callback never ran."""
    dummy = typer.Typer()

    @dummy.command()
    def noop() -> None: ...

    return typer.Context(typer.main.get_command(dummy))


def test_get_ctx_returns_what_the_callback_stored() -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={})
    click_ctx = _bare_context()
    click_ctx.obj = ctx
    assert get_ctx(click_ctx) is ctx


def test_get_ctx_fails_loudly_when_the_callback_did_not_run() -> None:
    with pytest.raises(ElvaError, match="root callback"):
        get_ctx(_bare_context())
