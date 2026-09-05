from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from elva_cli.core.services import whoami as whoami_service
from elva_cli.core.services.whoami_result import WhoamiResult
from elva_cli.errors import ApiError, AuthError

BASE_URL = "https://api.getelva.ai"


class TestWhoami:
    def test_jwt_session_reports_just_the_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(whoami_service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(
            whoami_service,
            "_fetch_me",
            lambda base_url, token: {"user": {"id": "u1", "email": "a@b.com"}},
        )
        assert whoami_service.whoami(base_url=BASE_URL) == WhoamiResult(
            email="a@b.com", company_name=None
        )

    def test_pat_reports_the_scoped_company(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(whoami_service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(
            whoami_service,
            "_fetch_me",
            lambda base_url, token: {
                "user": {"id": "u1", "email": "a@b.com"},
                "pat": {"id": "p1", "companyId": "c1", "companyName": "Acme Inc"},
            },
        )
        assert whoami_service.whoami(base_url=BASE_URL) == WhoamiResult(
            email="a@b.com", company_name="Acme Inc"
        )

    def test_pat_without_a_resolved_company_name_reports_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(whoami_service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(
            whoami_service,
            "_fetch_me",
            lambda base_url, token: {
                "user": {"id": "u1", "email": "a@b.com"},
                "pat": {"id": "p1", "companyId": "c1"},
            },
        )
        assert whoami_service.whoami(base_url=BASE_URL) == WhoamiResult(
            email="a@b.com", company_name=None
        )

    def test_not_logged_in_raises_before_any_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_not_logged_in(*, base_url: str) -> str:
            raise AuthError("You're not logged in.")

        monkeypatch.setattr(whoami_service, "get_access_token", raise_not_logged_in)

        def fail_if_called(base_url: str, token: str) -> dict[str, object]:
            raise AssertionError("should not reach the network when not logged in")

        monkeypatch.setattr(whoami_service, "_fetch_me", fail_if_called)

        with pytest.raises(AuthError):
            whoami_service.whoami(base_url=BASE_URL)

    def test_malformed_response_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(whoami_service, "get_access_token", lambda *, base_url: "tok")
        monkeypatch.setattr(whoami_service, "_fetch_me", lambda base_url, token: {"user": {}})
        with pytest.raises(ApiError):
            whoami_service.whoami(base_url=BASE_URL)


class TestRejectedStoredToken:
    """A token that get_access_token handed over but the backend then 401s."""

    @staticmethod
    def _arrange(monkeypatch: pytest.MonkeyPatch, identity: str) -> list[bool]:
        from elva_cli import auth

        monkeypatch.setattr(whoami_service, "get_access_token", lambda *, base_url: "tok")

        def raise_401(base_url: str, token: str) -> dict[str, object]:
            raise AuthError("Your credentials are no longer valid.")

        monkeypatch.setattr(whoami_service, "_fetch_me", raise_401)
        forgotten: list[bool] = []
        monkeypatch.setattr(auth, "current_identity", lambda: identity)
        monkeypatch.setattr(auth, "forget_stored_credentials", lambda: forgotten.append(True))
        return forgotten

    def test_stored_session_is_forgotten_and_hint_points_at_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forgotten = self._arrange(monkeypatch, "session")
        with pytest.raises(AuthError) as exc_info:
            whoami_service.whoami(base_url=BASE_URL)
        assert forgotten == [True]
        assert "elva auth login" in (exc_info.value.hint or "")

    def test_stored_pat_is_forgotten_and_hint_is_not_about_login(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forgotten = self._arrange(monkeypatch, "pat")
        with pytest.raises(AuthError) as exc_info:
            whoami_service.whoami(base_url=BASE_URL)
        assert forgotten == [True]
        assert "auth login" not in (exc_info.value.hint or "")

    def test_env_token_is_left_alone_and_hint_names_the_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forgotten = self._arrange(monkeypatch, "env")
        with pytest.raises(AuthError) as exc_info:
            whoami_service.whoami(base_url=BASE_URL)
        assert forgotten == []
        assert "ELVA_TOKEN" in (exc_info.value.hint or "")


class TestRendering:
    def test_a_plain_session_renders_just_the_email(self) -> None:
        from elva_cli.ui.renderables import render

        text = render(WhoamiResult(email="a@b.com", company_name=None))
        assert text.plain == "Signed in as a@b.com."

    def test_a_pat_renders_the_scoped_company(self) -> None:
        from elva_cli.ui.renderables import render

        text = render(WhoamiResult(email="a@b.com", company_name="Acme Inc"))
        assert "a@b.com" in text.plain
        assert "personal access token scoped to Acme Inc" in text.plain


class TestFetchMe:
    def test_401_is_an_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(*_args: object, **_kwargs: object) -> None:
            raise HTTPError(BASE_URL, 401, "unauthorized", None, None)  # type: ignore[arg-type]

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(AuthError):
            whoami_service._fetch_me(BASE_URL, "tok")

    def test_other_http_error_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(*_args: object, **_kwargs: object) -> None:
            raise HTTPError(BASE_URL, 500, "boom", None, None)  # type: ignore[arg-type]

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(ApiError):
            whoami_service._fetch_me(BASE_URL, "tok")

    def test_unreachable_server_is_an_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(*_args: object, **_kwargs: object) -> None:
            raise URLError("no route to host")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(ApiError):
            whoami_service._fetch_me(BASE_URL, "tok")
