from __future__ import annotations

import stat
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import keyring.errors
import pytest

from elva_cli.auth.models import Credentials
from elva_cli.auth.store import FileStore, KeyringStore, StoreUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

SESSION = Credentials(
    kind="session",
    access_token="access-abc",
    access_expires_at=datetime(2026, 1, 1, tzinfo=UTC),
    refresh_token="refresh-abc",
    refresh_expires_at=datetime(2026, 1, 8, tzinfo=UTC),
)

PAT = Credentials.from_pat("elva_pat_xyz")


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: directory)
    return directory


class TestFileStore:
    def test_round_trips_a_session_credential(self, config_dir: Path) -> None:
        store = FileStore()
        store.save(SESSION)
        assert store.load() == SESSION

    def test_round_trips_a_pat_credential(self, config_dir: Path) -> None:
        store = FileStore()
        store.save(PAT)
        assert store.load() == PAT

    def test_missing_file_loads_as_none(self, config_dir: Path) -> None:
        assert FileStore().load() is None

    def test_malformed_file_loads_as_none(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "credentials.json").write_text("not json", encoding="utf-8")
        assert FileStore().load() is None

    def test_clear_removes_the_file(self, config_dir: Path) -> None:
        store = FileStore()
        store.save(SESSION)
        store.clear()
        assert store.load() is None
        store.clear()  # clearing an already-absent file must not raise

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits don't apply")
    def test_file_is_written_0600(self, config_dir: Path) -> None:
        FileStore().save(SESSION)
        mode = stat.S_IMODE((config_dir / "credentials.json").stat().st_mode)
        assert mode == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits don't apply")
    def test_config_dir_is_0700(self, config_dir: Path) -> None:
        FileStore().save(SESSION)
        mode = stat.S_IMODE(config_dir.stat().st_mode)
        assert mode == 0o700

    def test_no_leftover_temp_file(self, config_dir: Path) -> None:
        FileStore().save(SESSION)
        assert sorted(p.name for p in config_dir.iterdir()) == ["credentials.json"]

    def test_failed_write_leaves_no_temp_file(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> int:
            raise OSError("disk full")

        monkeypatch.setattr("os.write", boom)
        with pytest.raises(OSError, match="disk full"):
            FileStore().save(SESSION)
        assert list(config_dir.iterdir()) == []

    def test_clear_sweeps_leftover_temp_files(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "credentials.json.abc123.tmp").write_text("{}", encoding="utf-8")
        FileStore().clear()
        assert list(config_dir.iterdir()) == []

    def test_clear_swallows_unlink_permission_error(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        FileStore().save(SESSION)

        def deny(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("read-only file system")

        monkeypatch.setattr("pathlib.Path.unlink", deny)
        FileStore().clear()  # must not raise even when the file can't be removed

    def test_incomplete_session_credential_loads_as_none(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "credentials.json").write_text(
            '{"kind": "session", "access_token": "a", "refresh_token": "r"}',
            encoding="utf-8",
        )
        assert FileStore().load() is None

    def test_unknown_kind_loads_as_none(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "credentials.json").write_text(
            '{"kind": "wat", "access_token": "a"}', encoding="utf-8"
        )
        assert FileStore().load() is None

    @pytest.mark.parametrize("body", ["123", '"a bare string"', "[]", "null"])
    def test_valid_json_that_is_not_an_object_loads_as_none(
        self, config_dir: Path, body: str
    ) -> None:
        config_dir.mkdir(parents=True)
        (config_dir / "credentials.json").write_text(body, encoding="utf-8")
        assert FileStore().load() is None


class TestKeyringStore:
    def test_round_trips_via_keyring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend: dict[str, str] = {}
        monkeypatch.setattr(
            "keyring.set_password", lambda _service, _user, value: backend.__setitem__("v", value)
        )
        monkeypatch.setattr("keyring.get_password", lambda _service, _user: backend.get("v"))

        store = KeyringStore()
        store.save(SESSION)
        assert store.load() == SESSION

    def test_load_returns_none_when_keyring_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_unavailable(*_args: object) -> None:
            raise keyring.errors.NoKeyringError

        monkeypatch.setattr("keyring.get_password", raise_unavailable)
        assert KeyringStore().load() is None

    def test_save_raises_store_unavailable_when_keyring_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_unavailable(*_args: object) -> None:
            raise keyring.errors.NoKeyringError

        monkeypatch.setattr("keyring.set_password", raise_unavailable)
        with pytest.raises(StoreUnavailableError):
            KeyringStore().save(SESSION)

    def test_clear_swallows_keyring_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_delete_error(*_args: object) -> None:
            raise keyring.errors.PasswordDeleteError

        monkeypatch.setattr("keyring.delete_password", raise_delete_error)
        KeyringStore().clear()  # must not raise

    def test_load_returns_none_for_malformed_stored_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("keyring.get_password", lambda _service, _user: "not json")
        assert KeyringStore().load() is None

    @pytest.mark.parametrize("stored", ["123", '"a bare string"', "[]", "null"])
    def test_load_returns_none_for_valid_json_that_is_not_an_object(
        self, monkeypatch: pytest.MonkeyPatch, stored: str
    ) -> None:
        monkeypatch.setattr("keyring.get_password", lambda _service, _user: stored)
        assert KeyringStore().load() is None

    def test_load_falls_back_on_non_keyring_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A broken SecretService / D-Bus backend can raise something other
        # than keyring.errors.KeyringError — that must still degrade to None.
        def raise_dbus_error(*_args: object) -> None:
            raise RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")

        monkeypatch.setattr("keyring.get_password", raise_dbus_error)
        assert KeyringStore().load() is None

    def test_save_raises_store_unavailable_on_non_keyring_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_dbus_error(*_args: object) -> None:
            raise RuntimeError("no session bus")

        monkeypatch.setattr("keyring.set_password", raise_dbus_error)
        with pytest.raises(StoreUnavailableError):
            KeyringStore().save(SESSION)
