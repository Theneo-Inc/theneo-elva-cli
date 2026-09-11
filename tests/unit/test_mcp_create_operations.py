from __future__ import annotations

import io

import pytest

from elva_cli.commands.mcp import _resolve_operations
from elva_cli.errors import UsageError


class TestResolveOperations:
    def test_omitted_flag_resolves_to_none(self) -> None:
        """No --operations at all: the caller should omit selectedOperations
        entirely, not send an explicit empty list."""
        assert _resolve_operations([]) is None

    def test_repeated_values_are_returned_as_given(self) -> None:
        assert _resolve_operations(["GET /pets", "POST /pets"]) == ("GET /pets", "POST /pets")

    def test_dash_mixed_with_other_values_is_usage(self) -> None:
        with pytest.raises(UsageError, match="can't be combined"):
            _resolve_operations(["-", "GET /pets"])

    def test_dash_mixed_with_other_values_is_usage_regardless_of_position(self) -> None:
        with pytest.raises(UsageError, match="can't be combined"):
            _resolve_operations(["GET /pets", "-"])

    def test_dash_alone_reads_a_json_array_from_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('["GET /pets", "POST /pets"]'))
        assert _resolve_operations(["-"]) == ("GET /pets", "POST /pets")

    def test_dash_alone_reads_newline_separated_list_from_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("GET /pets\nPOST /pets\n\n"))
        assert _resolve_operations(["-"]) == ("GET /pets", "POST /pets")

    def test_dash_alone_with_an_empty_json_array_resolves_to_an_explicit_empty_tuple(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct from the omitted-flag case: this is an explicit "zero
        operations" selection, not "flag not given"."""
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        assert _resolve_operations(["-"]) == ()
