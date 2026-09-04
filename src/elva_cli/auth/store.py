"""Where a Credentials blob actually lives: OS keyring first, a 0600 file
for machines with no keyring backend (headless Linux, containers).

Deliberately does NOT depend on `keyrings.alt`: without it, `keyring` fails
over cleanly on a box with no real secret service instead of silently
writing through its own weakly-obfuscated plaintext backend — so it's
*this* module's documented file fallback that fires, not a hidden one.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from elva_cli.auth.models import Credentials
from elva_cli.settings import paths

_SERVICE = "elva-cli"
_USERNAME = "default"
_CREDENTIALS_FILE = "credentials.json"


class StoreUnavailableError(Exception):
    """This store can't be written to right now (e.g. no keyring backend).

    Internal to auth/ — callers fall through to the next store, never a
    user-facing error on its own.
    """


class TokenStore(Protocol):
    def load(self) -> Credentials | None: ...
    def save(self, creds: Credentials) -> None: ...
    def clear(self) -> None: ...


class KeyringStore:
    """Backed by the OS keyring (Keychain / libsecret / Credential Manager)."""

    def load(self) -> Credentials | None:
        import keyring

        try:
            raw = keyring.get_password(_SERVICE, _USERNAME)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return Credentials.from_json(json.loads(raw))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def save(self, creds: Credentials) -> None:
        import keyring

        try:
            keyring.set_password(_SERVICE, _USERNAME, json.dumps(creds.to_json()))
        except Exception as exc:
            raise StoreUnavailableError(str(exc)) from exc

    def clear(self) -> None:
        import keyring

        # Already absent, or no backend — either way, nothing to clear.
        with contextlib.suppress(Exception):
            keyring.delete_password(_SERVICE, _USERNAME)


class FileStore:
    """0600 JSON file under the CLI's config dir. The documented fallback
    for headless Linux / containers where no keyring daemon is running."""

    def _path(self) -> Path:
        return paths.config_dir() / _CREDENTIALS_FILE

    def load(self) -> Credentials | None:
        path = self._path()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            return Credentials.from_json(json.loads(raw))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def save(self, creds: Credentials) -> None:
        directory = paths.config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)

        path = directory / _CREDENTIALS_FILE
        payload = json.dumps(creds.to_json()).encode("utf-8")

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{_CREDENTIALS_FILE}.", suffix=".tmp", dir=directory
        )
        tmp_path = Path(tmp_name)
        try:
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
            tmp_path.replace(path)  # atomic on POSIX and Windows
        except BaseException:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    def clear(self) -> None:
        with contextlib.suppress(OSError):
            self._path().unlink(missing_ok=True)
        # Also sweep any temp files left by an interrupted save.
        for leftover in self._path().parent.glob(f"{_CREDENTIALS_FILE}.*.tmp"):
            with contextlib.suppress(OSError):
                leftover.unlink()
