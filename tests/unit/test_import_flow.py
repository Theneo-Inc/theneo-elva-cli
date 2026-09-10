from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from elva_cli.core.api.collections import collection_link
from elva_cli.core.api.http import HttpError
from elva_cli.core.api.targets import Target
from elva_cli.core.services import import_spec as service
from elva_cli.core.services.import_result import DryRunResult, ImportSpecResult
from elva_cli.errors import ApiError, AuthError, UsageError, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

BASE_URL = "https://api.getelva.ai"
COMPANY = "0123456789abcdef01234567"
COLLECTION = "89abcdef0123456789abcdef"

OPENAPI = (
    b'openapi: 3.0.3\ninfo:\n  title: Payments\n  version: "2.1"\npaths:\n  /a:\n    get: {}\n'
)
POSTMAN = (
    b'{"info": {"_postman_id": "abc", "schema": '
    b'"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"}}'
)
CREATED = {
    "collection": {
        "id": COLLECTION,
        "name": "Payments",
        "specTitle": "Payments",
        "specVersion": "2.1",
        "endpointCount": 1,
    }
}


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "payments.yaml"
    path.write_bytes(OPENAPI)
    return path


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
    monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))
    monkeypatch.setattr(
        service, "resolve_collection", lambda **_: Target(COLLECTION, "payments-api")
    )
    monkeypatch.setattr(service, "_settled", lambda uploaded, **_: (uploaded, True, ()))


def form(monkeypatch: pytest.MonkeyPatch, response: Any = CREATED) -> dict[str, Any]:
    """Replace the multipart call and record the request it would have made."""
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs, url=url)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(service, "send_form", fake)
    return seen


def body(monkeypatch: pytest.MonkeyPatch, response: Any = CREATED) -> dict[str, Any]:
    """Same, for the JSON path used by --url."""
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs, url=url)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(service, "send_json", fake)
    return seen


def nothing_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("nothing should have been sent")

    monkeypatch.setattr(service, "send_form", fail)
    monkeypatch.setattr(service, "send_json", fail)


class TestCreate:
    """Creating is the default: POST, with the name as a form field."""

    def test_it_posts_to_the_collections_route(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=spec_file)
        assert seen["url"] == f"{BASE_URL}/api/companies/{COMPANY}/collections"
        assert seen["method"] == "POST"
        assert seen["field"] == "spec"

    def test_it_reports_the_created_collection_and_a_link(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch)
        result = service.import_spec(base_url=BASE_URL, path=spec_file)
        assert result == ImportSpecResult(
            action="created",
            collection="Payments",
            collection_id=COLLECTION,
            workspace="Theneo",
            source="payments.yaml",
            spec_format="openapi",
            endpoints=1,
            spec_title="Payments",
            spec_version="2.1",
            url=f"https://app.getelva.ai/collections?selected={COLLECTION}",
        )

    def test_the_file_goes_up_byte_for_byte(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=spec_file)
        assert seen["data"] == OPENAPI
        assert seen["filename"] == "payments.yaml"

    def test_a_duplicate_name_points_at_update(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, HttpError(409, 'A collection named "Payments" already exists'))
        with pytest.raises(UsageError) as caught:
            service.import_spec(base_url=BASE_URL, path=spec_file)
        assert caught.value.hint is not None
        assert "--update" in caught.value.hint

    def test_a_response_without_an_id_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, {"collection": {"name": "Payments"}})
        with pytest.raises(ApiError):
            service.import_spec(base_url=BASE_URL, path=spec_file)


class TestNaming:
    """--name, else the spec's own title, else a prompt."""

    def test_the_flag_wins(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=spec_file, name="Chosen")
        assert seen["fields"] == {"name": "Chosen"}

    def test_it_falls_back_to_the_spec_title(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=spec_file)
        assert seen["fields"] == {"name": "Payments"}

    def test_a_titleless_spec_prompts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, signed_in: None
    ) -> None:
        path = tmp_path / "bare.yaml"
        path.write_bytes(b"openapi: 3.0.3\npaths: {}\n")
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=path, prompt_for_name=lambda: "Asked For")
        assert seen["fields"] == {"name": "Asked For"}

    def test_no_title_and_nobody_to_ask_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, signed_in: None
    ) -> None:
        path = tmp_path / "bare.yaml"
        path.write_bytes(b"openapi: 3.0.3\npaths: {}\n")
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError) as caught:
            service.import_spec(base_url=BASE_URL, path=path)
        assert caught.value.hint is not None
        assert "--name" in caught.value.hint

    def test_a_name_over_the_api_limit_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="limit is 100"):
            service.import_spec(base_url=BASE_URL, path=spec_file, name="x" * 101)

    def test_a_blank_name_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="blank"):
            service.import_spec(base_url=BASE_URL, path=spec_file, name="   ")


