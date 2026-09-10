"""The `elva import postman` flow.

Nothing here touches the network: send_json is replaced and the request it
would have made is asserted on. The recurring theme is the API key -- where it
is allowed to appear, and where it must never appear.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import import_postman as service
from elva_cli.core.services.postman_result import PostmanCollection, PostmanImportResult
from elva_cli.errors import (
    ApiError,
    AuthError,
    ExitCode,
    ForbiddenError,
    UsageError,
    ValidationError,
)

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
CREATED_ID = "89abcdef0123456789abcdef"
KEY = "PMAK-NOT-A-REAL-KEY-fixture-only-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

PAYMENTS = {
    "id": "1111",
    "uid": "12345678-1111-2222-3333-444455556666",
    "name": "Payments Platform API",
    "owner": "12345678",
    "updatedAt": "2026-08-14T09:12:00.000Z",
}
BILLING = {"id": "2222", "uid": "12345678-aaaa-bbbb-cccc-ddddeeeeffff", "name": "Billing"}

LISTED = {"collections": [PAYMENTS, BILLING]}
UNREADABLE = {"status": "ok", "count": 1}
IMPORTED = {"collection": {"id": CREATED_ID, "name": "Payments Platform API", "endpointCount": 17}}


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))


def calls(monkeypatch: pytest.MonkeyPatch, *responses: Any) -> list[dict[str, Any]]:
    """Answer each send_json in turn and record what was sent."""
    seen: list[dict[str, Any]] = []
    queue = list(responses)

    def fake(url: str, **kwargs: Any) -> Any:
        seen.append({**kwargs, "url": url})
        reply = queue.pop(0) if queue else None
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(service, "send_json", fake)
    return seen


def nothing_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("nothing should have been sent")

    monkeypatch.setattr(service, "send_json", fail)


class TestListing:
    def test_it_posts_the_key_to_the_collections_route(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED)
        service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert seen[0]["url"] == f"{BASE_URL}/api/companies/{COMPANY}/postman/collections"
        assert seen[0]["method"] == "POST"
        assert seen[0]["payload"] == {"apiKey": KEY}

    def test_the_key_never_goes_in_the_url(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """A query string is logged by proxies and kept in server logs."""
        seen = calls(monkeypatch, LISTED)
        service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert KEY not in seen[0]["url"]

    def test_it_reports_what_the_key_can_see(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED)
        result = service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert result.workspace == "Theneo"
        assert result.collections == (
            PostmanCollection(
                uid=PAYMENTS["uid"],
                name="Payments Platform API",
                id="1111",
                owner="12345678",
                updated_at="2026-08-14T09:12:00.000Z",
            ),
            PostmanCollection(uid=BILLING["uid"], name="Billing", id="2222"),
        )

    def test_an_empty_account_lists_nothing_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, {"collections": []})
        result = service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert result.collections == ()

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"collections": [PAYMENTS]}, id="collections"),
            pytest.param({"data": [PAYMENTS]}, id="data"),
            pytest.param([PAYMENTS], id="bare-list"),
        ],
    )
    def test_the_rows_are_found_whatever_envelope_they_arrive_in(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, body: Any
    ) -> None:
        calls(monkeypatch, body)
        result = service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert [item.name for item in result.collections] == ["Payments Platform API"]

    def test_a_row_without_any_id_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, {"collections": [{"name": "Nameless"}]})
        with pytest.raises(ApiError):
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)

    def test_a_response_that_is_not_a_list_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, {"collections": "nope"})
        with pytest.raises(ApiError):
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)


class TestImporting:
    def test_it_posts_the_chosen_uid_to_the_import_route(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED, IMPORTED)
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert seen[1]["url"] == f"{BASE_URL}/api/companies/{COMPANY}/postman/import"
        assert seen[1]["payload"] == {"apiKey": KEY, "collectionIds": [BILLING["uid"]]}

    def test_it_reports_the_collection_it_created_and_a_link(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, IMPORTED)
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result == PostmanImportResult(
            collection="Payments Platform API",
            collection_id=CREATED_ID,
            workspace="Theneo",
            postman_collection="Payments Platform API",
            postman_uid=PAYMENTS["uid"],
            endpoints=17,
            url=f"https://app.getelva.ai/collections?selected={CREATED_ID}",
        )

    def test_a_bare_document_is_accepted_as_well_as_an_envelope(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, {"id": CREATED_ID, "name": "Billing", "endpoints": []})
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID
        assert result.endpoints == 0

    def test_a_response_without_an_id_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, {"collection": {"name": "Billing"}})
        with pytest.raises(ApiError):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_a_duplicate_name_in_elva_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(409, None))
        with pytest.raises(UsageError, match="already exists"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_a_collection_that_vanished_from_postman_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(404, "Collection not found"))
        with pytest.raises(UsageError, match="no longer has"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_a_404_the_backend_did_not_explain_is_not_blamed_on_postman(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """A bare 404 is the route missing far more often than a collection
        being deleted between two requests a second apart. Calling it a deleted
        collection would send the user to look in Postman for something that
        never moved, and exit 2 would tell CI to stop retrying."""
        calls(monkeypatch, LISTED, HttpError(404, None))
        with pytest.raises(ApiError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.API


class TestChoosing:
    """A name, an id, or a question -- never a guess."""

    def test_a_name_matches_case_insensitively(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED, IMPORTED)
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection="  billing  ")
        assert seen[1]["payload"]["collectionIds"] == [BILLING["uid"]]

    def test_a_postman_id_skips_the_listing_altogether(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The id is already the answer. Looking it up would spend a round trip
        confirming it, and would make the import depend on that collection
        coming back in the list route's answer."""
        seen = calls(monkeypatch, IMPORTED)
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        assert len(seen) == 1
        assert seen[0]["url"].endswith("/postman/import")
        assert seen[0]["payload"]["collectionIds"] == [BILLING["uid"]]

    def test_an_id_beyond_what_the_list_route_returned_still_imports(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """An account with more collections than the list route hands back must
        still be able to import one by id."""
        unlisted = "12345678-0c1f0d3e-1111-2222-3333-444455556666"
        seen = calls(monkeypatch, IMPORTED)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection=unlisted)
        assert seen[0]["payload"]["collectionIds"] == [unlisted]
        assert result.postman_uid == unlisted

    def test_a_direct_import_does_not_claim_a_name_it_never_saw(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, IMPORTED)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        assert result.postman_collection is None

    def test_a_bare_id_that_is_not_a_uuid_is_still_looked_up(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """`id` on a Postman row is not always uuid-shaped, so the listing is
        still how a value like that gets resolved."""
        seen = calls(monkeypatch, LISTED, IMPORTED)
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["id"])
        assert len(seen) == 2
        assert seen[1]["payload"]["collectionIds"] == [BILLING["uid"]]

    def test_a_name_still_costs_a_listing(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED, IMPORTED)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert len(seen) == 2
        assert result.postman_collection == "Billing"

    def test_an_unknown_name_lists_what_was_there(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED)
        with pytest.raises(UsageError, match="no Postman collection named 'Nope'") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Nope")
        assert "Billing" in (caught.value.hint or "")

    def test_two_collections_with_one_name_is_refused_rather_than_guessed(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        twins = {"collections": [BILLING, {**BILLING, "id": "3333", "uid": "u-3333"}]}
        calls(monkeypatch, twins)
        with pytest.raises(UsageError, match="2 Postman collections are named") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert "u-3333" in (caught.value.hint or "")

    def test_no_name_and_nobody_to_ask_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The non-interactive contract: exit 2, and say what was available."""
        calls(monkeypatch, LISTED)
        with pytest.raises(UsageError, match="no Postman collection was named") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.USAGE
        assert "Billing" in (caught.value.hint or "")

    def test_no_name_with_a_picker_asks(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED, IMPORTED)
        offered: list[str] = []

        def choose(found: Any) -> Any:
            offered.extend(item.name for item in found)
            return found[1]

        service.import_postman(base_url=BASE_URL, api_key=KEY, choose=choose)
        assert offered == ["Payments Platform API", "Billing"]
        assert seen[1]["payload"]["collectionIds"] == [BILLING["uid"]]

    def test_a_picker_that_invents_a_collection_is_not_trusted(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED)
        made_up = PostmanCollection(uid="elsewhere", name="Elsewhere")
        with pytest.raises(Exception, match="not offered"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, choose=lambda _: made_up)

    def test_an_empty_postman_account_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, {"collections": []})
        with pytest.raises(UsageError, match="cannot see any collections"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")


class TestTheKeyIsChecked:
    """Local checks, so a mangled key costs no round trip and no log line."""

    @pytest.mark.parametrize("key", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
    def test_an_empty_key_is_usage(self, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="no Postman API key"):
            service.list_postman_collections(base_url=BASE_URL, api_key=key)

    def test_a_key_with_whitespace_in_it_is_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="whitespace"):
            service.list_postman_collections(base_url=BASE_URL, api_key="PMAK-ab cd")

    def test_an_absurdly_long_key_is_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="the limit is"):
            service.list_postman_collections(base_url=BASE_URL, api_key="x" * (service.MAX_KEY + 1))

    def test_a_rejected_key_is_never_quoted_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        nothing_sent(monkeypatch)
        secret = "PMAK-" + "s" * (service.MAX_KEY + 1)
        with pytest.raises(UsageError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=secret)
        assert secret not in str(caught.value)
        assert secret not in (caught.value.hint or "")

    def test_the_key_is_trimmed_before_it_is_sent(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED)
        service.list_postman_collections(base_url=BASE_URL, api_key=f"  {KEY}\n")
        assert seen[0]["payload"] == {"apiKey": KEY}


class TestTheKeyNeedsTls:
    """Somebody else's credential does not go out in the clear."""

    def test_a_plaintext_base_url_is_refused_before_anything_is_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="refusing to send") as caught:
            service.list_postman_collections(base_url="http://api.example.com", api_key=KEY)
        assert caught.value.exit_code == ExitCode.USAGE

    @pytest.mark.parametrize(
        "base",
        [
            pytest.param("http://localhost:5001", id="localhost"),
            pytest.param("http://127.0.0.1:5001", id="ipv4"),
            pytest.param("http://elva.localhost:5001", id="localhost-suffix"),
        ],
    )
    def test_loopback_is_exempt_so_local_development_still_works(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, base: str
    ) -> None:
        calls(monkeypatch, LISTED)
        assert service.list_postman_collections(base_url=base, api_key=KEY).collections


