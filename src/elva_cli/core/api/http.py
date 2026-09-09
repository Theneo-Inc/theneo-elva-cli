"""The HTTP calls the CLI makes, and the one place a status becomes an error.

Not the generated client this package's docstring describes -- that arrives
with its own ticket. This is the minimum that stops every new command
hand-rolling urllib and its own status mapping.

Callers get HttpError for a rejected request and map the codes they have
something specific to say about; `default_error` handles the rest.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from elva_cli.errors import ApiError, AuthError, ElvaError

if TYPE_CHECKING:
    import urllib.error
    from collections.abc import Mapping

DEFAULT_TIMEOUT = 30.0
UNEXPECTED_RESPONSE = "The server returned an unexpected response."
REDIRECTED = "The server redirected the request. Check the configured base URL."
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


class HttpError(Exception):
    """A non-2xx response, with whatever explanation the server sent."""

    def __init__(self, status: int, detail: str | None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail


def default_error(error: HttpError, *, action: str) -> ElvaError:
    """The mapping every caller shares. `action` completes "... failed"."""
    if error.status in (401, 403):
        return AuthError("Your credentials are no longer valid.")
    return ApiError(f"{action} failed (HTTP {error.status}).")


def get_json(url: str, *, token: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
    return _send(url, token=token, method="GET", timeout=timeout)


def send_json(
    url: str,
    *,
    token: str,
    method: str,
    payload: Mapping[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    return _send(
        url,
        token=token,
        method=method,
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
        timeout=timeout,
    )


def send_form(
    url: str,
    *,
    token: str,
    method: str,
    fields: Mapping[str, str],
    field: str | None = None,
    filename: str | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """A multipart/form-data request: text fields, plus at most one file."""
    body, boundary_type = _multipart(
        fields=fields,
        field=field,
        filename=filename,
        data=data,
        content_type=content_type,
    )
    return _send(
        url, token=token, method=method, body=body, content_type=boundary_type, timeout=timeout
    )


def _multipart(
    *,
    fields: Mapping[str, str],
    field: str | None,
    filename: str | None,
    data: bytes | None,
    content_type: str | None,
) -> tuple[bytes, str]:
    """Body and Content-Type header for a multipart form.

    Hand-rolled to keep the dependency list flat. If this ever needs more than
    one file part, or streaming, reach for httpx instead of growing it.
    """
    import secrets

    boundary = f"----elva{secrets.token_hex(16)}"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{_header_safe(name)}"'.encode(),
            b"",
            value.encode("utf-8"),
        ]

    if field is not None and data is not None:
        parts += [
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{_header_safe(field)}"; '
                f'filename="{_header_safe(filename or "spec")}"'
            ).encode(),
            f"Content-Type: {content_type or 'application/octet-stream'}".encode(),
            b"",
            data,
        ]

    parts += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"


def _header_safe(value: str) -> str:
    """A quote or newline would otherwise break out of the part header."""
    return value.translate({ord(c): "_" for c in '"\\\r\n'})


_OPENER: Any = None


def _opener() -> Any:
    """An opener that refuses redirects instead of following them.

    urllib's default handler would replay the request at the new location with
    our `Authorization: Bearer` still attached -- to another host, if that is
    where it points -- and on 301/302/303 it rewrites POST/PATCH to GET, which
    drops the upload body and surfaces only as an unexpected response. Neither
    is ours to do on the caller's behalf, so a redirect becomes an error.
    """
    global _OPENER
    if _OPENER is None:
        import urllib.request

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        _OPENER = urllib.request.build_opener(_NoRedirect)
    return _OPENER


def _send(
    url: str,
    *,
    token: str,
    method: str,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float,
) -> Any:
    import urllib.error
    import urllib.request

    headers = {"Authorization": f"Bearer {token}"}
    if content_type is not None:
        headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener().open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in _REDIRECT_CODES:
            raise ApiError(REDIRECTED) from exc
        raise HttpError(exc.code, _detail(exc)) from exc
    except OSError as exc:
        # URLError and TimeoutError are both OSError, but a connection reset
        # part-way through reading the response is neither -- it arrives raw
        # from the socket, and catching only those two lets it out as an
        # unhandled traceback under exit 1 instead of a reachability failure.
        raise ApiError("Could not reach the server.") from exc

    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(UNEXPECTED_RESPONSE) from exc


def _detail(exc: urllib.error.HTTPError) -> str | None:
    """The server's own explanation, when it sends one worth showing."""
    try:
        payload = json.loads(exc.read())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
