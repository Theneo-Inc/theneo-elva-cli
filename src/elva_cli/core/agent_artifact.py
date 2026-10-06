"""Read only an agent-generated API artifact; never walk or upload source files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from jsonschema import Draft7Validator

from elva_cli.errors import UsageError

if TYPE_CHECKING:
    from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
DROP = frozenset(
    {
        "example",
        "examples",
        "default",
        "externalDocs",
        "contact",
        "license",
        "security",
        "securitySchemes",
        "tags",
        "xml",
    }
)
BAD_KEYS = frozenset({"__proto__", "constructor", "prototype"})
TOKEN = re.compile(
    r"(?:gh[pors]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|"
    r"AIza[\w-]{30,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|sk-ant-[\w-]{15,}|"
    r"xox[bp]-[A-Za-z0-9-]{10,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
ASSIGNMENT = re.compile(
    r"""(?:password|passwd|secret|token|api[_-]?key)[\w-]{0,32}['"]?\s*[:=]\s*['"][^'"\n]+['"]""",
    re.I,
)
DB_URL = re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)s?://", re.I)
METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def artifact_schema() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        files("elva_cli").joinpath("assets/agent-artifact.schema.json").read_text()
    )
    return result


@dataclass(frozen=True)
class ArtifactReview:
    artifact: dict[str, Any]
    removed: int
    endpoints: list[str]


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_artifact(path: Path) -> Any:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise UsageError("Artifact exceeds 2 MiB. Include only the intended API surface.")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise UsageError("Could not read an agent artifact JSON file.") from exc


def normalize_artifact(value: Any) -> ArtifactReview:
    schema = artifact_schema()
    nodes = removed = 0

    def fail(path: str, detail: str) -> None:
        raise UsageError(
            f"Invalid agent artifact at {path}: {detail}", code="ELVA_ARTIFACT_INVALID"
        )

    def walk(value: Any, shape: dict[str, Any], path: str, depth: int) -> Any:
        nonlocal nodes, removed
        nodes += 1
        if nodes > 50000 or depth > 40:
            fail(path, "structure exceeds limits")
        if "$ref" in shape:
            shape = schema["definitions"][shape["$ref"].rsplit("/", 1)[-1]]
        if "anyOf" in shape:
            shape = next(
                (
                    s
                    for s in shape["anyOf"]
                    if ("$ref" in s and isinstance(value, dict))
                    or (s.get("type") == "boolean" and isinstance(value, bool))
                ),
                shape["anyOf"][0],
            )
        if "$ref" in shape:
            shape = schema["definitions"][shape["$ref"].rsplit("/", 1)[-1]]
        if isinstance(value, str) and len(value) > 8192:
            fail(path, "text exceeds 8192 characters")
        if isinstance(value, str) and re.search(r"[\ud800-\udfff]", value):
            fail(path, "invalid Unicode text")
        if isinstance(value, list):
            return [
                walk(v, shape.get("items", {}), f"{path}/{i}", depth + 1)
                for i, v in enumerate(value)
            ]
        if isinstance(value, dict):
            result = {}
            for key, child_value in value.items():
                if (
                    not isinstance(key, str)
                    or key in BAD_KEYS
                    or re.search(r"[\x00-\x1f\x7f]", key)
                ):
                    fail(path, "unsafe property name")
                child = shape.get("properties", {}).get(key)
                if child is None:
                    child = next(
                        (
                            s
                            for p, s in shape.get("patternProperties", {}).items()
                            if re.search(p, key)
                        ),
                        None,
                    )
                if child is None and isinstance(shape.get("additionalProperties"), dict):
                    child = shape["additionalProperties"]
                if child is None and path != "/" and (key.startswith("x-") or key in DROP):
                    removed += 1
                    continue
                result[key] = walk(child_value, child or {}, f"{path}/{key}", depth + 1)
            return result
        return value

    artifact: dict[str, Any] = walk(value, schema, "/", 0)
    error = next(Draft7Validator(schema).iter_errors(artifact), None)
    if error:
        fail(
            "/" + "/".join(str(p) for p in error.absolute_path),
            f"does not satisfy {error.validator}",
        )
    spec = artifact["spec"]
    definitions = spec.get("components", {}).get("schemas", {})
    used: set[str] = set()
    pending: list[str] = []

    def inspect(value: Any, path: str) -> None:
        if isinstance(value, str) and (
            TOKEN.search(value) or ASSIGNMENT.search(value) or DB_URL.search(value)
        ):
            fail(path, "credential-like content must be removed locally")
        if isinstance(value, dict):
            if "$ref" in value:
                name = (
                    value["$ref"][len("#/components/schemas/") :]
                    .replace("~1", "/")
                    .replace("~0", "~")
                )
                if name not in definitions:
                    fail(path, "unresolved local schema reference")
                if name not in used:
                    used.add(name)
                    pending.append(name)
            for key, child in value.items():
                inspect(child, f"{path}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                inspect(child, f"{path}/{i}")

    inspect(
        {
            "name": artifact["name"],
            "auth": artifact["auth"],
            "spec": {k: v for k, v in spec.items() if k != "components"},
        },
        "/",
    )
    while pending:
        name = pending.pop()
        inspect(definitions[name], f"/spec/components/schemas/{name}")
    removed += sum(k not in used for k in definitions)
    if used:
        spec["components"] = {"schemas": {k: definitions[k] for k in sorted(used)}}
    else:
        spec.pop("components", None)
    url = spec["servers"][0]["url"]
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in url)
            or "\\" in url
        ):
            raise ValueError()
        _ = parsed.port
    except ValueError:
        fail("/spec/servers", "supply one HTTP(S) URL without credentials, query or fragment")
    endpoints = []
    for route, item in spec["paths"].items():
        if (
            re.search(r"[\s?#\\]", route)
            or route.startswith("//")
            or re.search(r"[{}]", re.sub(r"\{[^{}]+\}", "", route))
        ):
            fail("/spec/paths", "invalid API path")
        for method in METHODS:
            if method not in item:
                continue
            endpoints.append(f"{method.upper()} {route}")
            parameters = [*item.get("parameters", []), *item[method].get("parameters", [])]
            forbidden_headers = {
                "authorization",
                "proxy-authorization",
                artifact["auth"].get("header", "").lower(),
            }
            if any(
                p["in"] == "header" and p["name"].lower() in forbidden_headers for p in parameters
            ):
                fail("/spec/paths", "authentication must use auth settings, not tool parameters")
            for name in re.findall(r"\{([^{}]+)\}", route):
                if not any(
                    p["in"] == "path" and p["name"] == name and p.get("required") is True
                    for p in parameters
                ):
                    fail("/spec/paths", "path placeholders need required path parameters")
    if not 1 <= len(endpoints) <= 400:
        fail("/spec/paths", "select between 1 and 400 API operations")
    if len(json.dumps(artifact, ensure_ascii=False).encode()) > MAX_BYTES:
        fail("/", "artifact exceeds 2 MiB")
    return ArtifactReview(artifact, removed, endpoints)
