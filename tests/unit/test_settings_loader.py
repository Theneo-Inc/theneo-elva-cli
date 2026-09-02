from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from elva_cli.errors import ConfigError
from elva_cli.settings.loader import resolve

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the user config at a temp dir and give us an isolated project root."""
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr("elva_cli.settings.paths.config_dir", lambda: config)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


def write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_defaults_when_nothing_is_configured(home: Path) -> None:
    result = resolve(env={}, cwd=home)
    assert result.settings.base_url == "https://api.getelva.ai"
    assert result.settings.workspace is None
    assert result.origins["base_url"] == "default"


def test_flag_beats_env(home: Path) -> None:
    result = resolve(
        overrides={"workspace": "from-flag"}, env={"ELVA_WORKSPACE": "from-env"}, cwd=home
    )
    assert result.settings.workspace == "from-flag"
    assert result.origins["workspace"] == "flag"


def test_env_beats_project_file(home: Path) -> None:
    write(home / "elva.json", {"workspace": "from-project"})
    result = resolve(env={"ELVA_WORKSPACE": "from-env"}, cwd=home)
    assert result.settings.workspace == "from-env"
    assert result.origins["workspace"] == "env"


def test_project_file_beats_user_config(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "config" / "config.json", {"workspace": "from-user"})
    write(home / "elva.json", {"workspace": "from-project"})
    result = resolve(env={}, cwd=home)
    assert result.settings.workspace == "from-project"
    assert result.origins["workspace"] == "project"


def test_user_config_beats_defaults(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "config" / "config.json", {"base_url": "https://staging.example.com"})
    result = resolve(env={}, cwd=home)
    assert result.settings.base_url == "https://staging.example.com"
    assert result.origins["base_url"] == "user"


def test_project_file_is_found_by_walking_up(home: Path) -> None:
    write(home / "elva.json", {"workspace": "root-level"})
    nested = home / "a" / "b"
    nested.mkdir(parents=True)
    result = resolve(env={}, cwd=nested)
    assert result.settings.workspace == "root-level"


def test_search_stops_at_the_repo_root(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "elva.json", {"workspace": "outside-the-repo"})
    result = resolve(env={}, cwd=home)
    assert result.settings.workspace is None


def test_selected_profile_overrides_user_defaults(home: Path, tmp_path: Path) -> None:
    write(
        tmp_path / "config" / "config.json",
        {
            "base_url": "https://api.getelva.ai",
            "profiles": {"staging": {"base_url": "https://api-staging.getelva.ai"}},
        },
    )
    result = resolve(overrides={"profile": "staging"}, env={}, cwd=home)
    assert result.settings.base_url == "https://api-staging.getelva.ai"
    assert result.origins["base_url"] == "profile:staging"
    assert result.profiles == ("staging",)


def test_profile_can_be_selected_by_env(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "config" / "config.json", {"profiles": {"prod": {"timeout": 5.0}}})
    result = resolve(env={"ELVA_PROFILE": "prod"}, cwd=home)
    assert result.settings.timeout == 5.0


def test_unknown_profile_is_an_error(home: Path, tmp_path: Path) -> None:
    write(tmp_path / "config" / "config.json", {"profiles": {"prod": {}}})
    with pytest.raises(ConfigError, match="unknown profile"):
        resolve(overrides={"profile": "nope"}, env={}, cwd=home)


def test_files_are_reported_whether_or_not_they_exist(home: Path) -> None:
    result = resolve(env={}, cwd=home)
    kinds = {f.kind: f.exists for f in result.files}
    assert kinds == {"project": False, "user": False}

    write(home / "elva.json", {})
    result = resolve(env={}, cwd=home)
    assert {f.kind: f.exists for f in result.files}["project"] is True


def test_every_field_has_an_origin(home: Path) -> None:
    result = resolve(env={}, cwd=home)
    assert set(result.origins) == set(type(result.settings).model_fields)


def test_malformed_json_is_an_error(home: Path) -> None:
    (home / "elva.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        resolve(env={}, cwd=home)


def test_unknown_key_is_an_error(home: Path) -> None:
    write(home / "elva.json", {"nope": 1})
    with pytest.raises(ConfigError, match="invalid setting"):
        resolve(env={}, cwd=home)


def test_bad_base_url_names_the_layer_that_set_it(home: Path) -> None:
    with pytest.raises(ConfigError, match="from env"):
        resolve(env={"ELVA_BASE_URL": "ftp://nope"}, cwd=home)


def test_bad_timeout_from_env_is_an_error(home: Path) -> None:
    with pytest.raises(ConfigError, match="must be a number"):
        resolve(env={"ELVA_TIMEOUT": "soon"}, cwd=home)


def test_settings_are_frozen(home: Path) -> None:
    settings = resolve(env={}, cwd=home).settings
    with pytest.raises(Exception, match=r"frozen|immutable"):
        settings.base_url = "https://elsewhere.example.com"
