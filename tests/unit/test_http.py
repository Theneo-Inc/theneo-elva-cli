"""The multipart body is hand-rolled, so it gets tested rather than trusted."""

from __future__ import annotations

import http.server
import threading

import pytest

from elva_cli.core.api.http import HttpError, _multipart, default_error, send_json
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


class TestConnectionReset:
    """A reset part-way through the response is a reachability failure, not a
    crash: pipelines read the exit code to tell that from a bad spec."""

    def test_a_reset_mid_response_is_reported_rather_than_raised_raw(self) -> None:
        import socket
        import struct

        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def serve() -> None:
            conn, _ = server.accept()
            conn.recv(65536)
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\n")
            # SO_LINGER with a zero timeout closes with an RST, so the client
            # is reset while it waits for the body those headers promised.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with pytest.raises(ApiError, match="reach"):
                send_json(f"http://127.0.0.1:{port}/x", token="t", method="POST", payload={})
        finally:
            thread.join(timeout=5)
            server.close()


class TestRedirects:
    """A redirect is refused, never replayed with the bearer token attached."""

    @staticmethod
    def _serve(status: int, location: str) -> tuple[str, threading.Thread, list[str]]:
        """A server whose first route redirects and whose second records the
        Authorization header anything following the redirect would send."""
        leaked: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def _route(self) -> None:
                # Closing a socket with unread data in its receive queue sends
                # an RST rather than a FIN, and the RST discards whatever the
                # client had buffered -- so the response is lost and the client
                # sees WinError 10053 instead. Draining is what a real server
                # does; skipping it makes every one of these tests a race that
                # Windows usually loses.
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)

                if self.path == "/start":
                    self.send_response(status)
                    self.send_header("Location", location)
                    self.end_headers()
                    return
                leaked.append(self.headers.get("Authorization", ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def do_GET(self) -> None:
                self._route()

            def do_POST(self) -> None:
                self._route()

            def do_PATCH(self) -> None:
                self._route()

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return f"http://127.0.0.1:{server.server_port}", thread, leaked

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_redirect_is_an_error_and_the_token_never_follows(self, status: int) -> None:
        base, _thread, leaked = self._serve(status, "/target")
        with pytest.raises(ApiError, match="redirected"):
            send_json(f"{base}/start", token="secret", method="PATCH", payload={"a": 1})
        assert leaked == [], "the redirect target must never see the bearer token"

    def test_an_off_host_redirect_is_refused_too(self) -> None:
        sink, _sink_thread, leaked = self._serve(200, "/unused")
        base, _thread, _ = self._serve(302, f"{sink}/target")
        with pytest.raises(ApiError, match="redirected"):
            send_json(f"{base}/start", token="secret", method="POST", payload={"a": 1})
        assert leaked == [], "a cross-host redirect must not receive the token either"

    def test_an_ordinary_response_still_works(self) -> None:
        base, _thread, _ = self._serve(302, "/unused")
        assert send_json(f"{base}/plain", token="t", method="POST", payload={}) == {"ok": True}


class TestErrorDetailShapes:
    """A validation layer rarely answers with a flat string, and losing its
    explanation leaves the CLI printing a generic refusal for a request the
    server explained perfectly well."""

    @staticmethod
    def _detail_of(payload: object) -> str | None:
        import json as _json

        from elva_cli.core.api import http

        class FakeError:
            def read(self) -> bytes:
                return _json.dumps(payload).encode()

        return http._detail(FakeError())  # type: ignore[arg-type]

    def test_a_flat_message_still_works(self) -> None:
        assert self._detail_of({"message": '"collectionIds" is required'}) == (
            '"collectionIds" is required'
        )

    def test_a_class_validator_array_is_joined(self) -> None:
        """NestJS sends `message` as an array of every failing constraint."""
        got = self._detail_of(
            {"statusCode": 400, "message": ["collectionIds should not be empty"], "error": "Bad"}
        )
        assert got == "collectionIds should not be empty"

    def test_several_failures_are_all_kept(self) -> None:
        got = self._detail_of({"message": ["first is wrong", "second is wrong"]})
        assert got == "first is wrong; second is wrong"

    def test_a_nested_error_object_is_unwrapped(self) -> None:
        assert self._detail_of({"error": {"message": "Postman said no"}}) == "Postman said no"

    def test_an_errors_array_of_objects_is_read(self) -> None:
        got = self._detail_of({"errors": [{"message": "bad id"}, {"message": "bad key"}]})
        assert got == "bad id; bad key"

    def test_a_body_with_nothing_sayable_is_still_none(self) -> None:
        """Better a generic refusal than a guess at which field meant what."""
        assert self._detail_of({"statusCode": 400, "success": False}) is None

    def test_a_non_object_body_is_none(self) -> None:
        assert self._detail_of([1, 2, 3]) is None

    def test_deep_nesting_gives_up_rather_than_recursing_forever(self) -> None:
        deep: object = {"message": "found me"}
        for _ in range(6):
            deep = {"error": deep}
        assert self._detail_of(deep) is None
