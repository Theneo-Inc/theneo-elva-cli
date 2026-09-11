from __future__ import annotations

from typing import TYPE_CHECKING

from elva_cli.errors import ExitCode

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable


def test_unattended_register_exits_auth(
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run("auth", "register", env={"CI": "true"})
    assert result.returncode == ExitCode.AUTH
    assert "browser" in result.stderr
    assert "ELVA_TOKEN" not in result.stderr
