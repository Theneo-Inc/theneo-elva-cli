"""Email-only onboarding. Verification and the requesting CLI's proof are both required."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from elva_cli.auth import get_access_token, save_login
from elva_cli.auth.store import StoreUnavailableError
from elva_cli.core.agent_artifact import normalize_artifact, read_artifact
from elva_cli.core.api.http import HttpError, get_json, send_json
from elva_cli.core.services.auth_result import EmailAuthResult
from elva_cli.errors import ApiError, AuthError, ElvaError, UsageError
from elva_cli.settings.paths import config_dir


def _directory() -> Path:
    root = config_dir() / "auth-sessions"
    if root.is_symlink():
        raise UsageError("Signup session directory must not be a symlink.")
    try:
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(0o700)
    except OSError as exc:
        raise UsageError("Could not access private signup session storage.") from exc
    return root


def _read(path: Path, base_url: str | None = None) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError()
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("version") != 1
            or not isinstance(data.get("apiOrigin"), str)
            or (base_url is not None and data["apiOrigin"] != base_url.rstrip("/"))
            or not re.fullmatch(r"[a-f0-9-]{36}", data.get("sessionId", ""))
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", data.get("verifier", ""))
            or not isinstance(data.get("email"), str)
        ):
            raise ValueError()
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise UsageError("Signup session is invalid or belongs to another API server.") from exc


def _save_new(path: Path, data: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".signup-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)  # Atomic and exclusive: another process cannot replace its proof.
    finally:
        temp.unlink(missing_ok=True)


def _request(base_url: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = send_json(
            base_url.rstrip("/") + "/api/auth/cli/email/" + endpoint,
            token=None,
            method="POST",
            payload=payload,
        )
    except HttpError as exc:
        if exc.status == 401:
            raise AuthError(
                exc.detail or "Signup session or verification code is invalid.",
                code="ELVA_SIGNUP_INVALID",
            ) from exc
        if exc.status in (400, 409, 422):
            raise UsageError(exc.detail or "Signup input was not accepted.") from exc
        raise ApiError(
            f"Email signup failed (HTTP {exc.status}).",
            hint="Retry the same session. This flow requires the email-signup backend.",
        ) from exc
    if not isinstance(result, dict) or result.get("status") not in {
        "pending_verification",
        "processing",
        "authenticated",
        "completed",
    }:
        raise ApiError("Unexpected signup response. The saved session can be retried.")
    return result


def _pending(data: dict[str, Any], response: dict[str, Any]) -> EmailAuthResult:
    pending = response["status"] == "pending_verification"
    return EmailAuthResult(
        response["status"],
        data["sessionId"],
        data["email"],
        response.get("expiresAt"),
        artifact_file=data.get("artifactFile"),
        next_action=("elva --json auth verify " if pending else "elva --json auth resume ")
        + data["sessionId"]
        + (" --code-stdin" if pending else ""),
        message="Enter the code from your email in this CLI session."
        if pending
        else "Resume this saved signup session.",
    )


def start_signup(
    *, base_url: str, email: str, artifact: Path | None = None, restart: bool = False
) -> EmailAuthResult:
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise UsageError("Provide a valid email address with --email.")
    directory = _directory()
    filename = hashlib.sha256((base_url.rstrip("/") + "\n" + email).encode()).hexdigest() + ".json"
    path = directory / filename
    continuation: dict[str, Any] = {}
    if artifact:
        normalize_artifact(read_artifact(artifact))
        resolved = artifact.resolve()
        continuation = {
            "artifactFile": str(resolved),
            "artifactHash": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        }
    if path.exists() and restart:
        path.unlink()
    if not path.exists():
        data = {
            "version": 1,
            "apiOrigin": base_url.rstrip("/"),
            "sessionId": str(uuid.uuid4()),
            "email": email,
            "verifier": secrets.token_urlsafe(48),
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
            **continuation,
        }
        try:
            _save_new(path, data)
        except FileExistsError:
            pass
        except OSError as exc:
            raise UsageError("Could not save signup session. No email request was sent.") from exc
    data = _read(path, base_url)
    if continuation and any(data.get(k) != v for k, v in continuation.items()):
        raise UsageError("A signup session already preserves another artifact. Resume it first.")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(data["verifier"].encode()).digest())
        .decode()
        .rstrip("=")
    )
    try:
        response = _request(
            base_url,
            "start",
            {"email": email, "sessionId": data["sessionId"], "codeChallenge": challenge},
        )
    except ElvaError as exc:
        exc.hint = (
            exc.hint or ""
        ) + " The session is saved locally. Retry signup or use --restart for a fresh email code."
        raise
    if response["status"] != "pending_verification":
        return finish_signup(base_url=base_url, session_id=data["sessionId"])
    return _pending(data, response)


def _find(session_id: str, base_url: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[a-f0-9-]{36}", session_id):
        raise UsageError("Invalid signup session ID.")
    for path in _directory().glob("*.json"):
        # Read only this feature's bounded, private session documents.
        try:
            data = _read(path)
        except UsageError:
            continue
        if data["sessionId"] == session_id:
            if data["apiOrigin"] != base_url.rstrip("/"):
                raise UsageError("Signup session belongs to another API server.")
            return path, data
    raise UsageError("No local proof for this signup session. Start signup in this CLI.")


def finish_signup(
    *, base_url: str, session_id: str, code: str | None = None, wait_seconds: float = 0
) -> EmailAuthResult:
    if code is not None and not re.fullmatch(r"[0-9]{8}", code.strip()):
        raise UsageError("Enter the eight-digit verification code from your email.")
    path, data = _find(session_id, base_url)
    proof = {"sessionId": session_id, "verifier": data["verifier"]}
    deadline = time.monotonic() + wait_seconds
    response = _request(
        base_url,
        "verify" if code is not None else "resume",
        {**proof, **({"code": code.strip()} if code is not None else {})},
    )
    while response["status"] == "processing" and time.monotonic() < deadline:
        time.sleep(min(2, max(0, deadline - time.monotonic())))
        response = _request(base_url, "resume", proof)
    if response.get("sessionId") != session_id:
        raise ApiError("Signup returned a different session. The saved session can be retried.")
    if response["status"] == "completed":
        # The ack response may have been lost after the server cleared its cache.
        # Confirm the durable credentials still identify this email before cleanup.
        try:
            identity = get_json(
                base_url.rstrip("/") + "/api/auth/me",
                token=get_access_token(base_url=base_url, use_env=False),
            )
            if identity["user"]["email"].lower() != data["email"]:
                raise ValueError()
        except (HttpError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise AuthError(
                "This signup is complete, but its login is unavailable. "
                "Sign in again with your email."
            ) from exc
        with contextlib.suppress(OSError):
            path.unlink()
        return _finished(data, response, "Signed in. Continue your saved API workflow.")
    if response["status"] != "authenticated":
        return _pending(data, response)
    try:
        if (
            response["user"]["email"].lower() != data["email"]
            or response["sessionId"] != session_id
        ):
            raise ValueError()
        if not isinstance(response.get("workspace"), dict) or not isinstance(
            response["workspace"].get("id"), str
        ):
            raise ValueError()
        save_login(response, base_url=base_url)
    except (StoreUnavailableError, OSError) as exc:
        raise AuthError(
            "Verified, but credentials could not be saved. Resume this session to retry."
        ) from exc
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ApiError("Signup returned invalid credentials. Resume the saved session.") from exc
    # Acknowledge only after durable local credential storage. Keep the proof on errors.
    try:
        _request(base_url, "ack", proof)
    except ElvaError:
        message = "Signed in. Session cleanup is pending; resume to retry cleanup."
    else:
        with contextlib.suppress(OSError):
            path.unlink()
        message = "Signed in. Continue your saved API workflow."
    return _finished(data, response, message)


def _finished(data: dict[str, Any], response: dict[str, Any], message: str) -> EmailAuthResult:
    next_action: str | None = "elva --json whoami"
    if data.get("artifactFile"):
        artifact = Path(data["artifactFile"])
        try:
            same = hashlib.sha256(artifact.read_bytes()).hexdigest() == data["artifactHash"]
        except OSError:
            same = False
        if same:
            next_action = "elva --yes --json agent create --from " + shlex.quote(str(artifact))
        else:
            next_action = "elva --json agent validate --from " + shlex.quote(str(artifact))
    if os.environ.get("ELVA_TOKEN"):
        next_action = None
        message += " Unset ELVA_TOKEN before continuing; it overrides this saved login."
    return EmailAuthResult(
        "authenticated",
        data["sessionId"],
        data["email"],
        workspace_id=response.get("workspace", {}).get("id"),
        artifact_file=data.get("artifactFile"),
        next_action=next_action,
        message=message,
    )
