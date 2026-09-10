from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError as PydanticValidationError

from elva_cli.errors import ConfigError, UsageError
from elva_cli.settings import paths
from elva_cli.settings.models import Settings

Target = Literal["project", "user"]

KNOWN_KEYS: frozenset[str] = frozenset(Settings.model_fields)

CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "password",
        "secret",
        "auth_token",
        "access_token",
        "refresh_token",
    }
)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_USER_FILE_MODE = 0o600
_USER_DIR_MODE = 0o700
_PROJECT_FILE_MODE = 0o644


@dataclass(frozen=True)
class WriteTarget:
    kind: Target
    path: Path


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def resolve_target(*, use_global: bool, cwd: Path) -> WriteTarget:
    if use_global:
        return WriteTarget("user", paths.user_config_file())

    existing = paths.find_project_file(cwd)
    if existing is not None:
        return WriteTarget("project", existing)

    for directory in [cwd, *cwd.parents]:
        if (directory / ".git").exists():
            return WriteTarget("project", directory / paths.PROJECT_FILE)

    raise UsageError(
        "not inside a repository; pass --global to write the user config",
        hint="Run this from inside a git repo, or use 'elva config set --global <key> <value>'.",
    )


def _reject_credential_key(key: str) -> None:
    if key.lower() in CREDENTIAL_KEYS:
        raise ConfigError(
            "credentials must not be stored in config",
            hint="Use 'elva auth login' instead; tokens are kept in the OS keyring.",
        )


def _reject_unknown_key(key: str) -> None:
    if key not in KNOWN_KEYS:
        valid = ", ".join(sorted(KNOWN_KEYS))
        raise ConfigError(f"unknown key {key!r}", hint=f"valid keys: {valid}")


def _reject_control_chars(value: str) -> None:
    if _CONTROL_CHARS.search(value):
        raise ConfigError(
            "value contains control characters",
            hint="Config values must be printable single-line text.",
        )


def _coerce(field: str, raw: str) -> Any:
    if field == "timeout":
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"{field} must be a number, got {raw!r}") from None
    return raw


def _validate_via_model(key: str, value: Any) -> Any:
    try:
        settings = Settings(**{key: value})
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        raise ConfigError(f"invalid value for {key}: {first['msg']}") from exc
    return getattr(settings, key)


def _atomic_write(path: Path, text: str, *, file_mode: int, dir_mode: int) -> None:
    parent = path.parent
    parent.mkdir(mode=dir_mode, parents=True, exist_ok=True)
    try:
        os.chmod(parent, dir_mode)
    except (OSError, NotImplementedError):
        pass

    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp_path, file_mode)
        except (OSError, NotImplementedError):
            pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_dict(kind: Target, path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if kind == "user":
        _atomic_write(path, text, file_mode=_USER_FILE_MODE, dir_mode=_USER_DIR_MODE)
    else:
        _atomic_write(path, text, file_mode=_PROJECT_FILE_MODE, dir_mode=0o755)


def set_value(*, key: str, value: str, target: WriteTarget) -> Any:
    _reject_credential_key(key)
    _reject_unknown_key(key)
    _reject_control_chars(value)
    coerced = _coerce(key, value)
    normalized = _validate_via_model(key, coerced)

    data = read_json_file(target.path)
    data[key] = normalized
    _write_dict(target.kind, target.path, data)
    return normalized


def unset_value(*, key: str, target: WriteTarget) -> None:
    _reject_credential_key(key)
    _reject_unknown_key(key)

    data = read_json_file(target.path)
    data.pop(key, None)
    _write_dict(target.kind, target.path, data)
