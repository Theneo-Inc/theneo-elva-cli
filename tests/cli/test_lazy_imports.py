"""Guards the startup cost of `elva --version`.

pydantic and httpx are only needed once a command touches settings or the API.
If they ever get imported at module scope, every invocation pays for them.
"""

from __future__ import annotations

import subprocess
import sys

PROBE = """
import sys
sys.argv = ["elva", "{args}"]
from elva_cli import main
main._run()
print("pydantic:", "pydantic" in sys.modules)
print("httpx:", "httpx" in sys.modules)
"""


def probe(args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(args=args)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_version_does_not_import_pydantic_or_httpx() -> None:
    out = probe("--version")
    assert "pydantic: False" in out
    assert "httpx: False" in out


def test_importing_main_alone_does_not_import_pydantic() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import elva_cli.main, sys; print('pydantic' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
