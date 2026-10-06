from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from elva_cli.core.source_snapshot import MAX_FILE_BYTES, build_snapshot
from elva_cli.errors import UsageError


def test_source_without_spec_includes_local_code_and_excludes_private_and_ignored_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("@app.get('/orders')\ndef orders(): return {'id':'1'}")
    (tmp_path / "private.py").write_text("private")
    (tmp_path / ".gitignore").write_text("private.py\n*.json\n!package.json\n")
    (tmp_path / "package.json").write_text('{"name":"orders"}')
    (tmp_path / "hidden.json").write_text("secret")
    (tmp_path / ".env").write_text("DO_NOT_UPLOAD=private")
    (tmp_path / "credentials.json").write_text("private")
    (tmp_path / "secret.key").write_text("private")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dependency.js").write_text("dependency")
    (tmp_path / "link.py").symlink_to(tmp_path / "private.py")
    snapshot = build_snapshot(tmp_path)
    assert {f["path"] for f in snapshot.payload["files"]} == {"app.py", "package.json"}
    assert "DO_NOT_UPLOAD" not in json.dumps(snapshot.payload)


def test_nested_ignore_rules_and_elvaignore(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / ".gitignore").write_text("*.py\n!app.py\n")
    (tmp_path / ".elvaignore").write_text("omit.js\n")
    for file in ("api/app.py", "api/omit.py", "omit.js"):
        (tmp_path / file).write_text("code")
    assert [f["path"] for f in build_snapshot(tmp_path).payload["files"]] == ["api/app.py"]


def test_checkout_root_and_git_excludes_cover_untracked_and_modified_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "api").mkdir()
    (tmp_path / "api/app.py").write_text("modified source")
    (tmp_path / "api/private.py").write_text("private source")
    (tmp_path / ".git/info/exclude").write_text("api/private.py\n")
    snapshot = build_snapshot(tmp_path / "api")
    assert snapshot.root == tmp_path
    assert [f["path"] for f in snapshot.payload["files"]] == ["api/app.py"]
    assert snapshot.payload["files"][0]["content"] == "modified source"


def test_redacts_embedded_credentials_without_removing_the_assignment(tmp_path: Path) -> None:
    secret = "ghp_" + "aB3C" * 10
    (tmp_path / "app.py").write_text(f'API_TOKEN = "{secret}"\nPASSWORD = "test-secret-value"\n')
    snapshot = build_snapshot(tmp_path)
    content = snapshot.payload["files"][0]["content"]
    assert secret not in content and "test-secret-value" not in content
    assert 'API_TOKEN = "[REDACTED]"' in content
    assert snapshot.redactions >= 2


def test_oversized_source_is_not_silently_omitted(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(UsageError, match="256 KiB"):
        build_snapshot(tmp_path)


def test_config_secrets_and_parent_elvaignore(tmp_path: Path) -> None:
    (tmp_path / ".elvaignore").write_text("api/private.py\n")
    (tmp_path / "api").mkdir()
    (tmp_path / "api/private.py").write_text("private")
    (tmp_path / "api/settings.json").write_text(
        '{"password":"sensitive-value", "api_key": "abc123"}'
    )
    (tmp_path / "api/settings.yaml").write_text("password: sensitive-value\n")
    snapshot = build_snapshot(tmp_path, tmp_path / "api")
    assert len(snapshot.payload["files"]) == 2
    assert "sensitive-value" not in json.dumps(snapshot.payload)
    assert "abc123" not in json.dumps(snapshot.payload)
    assert snapshot.redactions == 3


def test_metadata_does_not_run_fsmonitor(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    hook = tmp_path / "hook.sh"
    marker = tmp_path / "hook-ran"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o700)
    subprocess.run(["git", "-C", str(tmp_path), "config", "core.fsmonitor", str(hook)], check=True)
    (tmp_path / "app.py").write_text("code")
    # Commit enables the metadata status path; disable the hook during fixture setup.
    subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(tmp_path), "add", "app.py"], check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "user.name=QA",
            "-c",
            "user.email=qa@example.com",
            "-C",
            str(tmp_path),
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    build_snapshot(tmp_path)
    assert not marker.exists()


def test_git_negation_cannot_override_elva_privacy_ignore(tmp_path: Path) -> None:
    (tmp_path / ".elvaignore").write_text("**/private.py\n")
    (tmp_path / "api").mkdir()
    (tmp_path / "api/.gitignore").write_text("!private.py\n")
    (tmp_path / "api/private.py").write_text("private")
    (tmp_path / "api/app.py").write_text("code")
    assert [f["path"] for f in build_snapshot(tmp_path).payload["files"]] == ["api/app.py"]
