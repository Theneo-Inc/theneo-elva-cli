from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable


def test_not_logged_in_exits_auth(
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run("whoami")
    assert result.returncode == ExitCode.AUTH
    assert "not logged in" in result.stderr
