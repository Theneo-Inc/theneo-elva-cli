"""The Credentials shape: what gets stored, and how it maps to the wire."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

TokenKind = Literal["session", "pat"]


def _parse_expiry(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, forcing it timezone-aware.

    The backend sends UTC with a `Z`, but a hand-edited credentials.json can
    drop the offset. A naive datetime would later crash get_access_token's
    `expires - datetime.now(UTC)` arithmetic, so assume UTC when none is
    given."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Credentials:
    """One stored credential: either an OAuth session (JWT pair, refreshable)
    or a Personal Access Token (opaque, long-lived, no refresh side)."""

    kind: TokenKind
    access_token: str
    access_expires_at: datetime | None
    refresh_token: str | None
    refresh_expires_at: datetime | None

    @classmethod
    def from_auth_tokens(cls, tokens: dict[str, Any]) -> Credentials:
        """Build a session credential from the backend's AuthTokens shape:
        {"access": {"token", "expires"}, "refresh": {"token", "expires"}}.

        POST /api/auth/refresh-tokens returns this shape at the top level.
        The CLI login exchange (POST /api/auth/cli/token) nests it under a
        "tokens" key alongside "user" — callers there go through
        `session.save_login`, which unwraps it first."""
        access = tokens["access"]
        refresh = tokens["refresh"]
        return cls(
            kind="session",
            access_token=access["token"],
            access_expires_at=_parse_expiry(access["expires"]),
            refresh_token=refresh["token"],
            refresh_expires_at=_parse_expiry(refresh["expires"]),
        )

    @classmethod
    def from_pat(cls, token: str) -> Credentials:
        return cls(
            kind="pat",
            access_token=token,
            access_expires_at=None,
            refresh_token=None,
            refresh_expires_at=None,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "access_token": self.access_token,
            "access_expires_at": (
                self.access_expires_at.isoformat() if self.access_expires_at else None
            ),
            "refresh_token": self.refresh_token,
            "refresh_expires_at": (
                self.refresh_expires_at.isoformat() if self.refresh_expires_at else None
            ),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Credentials:
        kind = data["kind"]
        if kind not in ("session", "pat"):
            raise ValueError(f"unknown credential kind: {kind!r}")
        creds = cls(
            kind=kind,
            access_token=data["access_token"],
            access_expires_at=(
                _parse_expiry(data["access_expires_at"]) if data.get("access_expires_at") else None
            ),
            refresh_token=data.get("refresh_token"),
            refresh_expires_at=(
                _parse_expiry(data["refresh_expires_at"])
                if data.get("refresh_expires_at")
                else None
            ),
        )
        if creds.kind == "session" and (
            creds.access_expires_at is None
            or creds.refresh_token is None
            or creds.refresh_expires_at is None
        ):
            raise ValueError("incomplete session credential")
        return creds
