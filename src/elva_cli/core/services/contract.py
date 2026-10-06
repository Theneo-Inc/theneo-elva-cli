"""API contract lifecycle, preserving server governance and publish results."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from elva_cli.auth import get_access_token, refresh_now
from elva_cli.core.api.http import HttpError, default_error, get_json, send_json
from elva_cli.core.api.targets import resolve_workspace
from elva_cli.core.services.contract_result import ContractList, ContractPublished, ContractResult
from elva_cli.errors import ApiError, ForbiddenError, UsageError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"[a-f0-9]{24}", re.IGNORECASE)


def read_body(path: Path | None, stdin: bytes | None) -> dict[str, Any]:
    if stdin is not None:
        raw = stdin
    elif path is not None:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError as exc:
            raise UsageError(f"Could not read contract JSON: {path}") from exc
    else:
        raise UsageError("Pass --from with a JSON file or '-' for stdin.")
    if len(raw) > MAX_BYTES:
        raise UsageError("Contract JSON exceeds the 2 MiB limit.")

    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    try:
        data = json.loads(raw.decode("utf-8-sig"), parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise UsageError("Contract input must be valid UTF-8 JSON.") from exc
    if not isinstance(data, dict):
        raise UsageError("Contract input must be a JSON object.")
    # 'contract show --json > file' can be edited and sent back directly.
    # Status is metadata in that envelope: echoing active must not republish.
    if isinstance(data.get("contract"), dict):
        data = {key: value for key, value in data["contract"].items() if key != "status"}
    elif isinstance(data.get("apiContract"), dict):
        data = {key: value for key, value in data["apiContract"].items() if key != "status"}
    assert isinstance(data, dict)
    return data


def _request(
    base_url: str, token: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None
) -> Any:
    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    try:
        if method == "GET":
            return get_json(f"{base_url}{path}", token=token, reauth=reauth)
        return send_json(f"{base_url}{path}", token=token, method=method, payload=body or {})
    except HttpError as exc:
        if exc.status in {400, 404, 409}:
            raise UsageError(
                exc.detail or "Contract request was rejected.",
                hint="Check the contract, source collections, approval and release policy.",
            ) from exc
        if exc.status == 403:
            raise ForbiddenError(
                exc.detail or "Contract access was denied.",
                hint="Check workspace access, PAT scope, and the assigned contract approvers.",
            ) from exc
        if exc.status == 422:
            raise ValidationError(exc.detail or "Contract validation failed.") from exc
        raise default_error(exc, action="API contract request") from exc


def _scope(base_url: str, workspace: str | None) -> tuple[str, str, str]:
    token = get_access_token(base_url=base_url)

    def reauth(stale: str) -> str:
        return refresh_now(base_url=base_url, stale_access_token=stale)

    company_id = resolve_workspace(
        base_url=base_url, token=token, workspace=workspace, reauth=reauth
    ).id
    return token, company_id, f"/api/companies/{company_id}/api-contracts"


def _row(data: Any, company_id: str) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("id"), str)
        or not _ID.fullmatch(data["id"])
        or not isinstance(data.get("name"), str)
    ):
        raise ApiError("Unexpected API contract response.")
    if data.get("company") is not None and data["company"] != company_id:
        raise ApiError("The API returned a contract from a different workspace.")
    return data


def _unwrap(data: Any, company_id: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ApiError("Unexpected API contract response.")
    return _row(data.get("apiContract"), company_id)


def _list(base_url: str, token: str, company_id: str, path: str) -> tuple[dict[str, Any], ...]:
    data = _request(base_url, token, path)
    if not isinstance(data, dict) or not isinstance(data.get("apiContracts"), list):
        raise ApiError("Unexpected API contract list.")
    return tuple(_row(row, company_id) for row in data["apiContracts"])


def list_contracts(*, base_url: str, workspace: str | None) -> ContractList:
    token, company_id, path = _scope(base_url, workspace)
    return ContractList(company_id, _list(base_url, token, company_id, path))


def _find(base_url: str, token: str, company_id: str, path: str, reference: str) -> dict[str, Any]:
    if _ID.fullmatch(reference):
        row = _unwrap(_request(base_url, token, f"{path}/{reference.lower()}"), company_id)
        if row["id"].lower() != reference.lower():
            raise ApiError("The API returned a different contract than requested.")
        return row
    matches = [
        row
        for row in _list(base_url, token, company_id, path)
        if row["name"].casefold() == reference.strip().casefold()
    ]
    if len(matches) != 1:
        raise UsageError(
            "Contract name was not found or is ambiguous.",
            hint="Run 'elva contract list' and use an exact name or ID.",
        )
    row = _unwrap(_request(base_url, token, f"{path}/{matches[0]['id']}"), company_id)
    if row["id"] != matches[0]["id"]:
        raise ApiError("The API returned a different contract than requested.")
    return row


def show_contract(*, base_url: str, workspace: str | None, reference: str) -> ContractResult:
    token, company_id, path = _scope(base_url, workspace)
    return ContractResult(company_id, "show", _find(base_url, token, company_id, path, reference))


def create_contract(
    *, base_url: str, workspace: str | None, body: dict[str, Any], confirm: Callable[[str], None]
) -> ContractResult:
    if not isinstance(body.get("name"), str) or not body["name"].strip():
        raise UsageError("A contract name is required (--name or name in --from JSON).")
    _draft_write(body)
    token, company_id, path = _scope(base_url, workspace)
    confirm(
        f"Create draft contract {body['name']!r} in workspace {company_id}? "
        "Configured stakeholders may receive notifications."
    )
    row = _unwrap(
        _request(base_url, token, path, method="POST", body={**body, "status": "draft"}), company_id
    )
    return ContractResult(company_id, "created", row)


def _draft_write(body: dict[str, Any]) -> None:
    if body.get("status") == "active":
        raise UsageError(
            "Use 'elva contract publish' to publish a contract.",
            hint="Remove status: active from this input. Save changes, then publish explicitly.",
        )


def change_contract(
    *,
    base_url: str,
    workspace: str | None,
    reference: str,
    action: str,
    body: dict[str, Any],
    confirm: Callable[[str], None],
) -> ContractResult | ContractPublished:
    if action not in {"update", "sync", "approve", "reject", "publish", "delete"}:
        raise UsageError("Unknown contract action.")
    if action == "update":
        if not body:
            raise UsageError("The update JSON is empty.")
        _draft_write(body)
    if action == "sync" and (
        not isinstance(body.get("changes"), list) or not isinstance(body.get("collections"), list)
    ):
        raise UsageError(
            "Sync JSON must contain changes and collections arrays.",
            hint="Supply the reviewed source changes with --from. Sync does not publish them.",
        )
    token, company_id, path = _scope(base_url, workspace)
    row = _find(base_url, token, company_id, path, reference)
    identifier = row["id"]
    details = {
        "delete": "This removes the contract, its hosted artifacts and associated MCP deployment.",
        "publish": (
            "This publishes the saved contract and configured destinations; "
            "approvals and release rules still apply."
        ),
        "sync": (
            "This applies the supplied source changes without publishing. "
            "Approvers may be notified."
        ),
        "update": "This saves the supplied changes. Stakeholders or approvers may be notified.",
        "approve": "This records your approval of the current contract content.",
        "reject": "This records your rejection of the current contract content.",
    }
    confirm(
        f"{action.capitalize()} contract {row['name']!r} ({identifier}) "
        f"in workspace {company_id}? {details[action]}"
    )
    if action == "publish":
        return _publish(base_url, token, company_id, f"{path}/{identifier}", row, body)
    method = "PATCH" if action == "update" else "DELETE" if action == "delete" else "POST"
    suffix = "/sync" if action == "sync" else "/approval" if action in {"approve", "reject"} else ""
    if action in {"approve", "reject"}:
        body = {**body, "decision": "approved" if action == "approve" else "rejected"}
    data = _request(base_url, token, f"{path}/{identifier}{suffix}", method=method, body=body)
    if action == "delete":
        if data is not None:
            raise ApiError("Unexpected delete response; check the contract before retrying.")
        return ContractResult(company_id, "deleted", {"id": identifier, "name": row["name"]})
    updated = (
        _row(data, company_id) if action in {"approve", "reject"} else _unwrap(data, company_id)
    )
    if updated["id"] != identifier:
        raise ApiError("The API returned a different contract after the change.")
    return ContractResult(company_id, action, updated)


def _publish(
    base_url: str,
    token: str,
    company_id: str,
    path: str,
    row: dict[str, Any],
    body: dict[str, Any] | None = None,
) -> ContractPublished:
    publishing = row.get("publishing") or {}
    configured = isinstance(publishing, dict) and (
        publishing.get("platformConfigs") or publishing.get("mcpServer")
    )
    if not configured:
        # A contract can publish its hosted artifacts without an external destination.
        _unwrap(
            _request(
                base_url, token, path, method="PATCH", body={"status": "active", **(body or {})}
            ),
            company_id,
        )
        return ContractPublished(
            company_id, row["id"], ({"platform": "elva", "status": "published"},), True
        )
    data = _request(base_url, token, f"{path}/publish", method="POST", body=body)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("results"), list)
        or any(
            not isinstance(item, dict)
            or item.get("status") not in {"published", "unchanged", "skipped", "failed"}
            for item in data["results"]
        )
    ):
        raise ApiError(
            "Unexpected contract publish response. Inspect its destinations before retrying."
        )
    results = tuple(data["results"])
    return ContractPublished(
        company_id,
        row["id"],
        results,
        bool(results) and all(item["status"] in {"published", "unchanged"} for item in results),
    )
