from __future__ import annotations

import os
import select
import sys
from typing import Any

import pytest

from elva_cli.commands.mcp import _emit_batch, _stdin_closed
from elva_cli.core.api.http import HttpError, UnreachableError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import mcp_logs as service
from elva_cli.core.services.mcp_logs_result import LogEntry, McpLogsResult
from elva_cli.errors import ApiError, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
SLUG = "widgets"


def row(id_: str, *, time: str = "2026-01-01T00:00:00.000Z") -> dict[str, Any]:
    return {
        "id": id_,
        "time": time,
        "tool": "create_widget",
        "status": 200,
        "durationMs": 42,
        "agent": "agent-1",
        "agentId": "ag1",
        "clientId": "cl1",
        "userId": None,
        "error": None,
        "tokens": 10,
    }


def body(*ids: str, total: int) -> dict[str, Any]:
    return {"logs": [row(i) for i in ids], "total": total}


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))


def sequenced(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> list[str]:
    seen: list[str] = []
    queue = list(responses)

    def fake_get(url: str, **_kwargs: Any) -> Any:
        seen.append(url)
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(service, "get_json", fake_get)
    return seen


class TestWindow:
    def test_limit_within_cap_is_a_single_passthrough_call(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = sequenced(monkeypatch, [body("a", "b", total=2)])
        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=20
        )
        assert result == McpLogsResult(
            entries=(
                LogEntry(
                    id="a",
                    time="2026-01-01T00:00:00.000Z",
                    tool="create_widget",
                    status=200,
                    duration_ms=42,
                    agent="agent-1",
                    agent_id="ag1",
                    client_id="cl1",
                    user_id=None,
                    error=None,
                    tokens=10,
                ),
                LogEntry(
                    id="b",
                    time="2026-01-01T00:00:00.000Z",
                    tool="create_widget",
                    status=200,
                    duration_ms=42,
                    agent="agent-1",
                    agent_id="ag1",
                    client_id="cl1",
                    user_id=None,
                    error=None,
                    tokens=10,
                ),
            ),
            total=2,
            page=1,
            limit=20,
        )
        assert len(seen) == 1
        assert "page=1" in seen[0]
        assert "limit=20" in seen[0]
        assert "sort=time" in seen[0]
        assert "order=desc" in seen[0]

    def test_limit_over_cap_stitches_backend_pages(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        page1 = body(*(f"row-{i}" for i in range(100)), total=150)
        page2 = body(*(f"row-{i}" for i in range(100, 150)), total=150)
        seen = sequenced(monkeypatch, [page1, page2])

        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=150
        )

        assert len(result.entries) == 150
        assert result.entries[0].id == "row-0"
        assert result.entries[-1].id == "row-149"
        assert result.total == 150
        assert len(seen) == 2
        assert "page=1" in seen[0]
        assert "limit=100" in seen[0]
        assert "page=2" in seen[1]

    def test_stops_early_when_total_is_smaller_than_requested(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        page1 = body(*(f"row-{i}" for i in range(100)), total=120)
        page2 = body(*(f"row-{i}" for i in range(100, 120)), total=120)
        sequenced(monkeypatch, [page1, page2])

        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=150
        )

        assert len(result.entries) == 120
        assert result.entries[-1].id == "row-119"

    def test_page_offset_spans_backend_pages_correctly(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        # page=2, limit=150 -> offset=150, skip=50, starts at backend page 2.
        page2 = body(*(f"row-{i}" for i in range(100, 200)), total=500)
        page3 = body(*(f"row-{i}" for i in range(200, 300)), total=500)
        seen = sequenced(monkeypatch, [page2, page3])

        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=2, limit=150
        )

        assert len(result.entries) == 150
        assert result.entries[0].id == "row-150"
        assert result.entries[-1].id == "row-299"
        assert "page=2" in seen[0]
        assert "page=3" in seen[1]

    def test_no_entries_on_first_page_is_a_genuinely_empty_log(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(monkeypatch, [body(total=0)])
        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=10
        )
        assert result.entries == ()
        assert result.total == 0

    def test_no_entries_on_a_later_page_still_reports_the_real_total(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(monkeypatch, [body(total=5)])
        result = service.fetch_logs_window(
            base_url=BASE_URL, workspace=None, slug=SLUG, page=2, limit=10
        )
        assert result.entries == ()
        assert result.total == 5
        assert result.page == 2

    def test_404_names_the_slug_and_suggests_list(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(monkeypatch, [HttpError(404, None)])
        with pytest.raises(UsageError) as caught:
            service.fetch_logs_window(
                base_url=BASE_URL, workspace=None, slug="nope", page=1, limit=10
            )
        assert "nope" in str(caught.value)
        assert caught.value.hint is not None
        assert "mcp list" in caught.value.hint

    def test_403_is_a_usage_error(self, monkeypatch: pytest.MonkeyPatch, signed_in: None) -> None:
        sequenced(monkeypatch, [HttpError(403, None)])
        with pytest.raises(UsageError):
            service.fetch_logs_window(
                base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=10
            )

    def test_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(monkeypatch, [{"nope": []}])
        with pytest.raises(ApiError):
            service.fetch_logs_window(
                base_url=BASE_URL, workspace=None, slug=SLUG, page=1, limit=10
            )


class TestFollow:
    def test_yields_backlog_chronologically_then_new_entries_deduped(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        backlog = body("c", "b", "a", total=3)  # backend gave newest-first (order=desc)
        poll = body("c", "d", total=4)  # "c" is the boundary row (most recent seen), already seen
        seen = sequenced(monkeypatch, [backlog, poll])
        sleeps: list[float] = []

        gen = service.follow_logs(
            base_url=BASE_URL,
            workspace=None,
            slug=SLUG,
            limit=20,
            sleep=sleeps.append,
        )

        first = next(gen)
        assert [e.id for e in first] == ["a", "b", "c"]

        second = next(gen)
        assert [e.id for e in second] == ["d"]
        assert sleeps == [service._DEFAULT_INTERVAL]
        assert "order=desc" in seen[0]
        assert "order=asc" in seen[1]

    def test_starts_from_epoch_when_there_is_no_backlog(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = sequenced(monkeypatch, [body(total=0), body(total=0)])
        gen = service.follow_logs(
            base_url=BASE_URL, workspace=None, slug=SLUG, limit=20, sleep=lambda _s: None
        )
        assert next(gen) == ()
        assert next(gen) == ()
        assert "1970-01-01" in seen[1]

    def test_a_transient_poll_failure_is_retried_with_backoff(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(
            monkeypatch,
            [body("a", total=1), HttpError(503, None), body("a", "b", total=2)],
        )
        sleeps: list[float] = []
        notes: list[str] = []

        gen = service.follow_logs(
            base_url=BASE_URL,
            workspace=None,
            slug=SLUG,
            limit=20,
            sleep=sleeps.append,
            notify=notes.append,
        )
        assert [e.id for e in next(gen)] == ["a"]
        assert [e.id for e in next(gen)] == ["b"]
        assert sleeps == [service._DEFAULT_INTERVAL, service._FOLLOW_BACKOFF_SECONDS[0]]
        assert len(notes) == 1
        assert "retrying" in notes[0]

    def test_an_unreachable_server_counts_as_transient(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(
            monkeypatch,
            [body("a", total=1), UnreachableError("down"), body("a", "b", total=2)],
        )
        gen = service.follow_logs(
            base_url=BASE_URL, workspace=None, slug=SLUG, limit=20, sleep=lambda _s: None
        )
        next(gen)
        assert [e.id for e in next(gen)] == ["b"]

    def test_gives_up_after_the_backoff_is_exhausted(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        attempts = 1 + len(service._FOLLOW_BACKOFF_SECONDS)
        sequenced(
            monkeypatch,
            [body("a", total=1), *[HttpError(500, None)] * attempts],
        )
        notes: list[str] = []
        gen = service.follow_logs(
            base_url=BASE_URL,
            workspace=None,
            slug=SLUG,
            limit=20,
            sleep=lambda _s: None,
            notify=notes.append,
        )
        next(gen)
        with pytest.raises(ApiError, match="Lost contact"):
            next(gen)
        # every retry announced, but the final give-up is left to the raised error
        assert len(notes) == len(service._FOLLOW_BACKOFF_SECONDS)

    def test_a_bad_slug_mid_follow_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = sequenced(monkeypatch, [body("a", total=1), HttpError(404, None)])
        gen = service.follow_logs(
            base_url=BASE_URL, workspace=None, slug=SLUG, limit=20, sleep=lambda _s: None
        )
        next(gen)
        with pytest.raises(UsageError):
            next(gen)
        assert len(seen) == 2  # one poll, no retry

    def test_the_opening_backlog_fetch_is_also_retried(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        sequenced(monkeypatch, [UnreachableError("down"), body("a", total=1)])
        notes: list[str] = []
        gen = service.follow_logs(
            base_url=BASE_URL,
            workspace=None,
            slug=SLUG,
            limit=20,
            sleep=lambda _s: None,
            notify=notes.append,
        )
        assert [e.id for e in next(gen)] == ["a"]
        assert notes and "retrying" in notes[0]

    def test_an_entry_that_slides_across_a_backend_page_is_not_double_yielded(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        full_page = body(*(f"r{i}" for i in range(service._BACKEND_MAX_LIMIT)), total=100)
        # a concurrent insert shifts "r99" onto the head of the next page
        next_page = body("r99", "r100", total=102)
        sequenced(monkeypatch, [body(total=0), full_page, next_page])
        gen = service.follow_logs(
            base_url=BASE_URL, workspace=None, slug=SLUG, limit=20, sleep=lambda _s: None
        )
        next(gen)  # empty backlog
        ids = [e.id for e in next(gen)]
        assert ids.count("r99") == 1
        assert ids[-1] == "r100"


class TestEmitBatch:
    class _FakeOut:
        def __init__(self, *, json_mode: bool) -> None:
            self.json_mode = json_mode
            self.json_calls: list[Any] = []
            self.line_calls: list[str] = []

        def stream_json(self, obj: Any) -> None:
            self.json_calls.append(obj)

        def stream_line(self, text: str) -> None:
            self.line_calls.append(text)

    class _FakeCtx:
        def __init__(self, *, json_mode: bool) -> None:
            self.out = TestEmitBatch._FakeOut(json_mode=json_mode)

    def _entry(self, id_: str) -> LogEntry:
        return LogEntry(
            id=id_,
            time="T",
            tool="tool",
            status=200,
            duration_ms=5,
            agent="agent-1",
            agent_id="ag1",
            client_id=None,
            user_id=None,
            error=None,
            tokens=None,
        )

    def test_json_mode_streams_one_object_per_entry(self) -> None:
        ctx = self._FakeCtx(json_mode=True)
        _emit_batch(ctx, (self._entry("a"), self._entry("b")), str)  # type: ignore[arg-type]
        assert [call["id"] for call in ctx.out.json_calls] == ["a", "b"]
        assert ctx.out.line_calls == []

    def test_human_mode_streams_formatted_lines(self) -> None:
        ctx = self._FakeCtx(json_mode=False)
        _emit_batch(ctx, (self._entry("a"),), lambda e: f"line-{e.id}")  # type: ignore[arg-type]
        assert ctx.out.line_calls == ["line-a"]
        assert ctx.out.json_calls == []


class TestStdinClosed:
    def test_false_when_stdin_is_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
        monkeypatch.setattr(select, "select", lambda *_a, **_kw: ([], [], []))
        assert _stdin_closed() is False

    def test_true_on_eof(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
        monkeypatch.setattr(select, "select", lambda *_a, **_kw: ([0], [], []))
        monkeypatch.setattr(os, "read", lambda *_a: b"")
        assert _stdin_closed() is True

    def test_false_when_data_is_available_without_a_newline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A partial write that never gets its newline must not be read as EOF,
        and must not block."""
        monkeypatch.setattr(sys.stdin, "fileno", lambda: 0)
        monkeypatch.setattr(select, "select", lambda *_a, **_kw: ([0], [], []))
        monkeypatch.setattr(os, "read", lambda *_a: b"partial-no-newline")
        assert _stdin_closed() is False

    def test_false_when_stdin_has_no_fileno(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def no_fileno() -> int:
            raise ValueError

        monkeypatch.setattr(sys.stdin, "fileno", no_fileno)
        assert _stdin_closed() is False
