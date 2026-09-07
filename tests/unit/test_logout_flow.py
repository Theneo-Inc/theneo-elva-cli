from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.core.services import auth as auth_service
from elva_cli.core.services.auth_result import LogoutResult, LogoutStatus

if TYPE_CHECKING:
    import pytest

BASE_URL = "https://api.getelva.ai"


class TestLogout:
    def test_passes_the_credential_outcome_straight_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for status in LogoutStatus:
            monkeypatch.setattr(
                auth_service,
                "logout_credentials",
                lambda *, base_url, status=status: LogoutResult(status=status),
            )
            assert auth_service.logout(base_url=BASE_URL) == LogoutResult(status=status)

    def test_forwards_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        received: list[str] = []

        def fake_logout(*, base_url: str) -> LogoutResult:
            received.append(base_url)
            return LogoutResult(status=LogoutStatus.SIGNED_OUT)

        monkeypatch.setattr(auth_service, "logout_credentials", fake_logout)
        auth_service.logout(base_url=BASE_URL)
        assert received == [BASE_URL]