class TestUpdate:
    """--update is the only way to overwrite an existing collection."""

    def test_it_patches_the_resolved_collection(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        seen = form(monkeypatch, {"collection": {"id": COLLECTION, "name": "payments-api"}})
        result = service.import_spec(
            base_url=BASE_URL, path=spec_file, collection="payments-api", update=True
        )
        assert seen["method"] == "PATCH"
        assert seen["url"].endswith(f"/collections/{COLLECTION}")
        assert result.action == "updated"

    def test_it_sends_no_name_field(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        """Updating replaces a spec; it must not quietly rename the collection."""
        seen = form(monkeypatch, {"collection": {"id": COLLECTION, "name": "payments-api"}})
        service.import_spec(
            base_url=BASE_URL, path=spec_file, collection="payments-api", update=True
        )
        assert seen["fields"] == {}

    def test_update_without_a_collection_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="which collection"):
            service.import_spec(base_url=BASE_URL, path=spec_file, update=True)

    def test_name_with_update_is_refused_rather_than_ignored(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        """--update replaces a spec and never renames, so accepting --name
        here would report a success in which one flag did nothing."""
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="cannot be combined"):
            service.import_spec(
                base_url=BASE_URL,
                path=spec_file,
                collection="payments-api",
                name="Renamed",
                update=True,
            )

    def test_creating_never_overwrites(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        """Without --update, a --collection is not a target -- it is ignored,
        and the request is still a POST."""
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=spec_file, collection="payments-api")
        assert seen["method"] == "POST"


class TestUrlSource:
    def test_a_url_is_handed_to_the_server(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = body(monkeypatch)
        service.import_spec(base_url=BASE_URL, spec_url="https://x.dev/o.yaml", name="Remote")
        assert seen["payload"] == {"name": "Remote", "specUrl": "https://x.dev/o.yaml"}
        assert seen["method"] == "POST"

    def test_a_url_needs_a_name_because_nothing_is_read_locally(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="no name"):
            service.import_spec(base_url=BASE_URL, spec_url="https://x.dev/o.yaml")

    def test_a_non_http_url_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="http"):
            service.import_spec(base_url=BASE_URL, spec_url="ftp://x.dev/o.yaml", name="X")


class TestStdin:
    def test_it_uploads_what_was_piped_in(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        result = service.import_spec(base_url=BASE_URL, stdin=OPENAPI)
        assert seen["data"] == OPENAPI
        assert result.source == "<stdin>"

    def test_it_gets_a_filename_the_route_will_accept(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, stdin=OPENAPI)
        assert seen["filename"].endswith((".json", ".yaml", ".yml"))

    def test_empty_stdin_is_usage(self, monkeypatch: pytest.MonkeyPatch, signed_in: None) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="empty"):
            service.import_spec(base_url=BASE_URL, stdin=b"   \n")


class TestExactlyOneSource:
    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({}, id="none"),
            pytest.param({"stdin": OPENAPI, "spec_url": "https://x.dev/o"}, id="stdin-and-url"),
        ],
    )
    def test_it_insists_on_one(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None, kwargs: Any
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="exactly one"):
            service.import_spec(base_url=BASE_URL, **kwargs)


