from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


def run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    isolated = cwd / "xdgconfig"
    full = {
        **os.environ,
        "XDG_CONFIG_HOME": str(isolated),
        "APPDATA": str(isolated),
        "LOCALAPPDATA": str(isolated),
    }
    full.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "elva_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=full,
    )


def repo(tmp_path: Path, data: dict[str, object] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    if data is not None:
        (root / "elva.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def test_get_prints_only_the_bare_value(tmp_path: Path) -> None:
    root = repo(tmp_path, {"workspace": "payments"})
    result = run("config", "get", "workspace", cwd=root)
    assert result.returncode == 0
    assert result.stdout == "payments\n"


def test_get_supports_shell_capture(tmp_path: Path) -> None:
    root = repo(tmp_path, {"workspace": "payments"})
    result = run("config", "get", "workspace", cwd=root)
    assert result.stdout.rstrip("\n") == "payments"


def test_get_on_unset_key_exits_two(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "get", "workspace", cwd=root)
    assert result.returncode == 2
    assert "ELVA_CONFIG" in result.stderr


def test_get_on_unknown_key_exits_two(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "get", "nope", cwd=root)
    assert result.returncode == 2
    assert "valid keys" in result.stderr


def test_set_writes_project_file_and_reports_path(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "set", "workspace", "payments", cwd=root)
    assert result.returncode == 0, result.stderr
    assert str(root / "elva.json") in result.stdout
    data = json.loads((root / "elva.json").read_text())
    assert data == {"workspace": "payments"}


def test_set_creates_file_when_missing(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert not (root / "elva.json").exists()
    run("config", "set", "collection", "orders", cwd=root)
    assert (root / "elva.json").is_file()


def test_set_preserves_unrelated_keys_and_profiles(tmp_path: Path) -> None:
    root = repo(tmp_path)
    seed = run("config", "set", "--global", "base_url", "https://old.example.com", cwd=root)
    assert seed.returncode == 0, seed.stderr

    paths_payload = json.loads(run("--json", "config", "path", cwd=root).stdout)
    user_file = Path(next(f["path"] for f in paths_payload["files"] if f["kind"] == "user"))

    existing = json.loads(user_file.read_text())
    existing["profiles"] = {"prod": {"workspace": "billing"}}
    existing["unknown_extra"] = "keep-me"
    user_file.write_text(json.dumps(existing), encoding="utf-8")

    result = run("config", "set", "--global", "workspace", "payments", cwd=root)
    assert result.returncode == 0, result.stderr

    data = json.loads(user_file.read_text())
    assert data["workspace"] == "payments"
    assert data["base_url"] == "https://old.example.com"
    assert data["profiles"] == {"prod": {"workspace": "billing"}}
    assert data["unknown_extra"] == "keep-me"


def test_set_rejects_invalid_value_without_touching_file(tmp_path: Path) -> None:
    root = repo(tmp_path, {"workspace": "payments"})
    before = (root / "elva.json").read_bytes()
    result = run("config", "set", "base_url", "ftp://x", cwd=root)
    assert result.returncode == 2
    assert (root / "elva.json").read_bytes() == before


def test_set_rejects_negative_timeout(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "set", "timeout", "-1", cwd=root)
    assert result.returncode == 2


def test_set_rejects_unknown_key_with_valid_list(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "set", "nope", "x", cwd=root)
    assert result.returncode == 2
    assert "valid keys" in result.stderr
    assert not (root / "elva.json").exists()


def test_set_refuses_credential_keys(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "set", "token", "abc", cwd=root)
    assert result.returncode == 2
    assert "credentials" in result.stderr.lower()
    assert not (root / "elva.json").exists()


def test_set_rejects_control_chars_in_value(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("config", "set", "workspace", "x\nBAD", cwd=root)
    assert result.returncode == 2
    assert not (root / "elva.json").exists()


def test_set_outside_repo_without_global_exits_two(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    (outside / "xdgconfig").mkdir()
    result = run("config", "set", "workspace", "x", cwd=outside)
    assert result.returncode == 2
    assert "--global" in result.stderr


def test_unset_removes_key_and_preserves_siblings(tmp_path: Path) -> None:
    root = repo(tmp_path, {"workspace": "payments", "collection": "orders"})
    result = run("config", "unset", "workspace", cwd=root)
    assert result.returncode == 0, result.stderr
    data = json.loads((root / "elva.json").read_text())
    assert data == {"collection": "orders"}


def test_unset_is_idempotent_on_missing_key(tmp_path: Path) -> None:
    root = repo(tmp_path, {"collection": "orders"})
    result = run("config", "unset", "workspace", cwd=root)
    assert result.returncode == 0
    data = json.loads((root / "elva.json").read_text())
    assert data == {"collection": "orders"}


def test_atomic_write_leaves_no_temp_debris(tmp_path: Path) -> None:
    root = repo(tmp_path)
    run("config", "set", "workspace", "payments", cwd=root)
    debris = [p.name for p in root.iterdir() if p.name.startswith(".elva.json")]
    assert debris == []


def test_json_output_shape_for_get(tmp_path: Path) -> None:
    root = repo(tmp_path, {"workspace": "payments"})
    result = run("--json", "config", "get", "workspace", cwd=root)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {"key": "workspace", "value": "payments"}


def test_json_output_shape_for_set(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = run("--json", "config", "set", "workspace", "payments", cwd=root)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["action"] == "set"
    assert payload["target"] == "project"
    assert payload["key"] == "workspace"
    assert payload["value"] == "payments"
    assert payload["path"].endswith("elva.json")


def test_round_trip_via_config_get(tmp_path: Path) -> None:
    root = repo(tmp_path)
    run("config", "set", "workspace", "payments", cwd=root)
    got = run("config", "get", "workspace", cwd=root)
    assert got.stdout == "payments\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_user_config_written_with_owner_only_permissions(tmp_path: Path) -> None:
    root = repo(tmp_path)
    run("config", "set", "--global", "workspace", "payments", cwd=root)
    user_file = root / "xdgconfig" / "elva" / "config.json"
    mode = stat.S_IMODE(user_file.stat().st_mode)
    assert mode == 0o600
    dir_mode = stat.S_IMODE(user_file.parent.stat().st_mode)
    assert dir_mode == 0o700
