"""Exercise real process signals, HTTP timeouts and rejected config writes."""

from __future__ import annotations

import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal/signal regression")
def test_sigint_at_a_real_confirmation_exits_130(workdir: Path) -> None:
    import pty
    import select

    master, slave = pty.openpty()
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELVA_") and k != "CI"}
    env["TERM"] = "xterm-256color"
    process = subprocess.Popen(
        [sys.executable, "-m", "elva_cli", "mcp", "create", "--name", "QA cancelled"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=workdir,
        env=env,
        start_new_session=True,
    )
    os.close(slave)
    try:
        output = b""
        deadline = time.monotonic() + 10
        while b"(y/N)" not in output and b"(Y/n)" not in output:
            assert time.monotonic() < deadline, output.decode(errors="replace")
            if select.select([master], [], [], 0.1)[0]:
                output += os.read(master, 65536)
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=10) == 130, output.decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)


@pytest.mark.parametrize("operation", ["whoami", "import"])
def test_configured_timeout_stops_real_http_requests(
    run: Callable[..., subprocess.CompletedProcess[str]], workdir: Path, operation: str
) -> None:
    release = threading.Event()
    received = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def do_GET(self) -> None:
            received.set()
            release.wait(10)

        do_POST = do_GET  # noqa: N815

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        spec = workdir / "api.yaml"
        spec.write_text(
            "openapi: 3.0.3\ninfo: {title: QA, version: '1'}\npaths: {}\n", encoding="utf-8"
        )
        args = (
            ["whoami"]
            if operation == "whoami"
            else ["--workspace", "a" * 24, "import", "spec", str(spec)]
        )
        started = time.monotonic()
        result = run(
            *args,
            env={
                "ELVA_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "ELVA_TOKEN": "test-token",
                "ELVA_TIMEOUT": "0.1",
            },
        )
        assert received.is_set()
        assert result.returncode == 5, result.stderr
        assert "ELVA_API" in result.stderr
        assert time.monotonic() - started < 5
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_invalid_config_write_preserves_the_existing_file(
    run: Callable[..., subprocess.CompletedProcess[str]], workdir: Path, value: str
) -> None:
    target = workdir / "elva.json"
    original = '{"timeout": 7.5}\n'
    target.write_text(original, encoding="utf-8")
    result = run("config", "set", "timeout", "--", value)
    assert result.returncode == 2, result.stderr
    assert "finite" in result.stderr
    assert target.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
@pytest.mark.parametrize("source", ["environment", "profile"])
def test_nonfinite_timeout_never_reaches_json_output(
    run: Callable[..., subprocess.CompletedProcess[str]], workdir: Path, value: str, source: str
) -> None:
    args = ["--json", "config", "list"]
    env = {}
    if source == "environment":
        env["ELVA_TIMEOUT"] = value
    else:
        config = workdir / "xdgconfig" / "elva" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"profiles": {"qa": {"timeout": value}}}), encoding="utf-8")
        args = ["--profile", "qa", *args]
    result = run(*args, env=env)
    assert result.returncode == 2, result.stderr
    assert "ELVA_CONFIG" in result.stderr
    assert result.stdout == ""