class TestRefusedBeforeTheNetwork:
    """Everything here fails without a token being fetched or a byte sent."""

    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def no_token(*, base_url: str) -> str:
            raise AssertionError("should not have asked for a token")

        monkeypatch.setattr(service, "get_access_token", no_token)
        nothing_sent(monkeypatch)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(UsageError, match="no such file"):
            service.import_spec(base_url=BASE_URL, path=tmp_path / "nope.yaml")

    def test_a_directory_is_not_a_spec(self, tmp_path: Path) -> None:
        with pytest.raises(UsageError, match="directory"):
            service.import_spec(base_url=BASE_URL, path=tmp_path)

    @pytest.mark.parametrize("suffix", [".txt", ".xml", ".openapi", ""])
    def test_an_unsupported_extension_names_what_is_allowed(
        self, tmp_path: Path, suffix: str
    ) -> None:
        path = tmp_path / f"spec{suffix}"
        path.write_bytes(OPENAPI)
        with pytest.raises(UsageError, match=r"\.json, \.yaml, \.yml"):
            service.import_spec(base_url=BASE_URL, path=path)

    @pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml", ".YAML"])
    def test_the_allowed_extensions_get_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, suffix: str
    ) -> None:
        path = tmp_path / f"spec{suffix}"
        path.write_bytes(OPENAPI)
        monkeypatch.setattr(service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(service, "resolve_workspace", lambda **_: Target(COMPANY, "Theneo"))
        form(monkeypatch)
        assert service.import_spec(base_url=BASE_URL, path=path).action == "created"

    def test_an_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_bytes(b"   \n\n")
        with pytest.raises(UsageError, match="empty"):
            service.import_spec(base_url=BASE_URL, path=path)

    def test_a_file_over_the_upload_limit_names_it(self, tmp_path: Path) -> None:
        path = tmp_path / "huge.json"
        path.write_bytes(b'{"openapi":"3.0.0"}' + b" " * (10 * 1024 * 1024))
        with pytest.raises(UsageError, match="10 MB"):
            service.import_spec(base_url=BASE_URL, path=path)

    def test_an_unrecognisable_file_suggests_the_flag(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.json"
        path.write_bytes(b'{"nothing": "recognisable"}')
        with pytest.raises(UsageError) as caught:
            service.import_spec(base_url=BASE_URL, path=path)
        assert caught.value.hint is not None
        assert "--format" in caught.value.hint

    def test_an_unknown_format_lists_the_valid_ones(self, spec_file: Path) -> None:
        with pytest.raises(UsageError) as caught:
            service.import_spec(base_url=BASE_URL, path=spec_file, spec_format="raml")
        assert caught.value.hint is not None
        assert "openapi" in caught.value.hint


class TestPostmanIsRefused:
    """The collection route runs extractEndpoints over whatever it is sent, and
    that understands OpenAPI only -- a Postman collection uploads fine and
    yields nothing. The backend's own Postman importer pulls from Postman's API
    and takes no file, which is ELVA-162's job."""

    @pytest.fixture
    def postman_file(self, tmp_path: Path) -> Path:
        path = tmp_path / "collection.json"
        path.write_bytes(POSTMAN)
        return path

    def test_a_detected_postman_collection_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, postman_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="Postman collection"):
            service.import_spec(base_url=BASE_URL, path=postman_file)

    def test_it_is_refused_before_a_token_is_fetched(
        self, monkeypatch: pytest.MonkeyPatch, postman_file: Path
    ) -> None:
        def no_token(*, base_url: str) -> str:
            raise AssertionError("should not have asked for a token")

        monkeypatch.setattr(service, "get_access_token", no_token)
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError):
            service.import_spec(base_url=BASE_URL, path=postman_file)

    def test_the_flag_is_refused_too(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="Postman collection"):
            service.import_spec(base_url=BASE_URL, path=spec_file, spec_format="postman")

    def test_format_openapi_cannot_overrule_a_detected_collection(
        self, monkeypatch: pytest.MonkeyPatch, postman_file: Path, signed_in: None
    ) -> None:
        """The refusal's own hint used to recommend this flag, which walked the
        user straight back into the empty collection it exists to prevent."""
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="Postman collection"):
            service.import_spec(
                base_url=BASE_URL, path=postman_file, name="Forced", spec_format="openapi"
            )

    def test_the_hint_no_longer_recommends_the_flag(
        self, monkeypatch: pytest.MonkeyPatch, postman_file: Path, signed_in: None
    ) -> None:
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError) as caught:
            service.import_spec(base_url=BASE_URL, path=postman_file)
        assert "--format openapi" not in (caught.value.hint or "")

    def test_format_openapi_still_rescues_an_undetectable_document(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, signed_in: None
    ) -> None:
        """Detection has real gaps (a BOM, minified JSON), so the override has
        to keep working where the document is merely ambiguous."""
        path = tmp_path / "unmarked.json"
        path.write_bytes(b'{"info": {"title": "Payments"}, "paths": {}}')
        seen = form(monkeypatch)
        service.import_spec(base_url=BASE_URL, path=path, name="Forced", spec_format="openapi")
        assert seen["method"] == "POST"

    def test_format_postman_is_refused_on_a_url_too(
        self, monkeypatch: pytest.MonkeyPatch, signed_in: None
    ) -> None:
        """--url sends no bytes to sniff, so the declared format is all there is."""
        nothing_sent(monkeypatch)
        with pytest.raises(UsageError, match="Postman collection"):
            service.import_spec(
                base_url=BASE_URL,
                spec_url="https://example.com/collection.json",
                spec_format="postman",
                name="X",
            )


