"""Run with the clean wheel environment's Python; never imports source code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

COMMANDS = (
    "agent setup",
    "agent schema",
    "agent validate",
    "agent create",
    "auth login",
    "auth logout",
    "auth register",
    "auth signup",
    "auth verify",
    "auth resume",
    "whoami",
    "config path",
    "config list",
    "config get",
    "config set",
    "config unset",
    "import spec",
    "import postman",
    "workspace list",
    "workspace switch",
    "collection list",
    "collection show",
    "collection endpoints",
    "mcp list",
    "mcp show",
    "mcp create",
    "mcp plan",
    "apply",
    "schema",
    "plan show",
    "mcp publish",
    "mcp logs",
    "repo list",
    "repo connect",
    "repo sync",
    "repo status",
    "insights checks",
    "insights review",
    "insights show",
    "contract list",
    "contract show",
    "contract create",
    "contract update",
    "contract sync",
    "contract approve",
    "contract reject",
    "contract publish",
    "contract delete",
)


def main() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELVA_")}
    env.pop("PYTHONPATH", None)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    with tempfile.TemporaryDirectory() as workdir:
        discovery = subprocess.run(
            [sys.executable, "-m", "elva_cli", "--json", "schema"],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        root = next(c for c in json.loads(discovery.stdout)["commands"] if c["command"] == "elva")
        available = {o for p in root["parameters"] for o in p["options"]}
        assert {
            "--prompt",
            "--resume",
            "--path",
            "--auth-type",
            "--api-base-url",
            "--plan-only",
        } <= available
        for command in COMMANDS:
            result = subprocess.run(
                [sys.executable, "-m", "elva_cli", *command.split(), "--help"],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode:
                raise SystemExit(f"Wheel is missing {command}: {result.stderr}")
        for args in [["--unknown-option"], ["mcp", "publish"], ["config", "get"]]:
            result = subprocess.run(
                [sys.executable, "-m", "elva_cli", *args],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 2 or "ELVA_CRASH" in result.stderr:
                raise SystemExit(f"Argument parsing failed for {args}: {result.stderr}")
    print(
        f"Wheel smoke passed: {len(COMMANDS)} commands, "
        "root prompt discovery and usage-error handling."
    )


if __name__ == "__main__":
    main()