class TestRejectedKeysExitThree:
    """A bad or expired Postman key is a credential problem, not a bug and not
    a bad invocation."""

    @pytest.mark.parametrize("status", [401, 403])
    def test_an_unauthorised_response_is_an_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, status: int
    ) -> None:
        calls(monkeypatch, HttpError(status, None))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_flattened_four_hundred_about_the_key_is_still_an_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Backends routinely turn an upstream 401 into a 400. Exit 4 would
        tell the caller their input was wrong, which it was not."""
        calls(monkeypatch, HttpError(400, "The provided API key is invalid or expired"))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.AUTH

    @pytest.mark.parametrize(
        "detail",
        [
            pytest.param("apiKey is required", id="required"),
            pytest.param("apiKey must be a string", id="wrong-type"),
            pytest.param("body.apiKey should not be empty", id="empty"),
        ],
    )
    def test_a_400_that_only_names_the_field_is_not_read_as_a_bad_key(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, detail: str
    ) -> None:
        """That is what a backend says when *this* code sends the wrong body,
        and the field names are an assumption. Reading it as a bad key would
        have the user rotating a Postman key that was fine, forever."""
        calls(monkeypatch, HttpError(400, detail))
        with pytest.raises(ValidationError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.VALIDATION

    @pytest.mark.parametrize(
        "detail",
        [
            pytest.param("The provided API key is invalid or expired", id="invalid"),
            pytest.param("Postman API key was revoked", id="revoked"),
            pytest.param("Unauthorized", id="bare-unauthorized"),
        ],
    )
    def test_a_400_that_says_the_key_was_refused_is_an_auth_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, detail: str
    ) -> None:
        calls(monkeypatch, HttpError(400, detail))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.AUTH

    def test_a_four_hundred_about_anything_else_stays_a_validation_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, HttpError(400, "collectionId must be a string"))
        with pytest.raises(ValidationError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.VALIDATION

    def test_a_server_error_is_still_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, HttpError(503, None))
        with pytest.raises(ApiError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.exit_code == ExitCode.API

    def test_the_hint_names_both_credentials_it_could_be(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """A workspace given as an id skips the lookup that would have proved
        the Elva session, so a 401 here is not certain to be the Postman key."""
        calls(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        hint = caught.value.hint or ""
        assert "ELVA_POSTMAN_API_KEY" in hint
        assert "auth login" in hint

    def test_a_server_that_echoes_the_key_back_has_it_taken_out_again(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, HttpError(403, f"key {KEY} was rejected"))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert KEY not in str(caught.value)
        assert "***" in str(caught.value)


class TestThePicker:
    """What the terminal offers, and how the answer maps back."""

    @staticmethod
    def _ctx() -> Any:
        from pathlib import Path

        from elva_cli.context import Ctx, GlobalOptions

        return Ctx(GlobalOptions(), cwd=Path("/"), env={}, tty=True)

    def test_every_label_carries_the_id_as_well_as_the_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two collections can share a name, so a label built from the name
        alone would offer the same line twice with no way to tell them apart."""
        from elva_cli.commands import import_ as command

        twin = PostmanCollection(uid="u-3333", name="Billing")
        found = [PostmanCollection(uid=BILLING["uid"], name="Billing"), twin]
        offered: list[str] = []

        def fake_select(value: Any, *, choices: Any, **_: Any) -> str:
            offered.extend(choices)
            return str(choices[1])

        monkeypatch.setattr("elva_cli.ui.prompts.select", fake_select)
        picked = command.pick_collection(found, self._ctx())

        assert len(set(offered)) == 2
        assert all(item.uid in "".join(offered) for item in found)
        assert picked is twin

    def test_the_answer_maps_back_to_the_collection_it_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from elva_cli.commands import import_ as command

        found = [
            PostmanCollection(uid=PAYMENTS["uid"], name="Payments Platform API"),
            PostmanCollection(uid=BILLING["uid"], name="Billing"),
        ]
        monkeypatch.setattr(
            "elva_cli.ui.prompts.select", lambda value, *, choices, **_: str(choices[0])
        )
        assert command.pick_collection(found, self._ctx()) is found[0]


