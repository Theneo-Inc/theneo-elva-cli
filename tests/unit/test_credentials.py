from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime

import pytest

from elva_cli.auth.models import Credentials


def _tokens(
    access_expires: str, refresh_expires: str = "2026-01-08T00:00:00Z"
) -> dict[str, object]:
    return {
        "access": {"token": "a", "expires": access_expires},
        "refresh": {"token": "r", "expires": refresh_expires},
    }


class TestExpiryParsing:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T04:00:00+04:00",
            "2026-01-01T00:00:00",  # hand-edited file, offset dropped
        ],
    )
    def test_from_auth_tokens_always_yields_aware_datetimes(self, value: str) -> None:
        creds = Credentials.from_auth_tokens(_tokens(value))
        assert creds.access_expires_at is not None
        assert creds.access_expires_at.tzinfo is not None
        # arithmetic against an aware "now" must not raise
        _ = creds.access_expires_at - datetime.now(UTC)

    def test_naive_timestamp_is_assumed_utc(self) -> None:
        creds = Credentials.from_auth_tokens(_tokens("2026-01-01T00:00:00"))
        assert creds.access_expires_at == datetime(2026, 1, 1, tzinfo=UTC)

    def test_from_json_coerces_a_naive_stored_timestamp(self) -> None:
        creds = Credentials.from_json(
            {
                "kind": "session",
                "access_token": "a",
                "access_expires_at": "2026-01-01T00:00:00",
                "refresh_token": "r",
                "refresh_expires_at": "2026-01-08T00:00:00",
            }
        )
        assert creds.access_expires_at is not None
        assert creds.refresh_expires_at is not None
        assert creds.access_expires_at.tzinfo is not None
        assert creds.refresh_expires_at.tzinfo is not None

    def test_round_trip_through_json_keeps_the_instant(self) -> None:
        original = Credentials.from_auth_tokens(_tokens("2026-01-01T00:00:00Z"))
        assert Credentials.from_json(original.to_json()) == original


class TestImportBudget:
    def test_importing_the_auth_package_does_not_pull_in_urllib(self) -> None:
        # session.py drags in urllib -> ssl/http.client/email; `import
        # elva_cli.auth` (and so `elva --version`) must not pay for it.
        code = (
            "import sys, elva_cli.auth\n"
            "assert 'elva_cli.auth.session' not in sys.modules, 'session imported eagerly'\n"
            "assert 'urllib.request' not in sys.modules, 'urllib.request imported eagerly'\n"
            "assert elva_cli.auth.Credentials is not None\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_public_helpers_are_still_reachable_from_the_package(self) -> None:
        from elva_cli.auth import get_access_token, logout, save_login, save_pat

        assert all(callable(fn) for fn in (get_access_token, logout, save_login, save_pat))

    def test_unknown_attribute_still_raises(self) -> None:
        import elva_cli.auth

        with pytest.raises(AttributeError):
            _ = elva_cli.auth.nonexistent
