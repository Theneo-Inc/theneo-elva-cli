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


@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL"])
def test_is_ci_true_for_known_providers(var: str) -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={var: "true"})
    assert ctx.is_ci is True


def test_is_ci_false_when_set_to_a_falsey_value() -> None:
    # A naive `env.get("CI")` truthy-check would get this wrong: the string
    # "false" is truthy in Python even though it means "not CI".
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={"CI": "false"})
    assert ctx.is_ci is False


def test_is_ci_false_when_nothing_is_set() -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={})
    assert ctx.is_ci is False


def test_is_tty_uses_the_injected_override() -> None:
    assert Ctx(GlobalOptions(), cwd=Path("/"), env={}, tty=True).is_tty is True
    assert Ctx(GlobalOptions(), cwd=Path("/"), env={}, tty=False).is_tty is False


def test_interactive_is_false_under_json_mode_even_with_a_tty() -> None:
    ctx = Ctx(GlobalOptions(json_output=True), cwd=Path("/"), env={}, tty=True)
    assert ctx.interactive is False


def test_interactive_is_false_in_ci_even_with_a_tty() -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={"CI": "true"}, tty=True)
    assert ctx.interactive is False


def test_interactive_is_true_with_a_tty_and_no_ci() -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={}, tty=True)
    assert ctx.interactive is True


def test_interactive_is_false_without_a_tty() -> None:
    ctx = Ctx(GlobalOptions(), cwd=Path("/"), env={}, tty=False)
    assert ctx.interactive is False


def test_quiet_alone_does_not_affect_interactive() -> None:
    """--quiet lowers the noise floor; it doesn't mean nobody's there."""
    ctx = Ctx(GlobalOptions(quiet=True), cwd=Path("/"), env={}, tty=True)
    assert ctx.interactive is True
