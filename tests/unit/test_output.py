from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import StringIO

import pytest
from rich.console import Console
from rich.text import Text

from elva_cli.errors import AuthError
from elva_cli.ui.output import Output, as_data
from elva_cli.ui.renderables.base import render
from elva_cli.ui.theme import ELVA_THEME


@dataclass(frozen=True)
class Sample:
    name: str
    count: int
    missing: str | None = None
    tags: list[str] = field(default_factory=list)


@render.register
def _(result: Sample) -> Text:
    return Text(f"{result.name} x{result.count}")


def make_output(
    *, json_mode: bool = False, quiet: bool = False
) -> tuple[Output, StringIO, StringIO]:
    out_buf, err_buf = StringIO(), StringIO()
    stdout = Console(file=out_buf, theme=ELVA_THEME, no_color=True, width=80)
    stderr = Console(file=err_buf, theme=ELVA_THEME, no_color=True, width=80, quiet=quiet)
    return (
        Output(stdout=stdout, stderr=stderr, json_mode=json_mode, quiet=quiet),
        out_buf,
        err_buf,
    )


def test_human_mode_renders_via_dispatch() -> None:
    output, out_buf, err_buf = make_output()
    output.result(Sample("spec", 3))
    assert "spec x3" in out_buf.getvalue()
    assert err_buf.getvalue() == ""


def test_json_mode_emits_parseable_json_on_stdout() -> None:
    output, out_buf, _ = make_output(json_mode=True)
    output.result(Sample("spec", 3, tags=["a", "b"]))
    parsed = json.loads(out_buf.getvalue())
    assert parsed == {"name": "spec", "count": 3, "missing": None, "tags": ["a", "b"]}


def test_json_mode_output_is_unwrapped_and_unstyled() -> None:
    output, out_buf, _ = make_output(json_mode=True)
    output.result(Sample("x" * 200, 1))
    raw = out_buf.getvalue()
    assert "\x1b" not in raw
    assert "x" * 200 in raw


def test_json_mode_does_not_use_the_renderer() -> None:
    """A Result with no registered renderer still works under --json."""

    @dataclass(frozen=True)
    class Unrendered:
        value: int

    output, out_buf, _ = make_output(json_mode=True)
    output.result(Unrendered(1))
    assert json.loads(out_buf.getvalue()) == {"value": 1}


def test_chrome_goes_to_stderr() -> None:
    output, out_buf, err_buf = make_output()
    output.hint("try --help")
    output.warn("deprecated")
    output.error(AuthError("expired"))
    assert out_buf.getvalue() == ""
    err = err_buf.getvalue()
    assert "try --help" in err
    assert "deprecated" in err
    assert "ELVA_AUTH" in err


def test_quiet_silences_chrome_but_keeps_data() -> None:
    output, out_buf, err_buf = make_output(quiet=True)
    output.hint("noise")
    output.warn("noise")
    output.result(Sample("spec", 1))
    assert err_buf.getvalue() == ""
    assert "spec x1" in out_buf.getvalue()


def test_error_includes_the_next_action() -> None:
    output, _, err_buf = make_output()
    output.error(AuthError("expired"))
    assert "elva auth login" in err_buf.getvalue()


def test_non_dataclass_results_are_rejected() -> None:
    with pytest.raises(TypeError, match="dataclasses"):
        as_data({"not": "a dataclass"})


def test_unregistered_renderer_fails_loudly_in_human_mode() -> None:
    @dataclass(frozen=True)
    class Unrendered:
        value: int

    output, _, _ = make_output()
    with pytest.raises(NotImplementedError, match="Unrendered"):
        output.result(Unrendered(1))
