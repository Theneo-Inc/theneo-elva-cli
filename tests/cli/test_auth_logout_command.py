from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable


def test_logout_with_nothing_stored_says_so(
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run("auth", "logout")
    assert result.returncode == 0
    assert "weren't signed in" in result.stdout

    result = run("auth", "logout", env={"ELVA_TOKEN": "anything"})
    assert result.returncode == 0
    assert "ELVA_TOKEN" in result.stderr
