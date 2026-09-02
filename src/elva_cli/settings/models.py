from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_BASE_URL = "https://api.getelva.ai"


class Settings(BaseModel):
    """Every setting the CLI has.

    Adding a field here is the only way to add a setting: the loader derives its
    precedence handling and `elva config list` derives its output. Unknown keys in
    a config file are an error rather than a silent typo.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = DEFAULT_BASE_URL
    profile: str = "default"
    workspace: str | None = None
    collection: str | None = None
    timeout: float = 30.0

    @field_validator("base_url")
    @classmethod
    def _must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            msg = "must start with http:// or https://"
            raise ValueError(msg)
        return value.rstrip("/")

    @field_validator("timeout")
    @classmethod
    def _must_be_positive(cls, value: float) -> float:
        if value <= 0:
            msg = "must be greater than 0"
            raise ValueError(msg)
        return value