class TestDryRun:
    def test_it_sends_nothing_at_all(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path
    ) -> None:
        """Not even a token: --dry-run works signed out."""

        def no_token(*, base_url: str) -> str:
            raise AssertionError("should not have asked for a token")

        monkeypatch.setattr(service, "get_access_token", no_token)
        nothing_sent(monkeypatch)

        result = service.import_spec(base_url=BASE_URL, path=spec_file, dry_run=True)
        assert isinstance(result, DryRunResult)

    def test_it_reports_what_would_be_created(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path
    ) -> None:
        nothing_sent(monkeypatch)
        result = service.import_spec(base_url=BASE_URL, path=spec_file, dry_run=True)
        assert result == DryRunResult(
            action="create",
            collection="Payments",
            source="payments.yaml",
            spec_format="openapi",
            endpoints=1,
            spec_title="Payments",
            spec_version="2.1",
            size_bytes=len(OPENAPI),
        )

    def test_it_says_update_under_update(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path
    ) -> None:
        nothing_sent(monkeypatch)
        result = service.import_spec(
            base_url=BASE_URL, path=spec_file, collection="payments-api", update=True, dry_run=True
        )
        assert result.action == "update"
        assert result.collection == "payments-api"

    def test_it_still_refuses_a_bad_invocation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--dry-run reports what would happen, so it must fail on what could not."""
        nothing_sent(monkeypatch)
        path = tmp_path / "spec.txt"
        path.write_bytes(OPENAPI)
        with pytest.raises(UsageError):
            service.import_spec(base_url=BASE_URL, path=path, dry_run=True)


class TestErrorMapping:
    """The exit-code contract. See docs/exit-codes.md."""

    def test_a_rejected_spec_is_validation_not_api(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, HttpError(422, "path / has no verb"))
        with pytest.raises(ValidationError, match="path / has no verb"):
            service.import_spec(base_url=BASE_URL, path=spec_file)

    def test_an_unsupported_file_type_is_validation(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, HttpError(400, "Unsupported file type."))
        with pytest.raises(ValidationError, match="Unsupported file type"):
            service.import_spec(base_url=BASE_URL, path=spec_file)

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_credentials_are_auth(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None, status: int
    ) -> None:
        form(monkeypatch, HttpError(status, None))
        with pytest.raises(AuthError):
            service.import_spec(base_url=BASE_URL, path=spec_file)

    def test_500_is_api_so_ci_can_retry(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, HttpError(500, None))
        with pytest.raises(ApiError):
            service.import_spec(base_url=BASE_URL, path=spec_file)

    def test_404_on_update_is_usage(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None
    ) -> None:
        form(monkeypatch, HttpError(404, None))
        with pytest.raises(UsageError, match="no collection named"):
            service.import_spec(
                base_url=BASE_URL, path=spec_file, collection="payments-api", update=True
            )

    def test_not_signed_in_never_reaches_the_network(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path
    ) -> None:
        def no_credentials(*, base_url: str) -> str:
            raise AuthError("You're not logged in.")

        monkeypatch.setattr(service, "get_access_token", no_credentials)
        nothing_sent(monkeypatch)
        with pytest.raises(AuthError):
            service.import_spec(base_url=BASE_URL, path=spec_file)

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param([1, 2], id="not-an-object"),
            pytest.param({"nope": {}}, id="no-collection-key"),
            pytest.param({"collection": "text"}, id="collection-not-an-object"),
        ],
    )
    def test_a_malformed_response_is_an_api_error(
        self, monkeypatch: pytest.MonkeyPatch, spec_file: Path, signed_in: None, response: Any
    ) -> None:
        form(monkeypatch, response)
        with pytest.raises(ApiError):
            service.import_spec(base_url=BASE_URL, path=spec_file)


class TestCollectionLink:
    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            pytest.param(
                "https://api.getelva.ai",
                "https://app.getelva.ai/collections?selected=x",
                id="prod",
            ),
            pytest.param(
                "https://api-staging.getelva.ai",
                "https://app-staging.getelva.ai/collections?selected=x",
                id="staging",
            ),
        ],
    )
    def test_the_web_app_host_is_derived(self, base: str, expected: str) -> None:
        assert collection_link(base, "x") == expected

    def test_an_unrecognised_host_gets_no_link_rather_than_a_wrong_one(self) -> None:
        assert collection_link("http://localhost:5001", "x") is None

    @pytest.mark.parametrize(
        "base",
        [
            pytest.param("https://api2.example.com", id="digit-suffix"),
            pytest.param("https://apidocs.internal", id="word-suffix"),
            pytest.param("https://apple.com", id="unrelated-word"),
        ],
    )
    def test_a_host_that_merely_starts_with_api_gets_no_link(self, base: str) -> None:
        """api2 would map to an app2 that does not exist, and a link to a host
        that is not there is worse than no link at all."""
        assert collection_link(base, "x") is None


class TestPublishedMcps:
    """MCP tools are generated at publish time and are not regenerated by a
    spec update, so the old ones stay live and answering."""

    @staticmethod
    def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def _settled_with(self, monkeypatch: pytest.MonkeyPatch, body: object) -> tuple[str, ...]:
        self._no_sleep(monkeypatch)
        monkeypatch.setattr(service, "get_json", lambda url, **_: body)
        _, _, mcps = service._settled(
            {"specTitle": "Old"},
            base_url=BASE_URL,
            token="t",
            company_id=COMPANY,
            collection_id=COLLECTION,
        )
        return mcps

    def test_published_servers_are_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {
            "collection": {"specTitle": "New"},
            "mcps": [
                {"mcpName": "payments-mcp", "status": "published"},
                {"mcpName": "billing-mcp", "status": "published"},
            ],
        }
        assert self._settled_with(monkeypatch, body) == ("payments-mcp", "billing-mcp")

    def test_unpublished_servers_are_not_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A draft deployment serves nothing, so it cannot be serving a stale
        spec either."""
        body = {
            "collection": {"specTitle": "New"},
            "mcps": [
                {"mcpName": "draft-mcp", "status": "draft"},
                {"mcpName": "live-mcp", "status": "published"},
            ],
        }
        assert self._settled_with(monkeypatch, body) == ("live-mcp",)

    def test_the_slug_stands_in_for_a_missing_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = {
            "collection": {"specTitle": "New"},
            "mcps": [{"mcpSlug": "payments", "status": "published"}],
        }
        assert self._settled_with(monkeypatch, body) == ("payments",)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"collection": {"specTitle": "New"}}, id="no-mcps-key"),
            pytest.param({"collection": {"specTitle": "New"}, "mcps": []}, id="empty"),
            pytest.param({"collection": {"specTitle": "New"}, "mcps": "nope"}, id="not-a-list"),
        ],
    )
    def test_nothing_to_warn_about_yields_nothing(
        self, monkeypatch: pytest.MonkeyPatch, body: object
    ) -> None:
        assert self._settled_with(monkeypatch, body) == ()

    def test_a_failed_read_warns_about_nothing_rather_than_guessing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The upload already succeeded; not knowing is not a reason to claim
        there are stale servers."""
        self._no_sleep(monkeypatch)

        def boom(url: str, **_: object) -> object:
            raise ApiError("down")

        monkeypatch.setattr(service, "get_json", boom)
        _, confirmed, mcps = service._settled(
            {"specTitle": "Old"},
            base_url=BASE_URL,
            token="t",
            company_id=COMPANY,
            collection_id=COLLECTION,
        )
        assert confirmed is False
        assert mcps == ()


class TestSettlingOnUpdate:
    """PATCH answers before the server recomputes metadata; POST does not."""

    @staticmethod
    def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    def test_it_reports_the_settled_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_sleep(monkeypatch)
        stale = {"specTitle": "Old", "endpointCount": 3}
        fresh = {"specTitle": "New", "endpointCount": 1}
        monkeypatch.setattr(service, "get_json", lambda url, **_: {"collection": fresh})
        doc, confirmed, _ = service._settled(
            stale, base_url=BASE_URL, token="t", company_id=COMPANY, collection_id=COLLECTION
        )
        assert doc is fresh
        assert confirmed is True

    def test_values_that_never_move_are_returned_as_they_are(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._no_sleep(monkeypatch)
        same = {"specTitle": "Same", "endpointCount": 2}
        monkeypatch.setattr(service, "get_json", lambda url, **_: {"collection": dict(same)})
        doc, confirmed, _ = service._settled(
            same, base_url=BASE_URL, token="t", company_id=COMPANY, collection_id=COLLECTION
        )
        assert service._metadata(doc) == service._metadata(same)
        assert confirmed is False, "never seeing the value move is not confirmation"

    def test_a_failed_poll_never_fails_the_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._no_sleep(monkeypatch)
        uploaded = {"specTitle": "Old", "endpointCount": 3}

        def boom(url: str, **_: Any) -> Any:
            raise HttpError(500, None)

        monkeypatch.setattr(service, "get_json", boom)
        doc, confirmed, _ = service._settled(
            uploaded,
            base_url=BASE_URL,
            token="t",
            company_id=COMPANY,
            collection_id=COLLECTION,
        )
        assert doc is uploaded
        assert confirmed is False
