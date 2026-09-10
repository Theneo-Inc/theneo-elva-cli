"""Text the CLI did not write, on its way to a terminal.

Collection names come from Elva, and Postman collection names come from
Postman by way of Elva. Neither is under the control of the person running the
command, and both end up printed. Two things have to hold: Rich must not read
`[...]` in one of them as a style tag, and an escape sequence in one must not
be executed by the terminal.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from elva_cli.core.api.collections import text
from elva_cli.core.services.postman_result import PostmanCollection, PostmanCollectionList
from elva_cli.errors import UsageError
from elva_cli.safe_text import printable
from elva_cli.ui.console import build_consoles
from elva_cli.ui.output import Output, write_error
from elva_cli.ui.renderables import render
from elva_cli.ui.theme import ELVA_THEME

ESCAPE = "Payments\x1b]0;PWNED\x07\x1b[31m"
MARKUP = "[/]"


def console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, theme=ELVA_THEME, no_color=True, width=120), buf


class TestPrintable:
    def test_it_removes_an_escape_sequence_introducer(self) -> None:
        assert "\x1b" not in printable(ESCAPE)

    def test_it_keeps_the_words_around_a_line_break(self) -> None:
        assert printable("two\nlines\tapart") == "two lines apart"

    @pytest.mark.parametrize(
        "char", ["\x00", "\x07", "\x1b", "\x7f", "\x9b"], ids=["nul", "bel", "esc", "del", "csi"]
    )
    def test_every_control_character_goes(self, char: str) -> None:
        assert char not in printable(f"a{char}b")

    def test_ordinary_text_is_untouched(self) -> None:
        assert printable("Payments Platform API (v2) — 17 endpoints") == (
            "Payments Platform API (v2) — 17 endpoints"
        )


class TestServerDocumentFields:
    """Stripped once, where a document is read, rather than at each display."""

    def test_a_name_from_a_document_is_stripped(self) -> None:
        assert text(ESCAPE) == "Payments]0;PWNED[31m"

    def test_a_field_of_nothing_but_control_characters_reads_as_absent(self) -> None:
        assert text("\x1b\x07") is None

    def test_a_postman_row_carries_a_clean_name(self) -> None:
        from elva_cli.core.services.import_postman import _collection

        assert "\x1b" not in _collection({"uid": "u-1", "name": ESCAPE}).name


class TestErrorsSurviveMarkup:
    """A MarkupError raised here would come from inside the error boundary --
    out of main._run()'s own `except ElvaError` -- so it would escape as a
    traceback under exit 1, with no crash file, rather than the error it was
    reporting."""

    def test_an_unclosed_tag_in_a_hint_does_not_raise(self) -> None:
        out, buf = console()
        write_error(out, UsageError("no Postman collection named 'x'", hint=f"Available: {MARKUP}"))
        assert MARKUP in buf.getvalue()

    def test_an_unclosed_tag_in_a_message_does_not_raise(self) -> None:
        out, buf = console()
        write_error(out, UsageError(f"no Postman collection named {MARKUP!r}"))
        assert MARKUP in buf.getvalue()

    def test_a_style_tag_is_shown_rather_than_applied(self) -> None:
        out, buf = console()
        write_error(out, UsageError("x", hint="Available: [red]Billing[/red]"))
        assert "[red]Billing[/red]" in buf.getvalue()

    def test_a_server_message_cannot_smuggle_an_escape_through(self) -> None:
        out, buf = console()
        write_error(out, UsageError(ESCAPE))
        assert "\x1b" not in buf.getvalue()


class TestConsolesHaveMarkupOff:
    """hint() and warn() print strings the CLI did not compose either -- a URL
    with a bracket in it, a message from the server."""

    @pytest.mark.parametrize("stream", [0, 1], ids=["stdout", "stderr"])
    def test_neither_console_reads_a_string_as_markup(
        self, stream: int, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Asserted through behaviour rather than Console internals: printing
        an unclosed tag must show it, not raise MarkupError."""
        built = build_consoles(color=False, quiet=False)[stream]
        built.print(f"Available: {MARKUP}")
        captured = capsys.readouterr()
        assert MARKUP in (captured.out if stream == 0 else captured.err)

    def test_a_bracket_in_a_hint_does_not_raise(self) -> None:
        buf = StringIO()
        err = Console(file=buf, theme=ELVA_THEME, no_color=True, markup=False, width=120)
        Output(stdout=err, stderr=err, json_mode=False, quiet=False).hint("Opening https://x/[/]")
        assert "[/]" in buf.getvalue()


class TestRenderedNamesAreSafe:
    def test_an_escape_in_a_listed_name_never_reaches_the_stream(self) -> None:
        listing = PostmanCollectionList(
            workspace="Theneo",
            collections=(PostmanCollection(uid="u-1", name=text(ESCAPE) or ""),),
        )
        out, buf = console()
        out.print(render(listing), soft_wrap=True)
        assert "\x1b" not in buf.getvalue()
        assert "Payments" in buf.getvalue()
