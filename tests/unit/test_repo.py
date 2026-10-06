from __future__ import annotations

import pytest

from elva_cli.core.services.repo import github_name
from elva_cli.errors import UsageError


@pytest.mark.parametrize(
    "value",
    [
        "acme/api",
        "https://github.com/acme/api.git",
        "https://github.com/acme/api/",
        "ssh://git@github.com/acme/api.git",
        "git@github.com:acme/api.git",
    ],
)
def test_github_reference(value: str) -> None:
    assert github_name(value) == ("acme", "api")


@pytest.mark.parametrize(
    "value",
    [
        "api",
        "a/b/tree/main",
        "../api",
        "acme/..",
        "https://gitlab.com/a/b",
        "https://token@github.com/a/b",
        "https://github.com.evil/a/b",
        "a/b?token=secret",
        "a/b#main",
        "a/b\n/../c",
        "https://github.com/a/b.git?foo=bar",
        "a/" + "b" * 101,
    ],
)
def test_invalid_reference(value: str) -> None:
    with pytest.raises(UsageError):
        github_name(value)
