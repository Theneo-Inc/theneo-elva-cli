"""The `collection endpoints` command layer: filters, the drift warning, the
picker, and the empty-result note.

The services are covered in test_collection_endpoints_flow.py; here the network
and the prompt are stubbed, so these are about the wiring the command adds around
them.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from elva_cli.commands import collection as command
from elva_cli.context import Ctx, GlobalOptions
from elva_cli.core import collections as service
from elva_cli.core.collections import AmbiguousCollection, CollectionSummary
from elva_cli.core.openapi_ops import Operation
from elva_cli.errors import ExitCode

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
ID_A = "a" * 24
ID_B = "b" * 24


def make_ctx(*, tty: bool, json_output: bool = False) -> Ctx:
    return Ctx(GlobalOptions(json_output=json_output), cwd=Path("/"), env={}, tty=tty)


def click_ctx(ctx: Ctx) -> Any:
    return SimpleNamespace(obj=ctx)


def summary(*, endpoint_count: int | None, collection_id: str = ID_A) -> CollectionSummary:
    return CollectionSummary(
        id=collection_id,
        name="api",
        spec_uploaded=True,
        endpoint_count=endpoint_count,
        labels=(),
        is_demo=False,
        updated_at="2026-01-01T00:00:00Z",
    )


def op(method: str, path: str, tags: tuple[str, ...] = ()) -> Operation:
    return Operation(
        key=f"{method} {path}",
        method=method,
        path=path,
        operation_id=None,
        summary=None,
        tags=tags,
    )


OPS = [
    op("GET", "/users", ("users",)),
    op("POST", "/users", ("users", "admin")),
    op("GET", "/orders", ("orders",)),
]


@pytest.fixture(autouse=True)
def _resolved_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command, "_workspace", lambda _ctx: (BASE_URL, "tok", COMPANY))


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolved: CollectionSummary,
    ops: list[Operation],
) -> None:
    monkeypatch.setattr(service, "resolve_collection", lambda *_a: resolved)
    monkeypatch.setattr(service, "get_collection_operations", lambda *_a: ops)


def _run(
    ctx: Ctx,
    ref: str = "api",
    *,
    tags: list[str] | None = None,
    methods: list[str] | None = None,
    paths: list[str] | None = None,
) -> None:
    command.endpoints(
        click_ctx(ctx),
        ref,
        tags=tags or [],
        methods=methods or [],
        path_prefixes=paths or [],
    )


class TestFilters:
    def test_filters_narrow_the_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=3), ops=OPS)
        _run(make_ctx(tty=True), methods=["get"])
        out = capsys.readouterr().out
        assert "/users" in out and "/orders" in out
        assert "POST" not in out  # the POST was filtered out by --method get

    def test_no_filters_shows_everything(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=3), ops=OPS)
        _run(make_ctx(tty=True))
        out = capsys.readouterr().out
        assert out.count("/users") == 2  # GET and POST both present


class TestDriftWarning:
    def test_a_count_mismatch_warns_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=5), ops=OPS)
        _run(make_ctx(tty=True))
        err = capsys.readouterr().err
        assert "warning" in err
        assert "5" in err and "3" in err

    def test_a_matching_count_is_silent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=3), ops=OPS)
        _run(make_ctx(tty=True))
        assert "warning" not in capsys.readouterr().err

    def test_a_null_count_never_warns(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=None), ops=OPS)
        _run(make_ctx(tty=True))
        assert "warning" not in capsys.readouterr().err

    def test_the_warning_compares_against_the_unfiltered_count(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Filtering down to one row must not make the drift check think the spec
        # has one operation: it has three, which matches, so no warning.
        _stub(monkeypatch, resolved=summary(endpoint_count=3), ops=OPS)
        _run(make_ctx(tty=True), methods=["delete"])
        assert "warning" not in capsys.readouterr().err


class TestEmptyResult:
    def test_no_match_after_filtering_notes_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=3), ops=OPS)
        _run(make_ctx(tty=True), methods=["delete"])
        captured = capsys.readouterr()
        assert "No operations match" in captured.err

    def test_a_spec_with_no_operations_notes_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=0), ops=[])
        _run(make_ctx(tty=True))
        assert "no operations" in capsys.readouterr().err.lower()

    def test_json_empty_is_an_empty_array_with_no_note(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _stub(monkeypatch, resolved=summary(endpoint_count=0), ops=[])
        _run(make_ctx(tty=False, json_output=True))
        captured = capsys.readouterr()
        assert captured.out.strip() == "[]"
        assert "no operations" not in captured.err.lower()


class TestAmbiguousName:
    def test_without_a_tty_it_surfaces_the_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_ambiguous(*_a: Any) -> Any:
            raise AmbiguousCollection(
                [
                    summary(endpoint_count=1, collection_id=ID_A),
                    summary(endpoint_count=1, collection_id=ID_B),
                ]
            )

        monkeypatch.setattr(service, "resolve_collection", raise_ambiguous)
        monkeypatch.setattr(service, "get_collection_operations", lambda *_a: OPS)

        with pytest.raises(AmbiguousCollection) as caught:
            _run(make_ctx(tty=False))
        assert caught.value.exit_code == ExitCode.USAGE
        assert ID_A in (caught.value.hint or "") and ID_B in (caught.value.hint or "")

    def test_with_a_tty_the_picked_id_drives_the_fetch(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seen: list[str] = []

        def resolve(base_url: str, token: str, company_id: str, ref: str) -> CollectionSummary:
            seen.append(ref)
            if ref == "api":
                raise AmbiguousCollection(
                    [
                        summary(endpoint_count=3, collection_id=ID_A),
                        summary(endpoint_count=3, collection_id=ID_B),
                    ]
                )
            return summary(endpoint_count=3, collection_id=ref)

        ops_seen: list[str] = []

        def fetch(base_url: str, token: str, company_id: str, ref: str) -> list[Operation]:
            ops_seen.append(ref)
            return OPS

        monkeypatch.setattr(service, "resolve_collection", resolve)
        monkeypatch.setattr(service, "get_collection_operations", fetch)

        import elva_cli.ui.prompts as prompts

        monkeypatch.setattr(prompts, "select", lambda *_a, choices, **_k: choices[0])

        _run(make_ctx(tty=True))

        # The picker's id resolved once more (unambiguously) and then drove the fetch.
        assert seen == ["api", ID_A]
        assert ops_seen == [ID_A]
        assert "/users" in capsys.readouterr().out
