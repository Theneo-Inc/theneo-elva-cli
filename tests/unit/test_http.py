"""The multipart body is hand-rolled, so it gets tested rather than trusted."""

from __future__ import annotations

import pytest

from elva_cli.core.api.http import HttpError, _multipart, default_error
from elva_cli.errors import ApiError, AuthError

SPEC = b"openapi: 3.0.3\ninfo:\n  title: T\n"


def build(**overrides: object) -> tuple[bytes, str]:
    kwargs: dict[str, object] = {
        "fields": {},
        "field": "spec",
        "filename": "payments.yaml",
        "data": SPEC,
        "content_type": "application/yaml",
    }
    kwargs.update(overrides)
    return _multipart(**kwargs)  # type: ignore[arg-type]


class TestMultipart:
    def test_it_carries_the_file_and_the_field_name(self) -> None:
        body, content_type = build()
        assert content_type.startswith("multipart/form-data; boundary=")
        boundary = content_type.split("boundary=", 1)[1]
        assert body.startswith(f"--{boundary}".encode())
        assert body.endswith(f"--{boundary}--\r\n".encode())
        assert b'name="spec"; filename="payments.yaml"' in body
        assert b"Content-Type: application/yaml" in body
        assert SPEC in body

    def test_text_fields_come_before_the_file(self) -> None:
        body, _ = build(fields={"name": "Payments"})
        assert body.index(b'name="name"') < body.index(b'name="spec"')
        assert b"Payments" in body

    def test_fields_alone_produce_no_file_part(self) -> None:
        body, _ = build(fields={"name": "Payments"}, field=None, data=None, filename=None)
        assert b"filename=" not in body
        assert b"Payments" in body

    def test_binary_content_survives_intact(self) -> None:
        blob = bytes(range(256))
        body, _ = build(data=blob, content_type="application/json")
        assert blob in body

    @pytest.mark.parametrize(
        "hostile",
        [
            pytest.param('ev"il.yaml', id="quote"),
            pytest.param("ev\r\nX-Injected: 1.yaml", id="crlf"),
            pytest.param("ev\\il.yaml", id="backslash"),
        ],
    )
    def test_a_hostile_filename_cannot_break_out_of_the_header(self, hostile: str) -> None:
        body, _ = build(filename=hostile)
        assert b"X-Injected: 1\r\n\r\n" not in body
        assert b'"ev' in body

    def test_a_hostile_field_name_is_escaped_too(self) -> None:
        body, _ = build(fields={'ev"il': "x"})
        assert b'name="ev_il"' in body

    def test_each_call_uses_a_fresh_boundary(self) -> None:
        _, first = build()
        _, second = build()
        assert first != second


class TestDefaultError:
    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_credentials_are_auth(self, status: int) -> None:
        assert isinstance(default_error(HttpError(status, None), action="Doing it"), AuthError)

    @pytest.mark.parametrize("status", [500, 502, 418])
    def test_anything_else_is_api_and_names_the_action(self, status: int) -> None:
        error = default_error(HttpError(status, None), action="Listing collections")
        assert isinstance(error, ApiError)
        assert "Listing collections" in str(error)
        assert str(status) in str(error)
