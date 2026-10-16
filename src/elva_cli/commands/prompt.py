"""The intent entry point: local source -> Elva scan/AI -> contract and MCP."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from rich.text import Text

from elva_cli.errors import UsageError
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render

if TYPE_CHECKING:
    from pathlib import Path

    from elva_cli.context import Ctx


@dataclass(frozen=True)
class PromptResult:
    status: str
    plan_file: str
    result: dict[str, Any]
    next_action: str


@render.register
def _render(result: PromptResult) -> Text:
    return Text(
        printable(
            json.dumps(
                {
                    "status": result.status,
                    "plan_file": result.plan_file,
                    **result.result,
                    "next_action": result.next_action,
                },
                indent=2,
            )
        )
    )


def inferred_audience(prompt: str) -> str | None:
    matches = set()
    if re.search(r"\b(?:partner|partners|customer|customers|external)\b", prompt, re.I):
        matches.add("partner")
    if re.search(r"\bpublic\b", prompt, re.I):
        matches.add("public")
    if re.search(r"\b(?:internal use|internal team|employees|employee)\b", prompt, re.I):
        matches.add("internal")
    return next(iter(matches)) if len(matches) == 1 else None


def validate_api_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in value)
        ):
            raise ValueError("invalid API URL")
        _ = parsed.port
    except ValueError as exc:
        raise UsageError(
            "Provide an HTTP(S) API base URL without credentials, query or fragment."
        ) from exc
    return value


def run_prompt(
    ctx: Ctx,
    *,
    prompt: str | None,
    path: Path | None,
    audience: str | None,
    api_base_url: str | None,
    resume: str | None,
    plan_only: bool,
    out: Path | None,
    name: str | None,
    auth_type: str | None = None,
    api_key_header: str | None = None,
) -> None:
    from elva_cli.commands.contract import _confirm
    from elva_cli.core.services.local_source import local_plan
    from elva_cli.core.services.plan import apply_plan, read_plan, save_plan, validate_plan
    from elva_cli.core.source_snapshot import build_snapshot
    from elva_cli.settings.paths import cache_dir
    from elva_cli.ui import prompts

    if out is not None and os.path.lexists(out):
        raise UsageError("--out already exists. Choose a new plan file.")
    if api_base_url:
        api_base_url = validate_api_url(api_base_url)
    if auth_type is not None and auth_type not in {"bearer", "api_key", "none"}:
        raise UsageError("--auth-type must be bearer, api_key or none.")
    if api_key_header and (
        auth_type != "api_key"
        or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", api_key_header)
    ):
        raise UsageError("--api-key-header requires --auth-type api_key and a valid header name.")
    body = None
    if resume is None:
        if not prompt or not 1 <= len(prompt.strip()) <= 2000:
            raise UsageError("--prompt must contain between 1 and 2000 characters.")
        chosen = audience or inferred_audience(prompt)
        chosen = prompts.select(
            chosen,
            prompt="Who will use this MCP?",
            choices=("partner", "public", "internal"),
            flag="--audience",
            ctx=ctx,
        )
        snapshot = build_snapshot(ctx.cwd, path)
        ctx.out.hint(
            printable(
                f"Source: {snapshot.root}; {len(snapshot.payload['files'])} files. "
                f"{snapshot.bytes} bytes. "
                f"Excluded {snapshot.excluded} entries; "
                f"redacted {snapshot.redactions} possible secrets. Audience: {chosen}."
            )
        )
        _confirm(ctx)(
            "Upload filtered source files to Elva for AI scanning and create source collections? "
            "No GitHub connection is needed."
        )
        body = {
            "prompt": prompt,
            "audience": chosen,
            "snapshot": snapshot.payload,
            "authType": auth_type or "bearer",
        }
        if api_base_url:
            body["baseUrl"] = api_base_url
        if auth_type == "api_key":
            body["apiKeyHeader"] = api_key_header or "X-API-Key"
        if name:
            body["name"] = name
        if len(json.dumps(body).encode()) > 8 * 1024 * 1024:
            raise UsageError("Encoded source upload is too large. Narrow --path.")

    def api_url() -> str:
        while True:
            value = prompts.text(
                api_base_url,
                prompt="What is the live API base URL?",
                flag="--api-base-url",
                ctx=ctx,
            ).strip()
            try:
                return validate_api_url(value)
            except UsageError:
                if not ctx.interactive or api_base_url is not None:
                    raise
                ctx.out.hint("Enter an HTTP(S) API URL without credentials, query or fragment.")

    planned = local_plan(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        body=body,
        resume=resume,
        base_url_answer=api_url,
        progress=ctx.out.hint,
        replacement_base_url=api_base_url,
    )
    plan = planned.plan
    destination = out or cache_dir() / "plans" / f"{plan['planId']}.json"
    if out is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and out is None:
        existing = validate_plan(read_plan(destination), ctx.settings.base_url)
        if existing["digest"] != plan["digest"]:
            raise UsageError(
                "The cached plan differs from the server review. Choose a new --out path."
            )
    else:
        save_plan(planned, destination)
    review = plan["review"]
    selections = [
        f"{e['method']} {e['path']}"
        for c in review["contract"]["collections"]
        for e in c["endpoints"]
    ]
    excluded = [
        f"{s['method']} {s['path']}: {f['path']}"
        for s in review["contract"].get("endpointSchemas", [])
        for f in s.get("fields", [])
        if not f.get("included", True)
    ]
    upstream_auth = review.get("mcpAuth", {}).get("type", auth_type or "bearer")
    # Keep JSON stdout to a single final result; the review remains visible on stderr.
    ctx.out.hint(
        printable(
            f"MCP + API contract: {review['contract']['name']}\nEndpoints: "
            + ", ".join(selections)
            + "\nExcluded fields: "
            + (", ".join(excluded) or "none")
            + f"\nUpstream authentication: {upstream_auth}"
            + f"\nFull review: {destination}"
        )
    )
    if plan_only:
        ctx.out.result(
            PromptResult("planned", str(destination), {"plan": plan}, f"elva apply {destination}")
        )
        return
    applied = apply_plan(
        base_url=ctx.settings.base_url,
        workspace=ctx.settings.workspace,
        plan=plan,
        confirm=_confirm(ctx),
    )
    contract_id = applied.result["contractId"]
    ctx.out.result(
        PromptResult(
            "drafts_created",
            str(destination),
            applied.result,
            f"elva contract publish {contract_id}",
        )
    )
