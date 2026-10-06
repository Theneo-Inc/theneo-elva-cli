from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from elva_cli.core.agent_artifact import normalize_artifact, read_artifact
from elva_cli.core.agent_setup import install_skill
from elva_cli.errors import UsageError
from elva_cli.main import app


def artifact() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        (Path(__file__).parents[1] / "fixtures/agent-artifact.json").read_text()
    )
    return value


def test_minimizes_metadata_without_removing_real_schema_fields() -> None:
    value = artifact()
    value["spec"]["x-source"] = "PRIVATE_SOURCE_SENTINEL"
    value["spec"]["info"]["contact"] = {"email": "private@example.test"}
    props = value["spec"]["paths"]["/orders"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["properties"]
    props["example"] = {"type": "string", "example": "PRIVATE_EXAMPLE"}
    props["default"] = {"type": "boolean", "default": True}
    value["spec"]["components"] = {"schemas": {"Private": {"type": "string"}}}
    original = copy.deepcopy(value)
    result = normalize_artifact(value)
    assert result.removed == 5
    assert result.endpoints == ["GET /orders"]
    assert "PRIVATE" not in json.dumps(result.artifact)
    assert '"example": {"type": "string"}' in json.dumps(result.artifact)
    assert '"default": {"type": "boolean"}' in json.dumps(result.artifact)
    assert value == original
    assert normalize_artifact(result.artifact).removed == 0


@pytest.mark.parametrize(
    "case", ["raw_source", "ref", "secret", "path", "header", "override", "unicode", "url", "deep"]
)
def test_rejects_unsafe_or_unsupported_artifacts(case: str) -> None:
    value = artifact()
    operation = value["spec"]["paths"]["/orders"]["get"]
    if case == "raw_source":
        value["files"] = [{"path": "app.ts", "content": "source"}]
    elif case == "ref":
        operation["responses"]["200"]["content"]["application/json"]["schema"] = {
            "$ref": "file:///etc/passwd"
        }
    elif case == "secret":
        operation["description"] = "ghp_" + "a" * 40
    elif case == "path":
        value["spec"]["paths"]["/orders/{id}"] = value["spec"]["paths"].pop("/orders")
    elif case == "header":
        operation["parameters"] = [
            {"in": "header", "name": "Authorization", "schema": {"type": "string"}}
        ]
    elif case == "override":
        operation["servers"] = [{"url": "https://other.example.test"}]
    elif case == "unicode":
        operation["description"] = chr(0xD800)
    elif case == "url":
        value["spec"]["servers"][0]["url"] = "https://user:password@example.com"
    else:
        schema: dict[str, Any] = {"type": "object"}
        operation["responses"]["200"]["content"]["application/json"]["schema"] = schema
        for _ in range(45):
            schema["properties"] = {"nested": {"type": "object"}}
            schema = schema["properties"]["nested"]
    with pytest.raises(UsageError):
        normalize_artifact(value)


def test_local_refs_are_retained_and_unused_definitions_pruned() -> None:
    value = artifact()
    value["spec"]["components"] = {
        "schemas": {"Order": {"type": "string"}, "Private": {"type": "number"}}
    }
    value["spec"]["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/Order"}
    assert list(normalize_artifact(value).artifact["spec"]["components"]["schemas"]) == ["Order"]


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text('{"name":"first","name":"second"}')
    with pytest.raises(UsageError):
        read_artifact(path)


def test_setup_installs_both_targets_and_preserves_existing_instructions(tmp_path: Path) -> None:
    installed = install_skill(tmp_path, "all")
    assert len(installed) == 3
    assert install_skill(tmp_path, "all") == installed
    target = Path(installed[0])
    target.write_text("user instructions")
    with pytest.raises(UsageError, match="differs"):
        install_skill(tmp_path, "all")
    assert target.read_text() == "user instructions"


def test_setup_preserves_utf8_with_a_non_utf8_default_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read = Path.read_text

    def legacy_read(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        return original_read(path, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", legacy_read)
    installed = install_skill(tmp_path, "all")
    assert install_skill(tmp_path, "all") == installed
    expected = files("elva_cli").joinpath("assets/elva-mcp/SKILL.md").read_text(encoding="utf-8")
    assert Path(installed[0]).read_text(encoding="utf-8") == expected


def test_setup_refuses_symlink_without_writing_other_target(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / ".claude").symlink_to(real, target_is_directory=True)
    with pytest.raises(UsageError, match="symlink"):
        install_skill(tmp_path, "all")
    assert not (tmp_path / ".agents").exists()


def test_schema_and_validate_are_offline_and_failures_are_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "agent", "schema"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["schema"]["required"]
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact()))
    out = tmp_path / "sanitized.json"
    result = runner.invoke(
        app, ["--json", "agent", "validate", "--from", str(path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["uploaded"] is False
    assert json.loads(out.read_text()) == artifact()
    path.write_text('{"files": []}')
    result = runner.invoke(app, ["--yes", "--json", "agent", "create", "--from", str(path)])
    assert isinstance(result.exception, UsageError)
    assert result.exception.exit_code == 2
    assert json.loads(result.stdout)["status"] == "error"
    assert "ELVA_CRASH" not in result.output


@pytest.mark.parametrize(
    "description", ['"password": "synthetic-password"', "token='synthetic-token'"]
)
def test_quoted_credential_assignments_are_rejected(description: str) -> None:
    value = artifact()
    value["spec"]["info"]["description"] = description
    with pytest.raises(UsageError):
        normalize_artifact(value)


@pytest.mark.parametrize("route", ["/orders/{id", "/orders/{}", "/orders/{nested{id}}"])
def test_malformed_placeholders_are_rejected(route: str) -> None:
    value = artifact()
    value["spec"]["paths"][route] = value["spec"]["paths"].pop("/orders")
    with pytest.raises(UsageError):
        normalize_artifact(value)


def test_long_reference_chain_has_no_recursive_stack_growth() -> None:
    value = artifact()
    defs = {f"S{i}": {"$ref": f"#/components/schemas/S{i + 1}"} for i in range(998)}
    defs["S998"] = {"type": "string"}
    value["spec"]["components"] = {"schemas": defs}
    value["spec"]["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"$ref": "#/components/schemas/S0"}
    assert len(normalize_artifact(value).artifact["spec"]["components"]["schemas"]) == 999


def test_oversized_enum_string_fails_before_credential_pattern_scan() -> None:
    value = artifact()
    value["spec"]["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ] = {"type": "string", "enum": ["password" * 5000]}
    with pytest.raises(UsageError):
        normalize_artifact(value)


def test_next_action_quotes_artifact_path(tmp_path: Path) -> None:
    import shlex

    path = tmp_path / "customer API; echo nope.json"
    path.write_text(json.dumps(artifact()))
    result = CliRunner().invoke(app, ["--json", "agent", "validate", "--from", str(path)])
    assert result.exit_code == 0
    assert shlex.split(json.loads(result.stdout)["next_action"])[-1] == str(path)


def test_personal_setup_uses_selected_home_without_touching_real_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = CliRunner().invoke(app, ["--json", "agent", "setup", "--target", "all", "--user"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["scope"] == "user"
    assert all(Path(p).is_relative_to(tmp_path) for p in data["files"])