class TestEditorAccess:
    """Listing needs any access to the workspace; importing needs the editor
    role. A 403 from the import route is that difference, not a bad key."""

    def test_a_forbidden_import_is_not_blamed_on_the_postman_key(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The same key listed collections a moment earlier, so telling the
        user to rotate it would send them nowhere."""
        calls(monkeypatch, LISTED, HttpError(403, "Forbidden"))
        with pytest.raises(AuthError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.AUTH
        assert "permission" in str(caught.value)
        assert "editor" in (caught.value.hint or "")
        assert "postman.co" not in (caught.value.hint or "")

    def test_a_forbidden_direct_import_names_both_possibilities(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Nothing was listed, so the key was never proven either."""
        calls(monkeypatch, HttpError(403, None))
        with pytest.raises(AuthError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        hint = caught.value.hint or ""
        assert "editor" in hint
        assert "ELVA_POSTMAN_API_KEY" in hint

    def test_a_forbidden_listing_is_still_read_as_the_key(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The list route has no role requirement beyond access, so a 403
        there does not carry the same meaning."""
        calls(monkeypatch, HttpError(403, None))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert "postman.co" in (caught.value.hint or "")


class TestForbiddenIsItsOwnCode:
    """Exit 3 covers both "sign in again" and "you may not do this". The
    numeric contract stays put; the error code is what tells them apart."""

    def test_a_permission_failure_keeps_exit_three(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(403, None))
        with pytest.raises(ForbiddenError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.AUTH

    def test_it_is_still_an_auth_error_for_anything_catching_those(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(403, None))
        with pytest.raises(AuthError):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_it_carries_a_code_a_pipeline_can_branch_on(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(403, None))
        with pytest.raises(ForbiddenError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.code == "ELVA_FORBIDDEN"

    def test_a_dead_session_still_reads_as_plain_auth(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Retrying after a login is still the right advice for this one."""
        calls(monkeypatch, HttpError(401, None))
        with pytest.raises(AuthError) as caught:
            service.list_postman_collections(base_url=BASE_URL, api_key=KEY)
        assert caught.value.code == "ELVA_AUTH"


class TestTheImportRouteTakesAnArray:
    """`collectionIds` is plural. One id goes up, so one collection comes back
    -- but the response may well be shaped like the request."""

    def test_one_id_is_sent_as_a_list_of_one(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = calls(monkeypatch, LISTED, IMPORTED)
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert seen[1]["payload"]["collectionIds"] == [BILLING["uid"]]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"collection": {"id": CREATED_ID, "name": "Billing"}}, id="singular"),
            pytest.param({"collections": [{"id": CREATED_ID, "name": "Billing"}]}, id="plural"),
            pytest.param({"imported": [{"id": CREATED_ID, "name": "Billing"}]}, id="imported"),
            pytest.param([{"id": CREATED_ID, "name": "Billing"}], id="bare-list"),
            pytest.param({"id": CREATED_ID, "name": "Billing"}, id="bare-doc"),
        ],
    )
    def test_the_created_collection_is_found_whatever_shape_it_comes_back_in(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, body: Any
    ) -> None:
        calls(monkeypatch, LISTED, body)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID
        assert result.collection == "Billing"

    def test_an_empty_array_back_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Nothing was imported, so there is nothing to report as imported."""
        calls(monkeypatch, LISTED, {"collections": []})
        with pytest.raises(ApiError):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")


class TestASuccessfulImportIsNeverReportedAsAFailure:
    """The route answering 2xx means the import happened. An unreadable reply
    is not a failed import, and saying it is sends the user to retry something
    that already landed -- which then fails as a duplicate."""

    @staticmethod
    def _elva_collections(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
        monkeypatch.setattr(service, "get_json", lambda *a, **k: payload)

    def test_an_unreadable_reply_falls_back_to_finding_the_collection(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, UNREADABLE)
        self._elva_collections(
            monkeypatch,
            {"collections": [{"id": CREATED_ID, "name": "Billing", "endpointCount": 17}]},
        )
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID
        assert result.collection == "Billing"

    def test_the_fallback_still_reports_the_endpoint_count(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """It reads the list route's own row, so the report is as complete as
        one taken straight from the reply."""
        calls(monkeypatch, LISTED, UNREADABLE)
        self._elva_collections(
            monkeypatch,
            {"collections": [{"id": CREATED_ID, "name": "Billing", "endpointCount": 17}]},
        )
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.endpoints == 17

    def test_it_says_the_import_landed_when_the_collection_cannot_be_found(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Still an error -- there is no id to report -- but one that stops the
        user retrying blindly."""
        calls(monkeypatch, LISTED, UNREADABLE)
        self._elva_collections(monkeypatch, {"collections": []})
        with pytest.raises(ApiError, match="was accepted"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_two_collections_of_that_name_is_not_guessed_between(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, UNREADABLE)
        self._elva_collections(
            monkeypatch,
            {
                "collections": [
                    {"id": CREATED_ID, "name": "Billing"},
                    {"id": "x", "name": "Billing"},
                ]
            },
        )
        with pytest.raises(ApiError, match="was accepted"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_a_direct_import_says_it_cannot_name_the_collection(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Addressed by id, so the Postman name was never learned and there is
        nothing to look the new collection up by."""
        calls(monkeypatch, UNREADABLE)
        with pytest.raises(ApiError, match="cannot say which collection"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])

    def test_a_readable_reply_never_costs_the_extra_lookup(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        def fail(*a: Any, **k: Any) -> Any:
            raise AssertionError("should not have looked anything up")

        monkeypatch.setattr(service, "get_json", fail)
        calls(monkeypatch, LISTED, IMPORTED)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID


class TestExtendedJsonIds:
    """A route that has not gone through the same response-shaping as the rest
    of the API can leak a raw Mongo id -- `{"$oid": "..."}` -- instead of the
    plain string every other route sends."""

    def test_an_extended_json_id_on_the_import_reply_is_read(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(
            monkeypatch,
            LISTED,
            {"collection": {"_id": {"$oid": CREATED_ID}, "name": "Billing"}},
        )
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID

    def test_an_extended_json_id_never_needs_the_fallback_lookup(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        def fail(*a: Any, **k: Any) -> Any:
            raise AssertionError("should have read the id directly")

        monkeypatch.setattr(service, "get_json", fail)
        calls(monkeypatch, LISTED, {"collection": {"_id": {"$oid": CREATED_ID}, "name": "Billing"}})
        service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")


class TestTheFallbackTriggersWheneverAnIdCannotBeRead:
    """Not only when the reply is unrecognised outright -- also when it parses
    into something with no id in it. This is the exact shape of the bug seen
    against a real backend: a 2xx reply the CLI could read as a document, but
    not one with a usable id, reported the import as failed."""

    def test_a_parseable_document_with_no_usable_id_still_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, {"collection": {"name": "Billing", "endpoints": []}})
        monkeypatch.setattr(
            service,
            "_look_up",
            lambda **_: {"id": CREATED_ID, "name": "Billing", "endpointCount": 17},
        )
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert result.collection_id == CREATED_ID
        assert result.endpoints == 17


class TestTheResultsShapeIsRead:
    """A real backend answers a rejected import as `{"results": [{"status":
    "failed", "error": "..."}]}` under HTTP 400, not the flat message this
    class of route usually sends. Captured directly against a live server --
    _detail() has already reduced it to plain text by the time it reaches
    here, which is what TestDetailExtractionReadsResults below covers; this
    class tests what _import_error does with that text.

    Every case names 'Billing' in the server's own text on purpose: this is
    also the boundary that stops an unrelated 400 that merely contains the
    phrase "already exists" from being reported as a duplicate name --
    something a live backend proved necessary (see the next class)."""

    def test_a_duplicate_reported_as_400_shows_the_servers_own_words(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Not a message this constructs -- what actually confirmed the
        server meant this collection is also the text worth showing."""
        detail = 'A collection named "Billing" already exists'
        calls(monkeypatch, LISTED, HttpError(400, detail))
        with pytest.raises(UsageError, match=detail) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.USAGE
        assert "rename" in (caught.value.hint or "").lower()

    def test_a_400_that_does_not_say_already_exists_is_not_reclassified(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(400, "collectionIds must be an array"))
        with pytest.raises(ValidationError):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")


class TestANameMatchIsRequiredNotJustThePhrase:
    """ "already exists" alone very nearly misled a real user: it fired for a
    collection ('testing') that provably did not exist, because the server's
    text -- whatever it actually said -- was never checked against the name
    being imported. Requiring the name is what a fabricated, confidently wrong
    sentence needed to not happen again."""

    def test_the_phrase_without_this_collections_name_is_not_a_conflict(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The exact shape of the near-miss: "already exists" is present, but
        about something other than 'Billing'."""
        calls(monkeypatch, LISTED, HttpError(400, "a workspace limit already exists for this plan"))
        with pytest.raises(ValidationError, match="workspace limit"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")

    def test_the_reported_message_is_never_invented(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Even on a genuine match, the words shown are the server's, not a
        template filled in with the collection's name."""
        detail = 'A collection named "Billing" already exists in this company'
        calls(monkeypatch, LISTED, HttpError(400, detail))
        with pytest.raises(UsageError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert str(caught.value) == detail

    def test_matching_is_not_fooled_by_case(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        detail = "a collection named BILLING already exists"
        calls(monkeypatch, LISTED, HttpError(400, detail))
        with pytest.raises(UsageError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert str(caught.value) == detail


class TestDetailExtractionReadsResults:
    """The `results` key was added to http.py on the strength of this one
    real backend, not a guess -- covered again here at the point where it
    actually fired."""

    def test_the_real_captured_body_yields_the_real_message(self) -> None:
        from elva_cli.core.api import http

        body = json.dumps(
            {
                "results": [
                    {
                        "postmanCollectionId": "53432779-6dbfd17a-e087-4e14-884d-b64dd67bb8e3",
                        "status": "failed",
                        "error": 'A collection named "Elva Test Collection" already exists',
                    }
                ]
            }
        ).encode()

        class FakeHTTPError:
            def read(self) -> bytes:
                return body

        assert http._detail(FakeHTTPError()) == (  # type: ignore[arg-type]
            'A collection named "Elva Test Collection" already exists'
        )
