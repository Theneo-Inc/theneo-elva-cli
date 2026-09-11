"""Fetch a spec from a URL the way the web app does: through Elva's own proxy
(`POST /api/fetch-file`), never a direct request from here.

That endpoint DNS-pins and block-lists private ranges, follows redirects with
each hop re-validated, and caps the body at 10 MB. It is the same path the
backend takes when it fetches a `specUrl` itself, so a URL a server-side fetch
could reach is one this reaches too -- and the CLI gets the bytes back, so it
can convert and name the spec rather than hand over a link and hope.
"""

from __future__ import annotations

from elva_cli.core.api.http import TIMED_OUT, HttpError, default_error, send_json
from elva_cli.errors import ApiError

_PATH = "/api/fetch-file"


class SpecFetchError(Exception):
    """The URL is the problem, and the caller turns this into a usage error.

    Deliberately narrow. Elva refusing or failing the request is not the user's
    invocation being wrong, and `exit-codes.md` promises those a code of their
    own -- 3 to re-authenticate, 5 to retry with backoff. Raising this for them
    would flatten both into "fix your command line", which is neither true nor
    actionable, and would tell a pipeline to give up on a transient outage.
    """


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
    except ApiError as exc:
        # A timeout, and nothing else. Elva accepted the request and then ran
        # out of clock, and the only slow part of this route is its own fetch of
        # `url` -- so this one is about the spec's host.
        #
        # Everything else `_send` raises stays an ApiError deliberately. An
        # unreachable Elva, a DNS failure, a typo in --base-url and a redirect
        # are all about the CLI's own connection, and exit 5 is what tells a
        # pipeline to back off and retry; reframing them as a bad --url would
        # name the wrong host and drop the retry signal.
        if str(exc) != TIMED_OUT:
            raise
        raise SpecFetchError(
            f"Elva timed out fetching {url}. The spec's host may be slow or unreachable."
        ) from exc

    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str):
        raise SpecFetchError("Elva returned an unexpected response fetching the spec URL.")
    return content.encode("utf-8")


# What the proxy answers when the fault is at `url`: the CLI asked for
# something the user has to change. 502/504 are the upstream fetch failing,
# 400/422 the URL being rejected (a private address, a bad scheme), 404 the
# remote returning one, 413 the spec being too big. Everything else -- a 401,
# a 500, a route that is not there -- is Elva, and keeps Elva's exit code.
_URL_AT_FAULT = frozenset({400, 404, 413, 422, 502, 504})


def _mapped(exc: HttpError, url: str) -> Exception:
    if exc.status == 413:
        return SpecFetchError(f"the spec at {url} is larger than the 10 MB limit")
    detail = f": {exc.detail}" if exc.detail else ""
    if exc.status in (502, 504):
        return SpecFetchError(f"{url} could not be reached{detail}")
    if exc.status in _URL_AT_FAULT:
        return SpecFetchError(f"could not fetch {url}{detail}")
    return default_error(exc, action=f"Fetching {url}")
