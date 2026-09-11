"""The `elva import postman` flow.

Nothing here touches the network: send_json is replaced and the request it
would have made is asserted on. The recurring theme is the API key -- where it
is allowed to appear, and where it must never appear.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from elva_cli.commands import import_ as command
from elva_cli.core.api.collections import endpoint_count
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

# The shape a real backend answers the import route with, captured against
# prod: a batch, one entry per id sent, the document nested under "collection".
RESULTS_IMPORTED = {
    "results": [
        {
            "postmanCollectionId": PAYMENTS["uid"],
            "status": "imported",
            "collection": {
                "id": CREATED_ID,
                "name": "Payments Platform API",
                "specTitle": "Payments Platform API",
                "specVersion": "1.0.0",
                "endpoints": [
                    {"path": "/pay", "method": "get"},
                    {"path": "/pay", "method": "post"},
                ],
            },
        }
    ]
}


def _results_failed(error: str, *, uid: str = BILLING["uid"]) -> dict[str, Any]:
    return {"results": [{"postmanCollectionId": uid, "status": "failed", "error": error}]}


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))
    # The endpoint-settling poll re-reads the collection over real delays; the
    # flow tests below are not about it, so it is stubbed out here and exercised
    # on its own in TestEndpointsSettleAfterImport.
    monkeypatch.setattr(service, "_settled", lambda doc, **_: doc)


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
            pytest.param(
                {
                    "results": [
                        {"status": "imported", "collection": {"id": CREATED_ID, "name": "Billing"}}
                    ]
                },
                id="results-batch",
            ),
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


class TestTheResultsBatchReply:
    """The shape a real backend actually sends: {"results": [{status,
    collection}]}. The document is nested a level down, and a rejected item
    carries its reason inline instead of as an HTTP error."""

    def test_the_nested_document_is_read_straight_from_the_reply(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        def no_lookup(*a: Any, **k: Any) -> Any:
            raise AssertionError("the reply carried the collection; nothing to look up")

        monkeypatch.setattr(service, "get_json", no_lookup)
        calls(monkeypatch, LISTED, RESULTS_IMPORTED)
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result.collection_id == CREATED_ID
        assert result.endpoints == 2

    def test_a_by_id_import_reads_the_results_reply_without_a_name(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The bug this fixes: addressed by id, the CLI never learned a name,
        so a reply it could not parse left it with nothing to report -- even
        though the import had succeeded."""

        def no_lookup(*a: Any, **k: Any) -> Any:
            raise AssertionError("should not need a lookup")

        monkeypatch.setattr(service, "get_json", no_lookup)
        calls(monkeypatch, RESULTS_IMPORTED)
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection=PAYMENTS["uid"])
        assert result.collection_id == CREATED_ID
        assert result.postman_collection is None

    def test_a_failed_entry_is_raised_not_chased_with_a_lookup(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        def no_lookup(*a: Any, **k: Any) -> Any:
            raise AssertionError("a rejected import has nothing to look up")

        monkeypatch.setattr(service, "get_json", no_lookup)
        calls(monkeypatch, LISTED, _results_failed('A collection named "Billing" already exists'))
        with pytest.raises(UsageError, match="already exists") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.USAGE

    def test_a_failed_entry_that_is_not_a_conflict_is_a_validation_error(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, _results_failed("The Postman collection could not be parsed"))
        with pytest.raises(ValidationError, match="could not be parsed") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert caught.value.exit_code == ExitCode.VALIDATION


class TestEndpointsSettleAfterImport:
    """The import route answers before it has finished reading requests out of
    the Postman collection, so its reply can say 0 endpoints for one that has
    six a second later -- which reads as an empty import. The count is settled
    by re-reading the collection (the same race import_spec._settled handles)."""

    @staticmethod
    def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def _run(
        self, monkeypatch: pytest.MonkeyPatch, imported: dict[str, Any], *reads: Any
    ) -> dict[str, Any]:
        self._no_sleep(monkeypatch)
        queue = list(reads)

        def fake_get(url: str, **_: Any) -> Any:
            reply = queue.pop(0) if queue else reads[-1]
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(service, "get_json", fake_get)
        return service._settled(
            imported, base_url=BASE_URL, token="t", company_id=COMPANY, collection_id=CREATED_ID
        )

    @staticmethod
    def _doc(endpoints: int) -> dict[str, Any]:
        inner = {"id": CREATED_ID, "name": "Bug Testing", "endpoints": [{}] * endpoints}
        return {"collection": inner}

    def test_a_zero_endpoint_reply_is_re_read_until_a_count_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc = self._run(
            monkeypatch,
            {"id": CREATED_ID, "name": "Bug Testing", "endpoints": []},
            self._doc(3),  # extraction still running
            self._doc(6),  # done -- but not yet confirmed
            self._doc(6),  # holds -> settled
        )
        assert endpoint_count(doc) == 6

    def test_a_reply_that_already_carries_a_count_is_not_polled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_read(*a: Any, **k: Any) -> Any:
            raise AssertionError("the reply had a count; nothing to poll")

        monkeypatch.setattr(service, "get_json", no_read)
        doc = service._settled(
            {"id": CREATED_ID, "endpoints": [{}, {}]},
            base_url=BASE_URL,
            token="t",
            company_id=COMPANY,
            collection_id=CREATED_ID,
        )
        assert endpoint_count(doc) == 2

    def test_a_collection_that_stays_empty_settles_to_zero_without_hanging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = {"id": CREATED_ID, "endpoints": []}
        doc = self._run(monkeypatch, original, *([self._doc(0)] * 4))
        assert endpoint_count(doc) == 0

    def test_a_failed_re_read_falls_back_to_the_import_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = {"id": CREATED_ID, "name": "Bug Testing", "endpoints": []}
        assert self._run(monkeypatch, original, HttpError(500, None)) is original

    def test_the_import_flow_reports_the_settled_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))
        calls(
            monkeypatch,
            {
                "results": [
                    {
                        "status": "imported",
                        "collection": {"id": CREATED_ID, "name": "Bug Testing", "endpoints": []},
                    }
                ]
            },
        )
        monkeypatch.setattr(service, "get_json", lambda *a, **k: self._doc(6))
        result = service.import_postman(base_url=BASE_URL, api_key=KEY, collection=PAYMENTS["uid"])
        assert result.endpoints == 6


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

    def test_a_by_id_duplicate_is_a_usage_error_even_without_a_name_to_match(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """Addressed by id, the CLI's only "name" for the collection is the id
        itself, so _named_conflict cannot fire -- but "a collection ... already
        exists" is still unambiguously a rename, not a bad request (exit 4)."""
        detail = 'A collection named "Billing" already exists'
        calls(monkeypatch, HttpError(400, detail))
        with pytest.raises(UsageError, match="already exists") as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        assert caught.value.exit_code == ExitCode.USAGE

    def test_an_unrelated_already_exists_400_still_needs_the_word_collection(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The by-id fallback keys on "collection" + "already exists"; a phrase
        about something else is left as the validation error it is."""
        calls(monkeypatch, HttpError(400, "a workspace limit already exists for this plan"))
        with pytest.raises(ValidationError, match="workspace limit"):
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])


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


class TestEveryServerMessageIsScrubbedNotJustSome:
    """Redaction used to be opt-in at each use of `error.detail`, and the
    conflict branch -- `_named_conflict(...) or _collection_conflict(...)`, both
    of which return the server's text verbatim -- did not opt in. The key is
    unlikely to be in a name-clash message today, but `http._detail` now reads
    `errors` and `results` three levels deep, so there is more server text
    reaching the user across every branch, and the next branch added here would
    have inherited the same gap. `_scrubbed` now cleans the HttpError at the
    two request helpers, so no branch has to remember.
    """

    def test_a_conflict_message_that_echoes_the_key_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        detail = f'A collection named "Billing" already exists (key {KEY})'
        calls(monkeypatch, LISTED, HttpError(400, detail))
        with pytest.raises(UsageError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert KEY not in str(caught.value)
        assert "***" in str(caught.value)
        assert caught.value.exit_code == ExitCode.USAGE

    def test_a_by_id_conflict_message_that_echoes_the_key_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        detail = f"collection already exists; apiKey={KEY}"
        calls(monkeypatch, HttpError(400, detail))
        with pytest.raises(UsageError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        assert KEY not in str(caught.value)

    def test_a_validation_message_that_echoes_the_key_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, HttpError(422, f"apiKey {KEY} is malformed"))
        with pytest.raises(ValidationError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection="Billing")
        assert KEY not in str(caught.value)

    def test_a_failed_results_entry_that_echoes_the_key_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """A rejection inside a 200 body never went through an HttpError at
        all, so it missed redaction even harder than the conflict branch did."""
        calls(monkeypatch, _results_failed(f"Postman refused the key {KEY}"))
        with pytest.raises(ValidationError) as caught:
            service.import_postman(base_url=BASE_URL, api_key=KEY, collection=BILLING["uid"])
        assert KEY not in str(caught.value)
        assert "***" in str(caught.value)


class TestAnUnknownStatusIsNotAFailure:
    """`status != "imported"` was read as a rejection. The route's vocabulary
    is an assumption -- "imported" is the only value this has actually seen --
    so a backend answering "success" or "queued" made the CLI report exit 4 for
    an import that happened, which a user answers by running it again into a
    duplicate."""

    @staticmethod
    def _entry(status: str) -> dict[str, Any]:
        """A result entry with a status and nothing else to read: no nested
        collection, no error. The shape the guess was about."""
        return {"results": [{"postmanCollectionId": PAYMENTS["uid"], "status": status}]}

    @pytest.mark.parametrize("status", ["success", "ok", "created", "queued", "complete"])
    def test_an_unrecognised_status_falls_through_to_the_lookup(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, status: str
    ) -> None:
        found = {"collections": [{"id": CREATED_ID, "name": "Payments Platform API"}]}
        calls(monkeypatch, LISTED, self._entry(status))
        monkeypatch.setattr(service, "get_json", lambda *a, **k: found)
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result.collection_id == CREATED_ID

    @pytest.mark.parametrize("status", ["failed", "error", "rejected", "skipped"])
    def test_an_explicit_failure_is_still_a_failure(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, status: str
    ) -> None:
        calls(monkeypatch, LISTED, self._entry(status))
        with pytest.raises(ValidationError, match="did not complete"):
            service.import_postman(
                base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
            )

    def test_a_failure_with_a_reason_still_reports_the_reason(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The `error` string is read before `status`, and still is."""
        calls(monkeypatch, LISTED, _results_failed("Postman rate limit exceeded"))
        with pytest.raises(ValidationError, match="rate limit"):
            service.import_postman(
                base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
            )


class TestTheFallbackWillNotAdoptAnOlderNamesake:
    """_look_up finds the new collection by name, but Elva does not stop two
    collections sharing one. Import 'Billing' today after importing it last
    week, get a reply _import_outcome cannot read, and the name match returns
    the week-old collection -- whose id, endpoint count and link then get
    reported as this import's result, with _settled polling the wrong
    document."""

    @staticmethod
    def _listing(created_at: str | None) -> dict[str, Any]:
        row: dict[str, Any] = {"id": CREATED_ID, "name": "Payments Platform API"}
        if created_at is not None:
            row["createdAt"] = created_at
        return {"collections": [row]}

    def test_a_collection_from_last_week_is_refused_rather_than_reported(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        calls(monkeypatch, LISTED, UNREADABLE)
        monkeypatch.setattr(
            service, "get_json", lambda *a, **k: self._listing("2026-08-14T09:12:00.000Z")
        )
        with pytest.raises(ApiError, match="already existed before") as caught:
            service.import_postman(
                base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
            )
        assert "before importing again" in (caught.value.hint or "")

    def test_a_collection_created_just_now_is_still_accepted(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        import datetime

        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        calls(monkeypatch, LISTED, UNREADABLE)
        monkeypatch.setattr(service, "get_json", lambda *a, **k: self._listing(now))
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result.collection_id == CREATED_ID

    def test_a_server_clock_a_little_behind_is_not_treated_as_last_week(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """The comparison is between two clocks, so it carries slack. Costing
        a user a real result over a minute of skew would be the worse bug."""
        import datetime

        skewed = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
        calls(monkeypatch, LISTED, UNREADABLE)
        monkeypatch.setattr(
            service,
            "get_json",
            lambda *a, **k: self._listing(skewed.isoformat().replace("+00:00", "Z")),
        )
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result.collection_id == CREATED_ID

    @pytest.mark.parametrize("stamp", [None, "not a date", ""])
    def test_a_timestamp_this_cannot_read_does_not_block_the_import(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, stamp: str | None
    ) -> None:
        """No createdAt is how this behaved before the check existed. A parse
        failure is not evidence the collection is old."""
        calls(monkeypatch, LISTED, UNREADABLE)
        monkeypatch.setattr(service, "get_json", lambda *a, **k: self._listing(stamp))
        result = service.import_postman(
            base_url=BASE_URL, api_key=KEY, collection="Payments Platform API"
        )
        assert result.collection_id == CREATED_ID
