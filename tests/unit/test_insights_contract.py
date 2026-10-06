from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from elva_cli.core.services.contract import MAX_BYTES, read_body
from elva_cli.core.services.insights import list_checks, review_file
from elva_cli.errors import UsageError, ValidationError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "body", [b"", b"[]", b"null", b"{", b' {"score": NaN}', b' {"score": Infinity}', b"\xff"]
)
def test_invalid_contract_input(body: bytes) -> None:
    with pytest.raises(UsageError):
        read_body(None, body)


def test_oversized_contract_input() -> None:
    with pytest.raises(UsageError, match="2 MiB"):
        read_body(None, b" " * (MAX_BYTES + 1))


@pytest.mark.parametrize("envelope", ["contract", "apiContract"])
def test_saved_active_contract_can_be_edited_without_republishing(envelope: str) -> None:
    body = read_body(
        None,
        json.dumps(
            {envelope: {"name": "API", "status": "active", "description": "Updated"}}
        ).encode(),
    )
    assert body == {"name": "API", "description": "Updated"}


def test_json_file_input(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    path.write_text('{"name":"Partner"}')
    assert read_body(path, None) == {"name": "Partner"}


def test_missing_input_file_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        read_body(tmp_path / "missing.json", None)


@pytest.mark.parametrize("body", [b"", b" " * (MAX_BYTES + 1), b"\xff"])
def test_invalid_insight_input_does_not_reach_network(body: bytes) -> None:
    with pytest.raises(ValidationError):
        review_file(base_url="http://127.0.0.1:1", path=None, stdin=body)


def test_bad_category_is_usage_error() -> None:
    with pytest.raises(UsageError):
        list_checks(base_url="http://127.0.0.1:1", category="nonexistent")
