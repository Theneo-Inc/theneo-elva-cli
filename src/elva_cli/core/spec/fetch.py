"""Fetch a spec from a URL the way the web app does: through Elva's own proxy
(`POST /api/fetch-file`), never a direct request from here.

That endpoint DNS-pins and block-lists private ranges, follows redirects with
each hop re-validated, and caps the body at 10 MB. It is the same path the
backend takes when it fetches a `specUrl` itself, so a URL a server-side fetch
could reach is one this reaches too -- and the CLI gets the bytes back, so it
can convert and name the spec rather than hand over a link and hope.
"""

from __future__ import annotations

from elva_cli.core.api.http import HttpError, send_json

_PATH = "/api/fetch-file"


class SpecFetchError(Exception):
    """Elva's proxy could not return the spec at the URL."""


def fetch_spec(*, base_url: str, url: str, timeout: float) -> bytes:
    """The bytes at `url`, fetched by Elva on the CLI's behalf."""
    try:
        body = send_json(
            f"{base_url}{_PATH}",
            token=None,
            method="POST",
            payload={"url": url},
            timeout=timeout,
        )
    except HttpError as exc:
        raise _mapped(exc, url) from exc

    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str):
        raise SpecFetchError("Elva returned an unexpected response fetching the spec URL.")
    return content.encode("utf-8")


def _mapped(exc: HttpError, url: str) -> SpecFetchError:
    if exc.status == 413:
        return SpecFetchError(f"the spec at {url} is larger than the 10 MB limit")
    detail = f": {exc.detail}" if exc.detail else ""
    if exc.status in (502, 504):
        return SpecFetchError(f"{url} could not be reached{detail}")
    return SpecFetchError(f"could not fetch {url}{detail}")
