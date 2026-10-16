from __future__ import annotations

import hashlib
from typing import Any

from elva_cli.core.services.contract import _request, _scope
from elva_cli.core.services.plan import canonical_json, validate_plan
from elva_cli.core.services.plan_result import PlanResult
from elva_cli.errors import ApiError, ElvaError


def create_artifact_plan(
    *, base_url: str, workspace: str | None, artifact: dict[str, Any]
) -> PlanResult:
    token, _, path = _scope(base_url, workspace)
    try:
        data = _request(base_url, token, f"{path}/agent/plans", method="POST", body=artifact)
    except ElvaError as exc:
        exc.hint = (
            (exc.hint or "")
            + f" Retry the same artifact file and requestId {artifact['requestId']}; "
            "do not upload repository source or fall back to AI planning. "
            "This requires the artifact-capable Elva backend."
        )
        raise
    if not isinstance(data, dict) or not isinstance(data.get("review"), dict):
        raise ApiError("Unexpected artifact plan response. Retry the same file/requestId.")
    data["apiOrigin"] = base_url.rstrip("/")
    data["fileDigest"] = hashlib.sha256(canonical_json(data["review"]).encode()).hexdigest()
    return PlanResult(validate_plan(data, base_url))
