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


class TestImportSpecRendering:
    """A spec the backend cannot read imports successfully with nothing in it.
    That is the one success the user has to be told about."""

    @staticmethod
    def _result(endpoints: int | None, *, confirmed: bool = True) -> object:
        from elva_cli.core.services.import_result import ImportSpecResult

        return ImportSpecResult(
            action="created",
            collection="payments-api",
            collection_id="0123456789abcdef01234567",
            workspace="Theneo",
            source="openapi.yaml",
            spec_format="openapi",
            endpoints=endpoints,
            spec_title="Payments",
            spec_version="1.0",
            url="https://app.getelva.ai/collections?selected=0123456789abcdef01234567",
            metadata_confirmed=confirmed,
        )

    @staticmethod
    def _text(result: object) -> str:
        from rich.console import Console

        from elva_cli.ui.renderables import render

        buffer = StringIO()
        console = Console(file=buffer, width=100, no_color=True)
        console.print(render(result))
        return buffer.getvalue()

    def test_zero_endpoints_is_called_out(self) -> None:
        assert "No endpoints were found" in self._text(self._result(0))

    def test_a_normal_import_says_nothing_extra(self) -> None:
        out = self._text(self._result(24))
        assert "No endpoints" not in out
        assert "24" in out

    def test_an_absent_count_is_not_treated_as_zero(self) -> None:
        assert "No endpoints" not in self._text(self._result(None))

    def test_unconfirmed_metadata_says_so(self) -> None:
        out = self._text(self._result(24, confirmed=False))
        assert "still describe the previous one" in out

    def test_an_unconfirmed_zero_is_not_reported_as_finding_nothing(self) -> None:
        """The count may be the previous spec's. Claiming this import found no
        endpoints would send the user debugging an import that worked."""
        out = self._text(self._result(0, confirmed=False))
        assert "No endpoints were found" not in out
        assert "still describe the previous one" in out
