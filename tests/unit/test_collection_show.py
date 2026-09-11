"""The `collection show` command layer: workspace resolution and the picker.

The services are covered in test_collections_flow.py; here the network and the
prompt are stubbed, so these are about the wiring -- resolving the workspace,
and what happens when a name is ambiguous with and without a terminal.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from elva_cli.commands import collection as command
from elva_cli.context import Ctx, GlobalOptions
from elva_cli.core import collections as service
from elva_cli.core.collections import AmbiguousCollection, CollectionDetail, CollectionSummary
from elva_cli.errors import ExitCode, UsageError

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
ID_A = "a" * 24
ID_B = "b" * 24


def make_ctx(*, tty: bool, json_output: bool = False) -> Ctx:
    return Ctx(
        GlobalOptions(json_output=json_output),
        cwd=Path("/"),
        env={},
        tty=tty,
    )


def click_ctx(ctx: Ctx) -> Any:
    return SimpleNamespace(obj=ctx)


def candidate(
    collection_id: str, updated: str | None = "2026-01-01T00:00:00Z"
) -> CollectionSummary:
    return CollectionSummary(
        id=collection_id,
        name="api",
        spec_uploaded=True,
        endpoint_count=1,
        labels=(),
        is_demo=False,
        updated_at=updated,
    )


def detail(collection_id: str) -> CollectionDetail:
    return CollectionDetail(
        id=collection_id,
        name="api",
        description=None,
        spec_uploaded=True,
        spec_title="API",
        spec_version="1.0",
        labels=(),
        source="openapi",
        is_demo=False,
        endpoint_count=1,
        created_at=None,
        updated_at=None,
        mcps=(),
    )


class TestWorkspaceResolution:
    def test_an_unresolvable_workspace_names_both_the_flag_and_the_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import elva_cli.auth as auth
        import elva_cli.core.api.targets as targets

        monkeypatch.setattr(auth, "get_access_token", lambda *, base_url: "tok")

        def ambiguous(**_: Any) -> Any:
            raise UsageError(
                "more than one workspace, so there is no obvious default",
                hint="Pass --workspace with one of: Theneo, Side",
            )

        monkeypatch.setattr(targets, "resolve_workspace", ambiguous)
        ctx = SimpleNamespace(settings=SimpleNamespace(base_url=BASE_URL, workspace=None))

        with pytest.raises(UsageError) as caught:
            command._workspace(ctx)  # type: ignore[arg-type]
        assert caught.value.exit_code == ExitCode.USAGE
        assert "--workspace" in (caught.value.hint or "")
        assert "ELVA_WORKSPACE" in (caught.value.hint or "")


class TestAmbiguousName:
    @pytest.fixture(autouse=True)
    def _resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(command, "_workspace", lambda _ctx: (BASE_URL, "tok", COMPANY))

    def test_without_a_tty_it_surfaces_the_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            service,
            "get_collection",
            lambda *_a: (_ for _ in ()).throw(
                AmbiguousCollection([candidate(ID_A), candidate(ID_B)])
            ),
        )
        ctx = make_ctx(tty=False)

        with pytest.raises(AmbiguousCollection) as caught:
            command.show(click_ctx(ctx), "api")
        assert caught.value.exit_code == ExitCode.USAGE
        assert ID_A in (caught.value.hint or "") and ID_B in (caught.value.hint or "")

    def test_with_a_tty_it_shows_the_picked_collection(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seen: list[str] = []

        def fake_get(
            base_url: str, token: str, company_id: str, ref: str, reauth: Any = None
        ) -> CollectionDetail:
            seen.append(ref)
            if ref == "api":
                raise AmbiguousCollection([candidate(ID_A), candidate(ID_B)])
            return detail(ref)

        monkeypatch.setattr(service, "get_collection", fake_get)

        picked: dict[str, Any] = {}

        def fake_select(value: Any, *, choices: list[str], **_: Any) -> str:
            picked["choices"] = list(choices)
            return choices[0]  # the ID_A candidate

        import elva_cli.ui.prompts as prompts

        monkeypatch.setattr(prompts, "select", fake_select)

        ctx = make_ctx(tty=True)
        command.show(click_ctx(ctx), "api")

        # The picker was offered the candidates, and the id it returned drove the
        # second, unambiguous fetch.
        assert picked["choices"] and all(ID_A in c or ID_B in c for c in picked["choices"])
        assert seen == ["api", ID_A]
        assert ID_A in capsys.readouterr().out
