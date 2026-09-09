"""How the CLI identifies itself to the Elva backend.

The `X-Elva-Client: cli` marker tells the refresh endpoint this is a
non-browser client that takes its refresh token in the response body (ELVA-200).
While the backend's AUTH_ALLOW_BODY_REFRESH_TOKEN flag is on it also accepts
unmarked body tokens; once that flag is flipped off (this CLI version being the
floor), the marker is required and unmarked/legacy tokens are rejected 401.
"""

from __future__ import annotations

from elva_cli import __version__

CLIENT_HEADER = "X-Elva-Client"
CLIENT_NAME = "cli"
USER_AGENT = f"elva-cli/{__version__}"


def client_headers() -> dict[str, str]:
    """Headers every Elva request should carry to identify this client."""
    return {CLIENT_HEADER: CLIENT_NAME, "User-Agent": USER_AGENT}
