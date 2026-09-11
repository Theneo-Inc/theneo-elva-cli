from __future__ import annotations

from typing import Any

import pytest

from elva_cli.errors import UsageError
from elva_cli.ui import secrets


class TestReadSecret:
    def test_env_ref_reads_the_named_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_SECRET", "hunter2")
        assert secrets.read_secret("env:MY_SECRET", flag="--client-secret") == "hunter2"

    def test_env_ref_to_an_unset_variable_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MY_UNSET_SECRET", raising=False)
        with pytest.raises(UsageError, match="MY_UNSET_SECRET"):
            secrets.read_secret("env:MY_UNSET_SECRET", flag="--client-secret")

    def test_file_ref_reads_the_file_and_strips_a_trailing_newline(self, tmp_path: Any) -> None:
        path = tmp_path / "secret.txt"
        path.write_text("hunter2\n")
        assert secrets.read_secret(f"file:{path}", flag="--client-secret") == "hunter2"

    def test_file_ref_to_a_missing_file_is_a_usage_error(self, tmp_path: Any) -> None:
        with pytest.raises(UsageError, match="no such file"):
            secrets.read_secret(f"file:{tmp_path / 'nope.txt'}", flag="--client-secret")

    def test_dash_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO("hunter2\n"))
        assert secrets.read_secret("-", flag="--client-secret") == "hunter2"

    def test_a_bare_value_is_refused_outright(self) -> None:
        with pytest.raises(UsageError, match="does not accept a plain value"):
            secrets.read_secret("hunter2", flag="--client-secret")

    def test_an_empty_resolved_value_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMPTY_SECRET", "")
        with pytest.raises(UsageError, match="empty"):
            secrets.read_secret("env:EMPTY_SECRET", flag="--client-secret")
