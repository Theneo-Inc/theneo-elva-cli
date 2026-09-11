from __future__ import annotations

import json
import os
import stat
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from elva_cli.errors import ConfigError, UsageError
from elva_cli.settings import writer


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def test_resolve_target_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    target = writer.resolve_target(use_global=True, cwd=tmp_path)
    assert target.kind == "user"
    assert str(target.path).endswith("config.json")


def test_resolve_target_existing_project_file(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "elva.json").write_text("{}", encoding="utf-8")
    target = writer.resolve_target(use_global=False, cwd=root)
    assert target.kind == "project"
    assert target.path == root / "elva.json"


def test_resolve_target_bare_repo_uses_repo_root(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    sub = root / "src"
    sub.mkdir()
    target = writer.resolve_target(use_global=False, cwd=sub)
    assert target.kind == "project"
    assert target.path == root / "elva.json"


def test_resolve_target_outside_repo_raises_usage(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        writer.resolve_target(use_global=False, cwd=tmp_path)


def test_set_value_rejects_credential_key(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = writer.WriteTarget("project", root / "elva.json")
    with pytest.raises(ConfigError, match="credentials"):
        writer.set_value(key="token", value="abc", target=target)
    assert not (root / "elva.json").exists()


def test_set_value_rejects_unknown_key(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = writer.WriteTarget("project", root / "elva.json")
    with pytest.raises(ConfigError, match="unknown key"):
        writer.set_value(key="nope", value="x", target=target)


def test_set_value_rejects_control_chars(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = writer.WriteTarget("project", root / "elva.json")
    with pytest.raises(ConfigError, match="control"):
        writer.set_value(key="workspace", value="x\nBAD", target=target)


def test_set_value_validates_via_pydantic(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = writer.WriteTarget("project", root / "elva.json")
    with pytest.raises(ConfigError):
        writer.set_value(key="base_url", value="ftp://x", target=target)


def test_set_value_coerces_timeout_to_float(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    target = writer.WriteTarget("project", root / "elva.json")
    writer.set_value(key="timeout", value="12.5", target=target)
    data = json.loads((root / "elva.json").read_text())
    assert data == {"timeout": 12.5}


def test_set_value_preserves_other_keys(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    path = root / "elva.json"
    path.write_text(json.dumps({"collection": "orders", "other": "keep"}), encoding="utf-8")
    writer.set_value(key="workspace", value="payments", target=writer.WriteTarget("project", path))
    data = json.loads(path.read_text())
    assert data == {"collection": "orders", "other": "keep", "workspace": "payments"}


def test_unset_value_removes_and_preserves(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    path = root / "elva.json"
    path.write_text(json.dumps({"workspace": "x", "collection": "y"}), encoding="utf-8")
    writer.unset_value(key="workspace", target=writer.WriteTarget("project", path))
    assert json.loads(path.read_text()) == {"collection": "y"}


def test_unset_missing_key_is_noop(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    path = root / "elva.json"
    path.write_text(json.dumps({"collection": "y"}), encoding="utf-8")
    writer.unset_value(key="workspace", target=writer.WriteTarget("project", path))
    assert json.loads(path.read_text()) == {"collection": "y"}


def test_atomic_write_restores_nothing_but_leaves_original_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path)
    path = root / "elva.json"
    original = json.dumps({"workspace": "keep"})
    path.write_text(original, encoding="utf-8")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        writer.set_value(
            key="collection", value="orders", target=writer.WriteTarget("project", path)
        )
    assert path.read_text() == original
    debris = [p.name for p in root.iterdir() if p.name.startswith(".elva.json")]
    assert debris == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_project_write_does_not_chmod_repo_dir(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    root.chmod(0o700)
    try:
        writer.set_value(
            key="workspace",
            value="payments",
            target=writer.WriteTarget("project", root / "elva.json"),
        )
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
    finally:
        root.chmod(0o755)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_user_write_preserves_existing_dir_mode(tmp_path: Path) -> None:
    user_dir = tmp_path / "elva"
    user_dir.mkdir()
    user_dir.chmod(0o750)
    writer.set_value(
        key="workspace",
        value="payments",
        target=writer.WriteTarget("user", user_dir / "config.json"),
    )
    assert stat.S_IMODE(user_dir.stat().st_mode) == 0o750


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks only")
def test_symlink_preplant_does_not_hijack_write(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    canary = tmp_path / "canary"
    canary.write_text("original", encoding="utf-8")
    (root / ".elva.json.attack.tmp").symlink_to(canary)

    writer.set_value(
        key="workspace",
        value="payments",
        target=writer.WriteTarget("project", root / "elva.json"),
    )
    assert canary.read_text() == "original"
    assert json.loads((root / "elva.json").read_text()) == {"workspace": "payments"}
