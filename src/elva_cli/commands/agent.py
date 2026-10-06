"""Artifact-only integration for the user's existing coding agent."""

from __future__ import annotations

import json
import shlex
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.text import Text

from elva_cli.context import get_ctx
from elva_cli.core.agent_artifact import artifact_schema, normalize_artifact, read_artifact
from elva_cli.errors import ApiError, ElvaError, UsageError
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render

if TYPE_CHECKING:
    from collections.abc import Iterator

    from elva_cli.context import Ctx

app = typer.Typer(
    name="agent",
    help="Use your own agent; send API definitions, never repository snapshots.",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class AgentResult:
    status: str
    data: dict[str, Any]
    next_action: str | None = None


@render.register
def _render(result: AgentResult) -> Text:
    return Text(printable(json.dumps(asdict(result), indent=2)))


@contextmanager
def _errors(ctx: Ctx) -> Iterator[None]:
    try:
        yield
    except ElvaError as exc:
        if ctx.out.json_mode:
            ctx.out.result(
                AgentResult(
                    "error",
                    {
                        "code": exc.code,
                        "message": exc.message,
                        "hint": exc.hint,
                        "retryable": isinstance(exc, ApiError),
                    },
                )
            )
        raise


@app.command("schema")
def schema(click_ctx: typer.Context) -> None:
    """Describe the artifact accepted from an agent. Offline; no login needed."""
    get_ctx(click_ctx).out.result(
        AgentResult(
            "schema",
            {
                "schema": artifact_schema(),
                "privacy": (
                    "Only the generated API definition and settings are accepted. "
                    "Examples, defaults, external docs, extensions and unused schemas "
                    "are removed before upload."
                ),
                "workflow": [
                    "Generate a customer-only OpenAPI definition locally.",
                    "Validate with elva agent validate --from artifact.json --out sanitized.json.",
                    "Use elva --yes --json agent create --from sanitized.json.",
                    "Repeat the same file/requestId to recover; "
                    "publish through elva contract publish.",
                ],
            },
        )
    )


@app.command("validate")
def validate(
    click_ctx: typer.Context,
    from_file: Path = typer.Option(..., "--from", help="Agent-generated artifact JSON file."),
    out: Path | None = typer.Option(None, help="Save sanitized artifact to a new file; no upload."),
) -> None:
    """Validate and minimize a generated artifact entirely locally."""
    ctx = get_ctx(click_ctx)
    with _errors(ctx):
        review = normalize_artifact(read_artifact(from_file))
        if out:
            try:
                with out.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(review.artifact, indent=2, ensure_ascii=False) + "\n")
            except OSError as exc:
                raise UsageError(
                    "Could not save sanitized artifact. Choose a new writable --out path."
                ) from exc
        ctx.out.result(
            AgentResult(
                "valid",
                {
                    "request_id": review.artifact["requestId"],
                    "endpoints": review.endpoints,
                    "removed_metadata": review.removed,
                    "artifact_file": str(out) if out else None,
                    "uploaded": False,
                    "runtime_checked": False,
                },
                "elva --yes --json agent create --from " + shlex.quote(str(out or from_file)),
            )
        )


@app.command("create")
def create(
    click_ctx: typer.Context,
    from_file: Path = typer.Option(
        ..., "--from", help="Generated API artifact, not a source snapshot."
    ),
    plan_only: bool = typer.Option(
        False,
        "--plan-only",
        help="Import the API and save its review without creating the contract/MCP.",
    ),
    out: Path | None = typer.Option(
        None, help="Save immutable review JSON. Reusing the same review is safe."
    ),
) -> None:
    """Create a draft API contract and MCP using your agent's API definition; no Elva AI."""
    from elva_cli.commands.contract import _confirm
    from elva_cli.core.services.agent_artifact import create_artifact_plan
    from elva_cli.core.services.plan import apply_plan, read_plan, save_plan, validate_plan
    from elva_cli.settings.paths import cache_dir

    ctx = get_ctx(click_ctx)
    with _errors(ctx):
        review = normalize_artifact(read_artifact(from_file))
        if out and out.exists():
            existing = validate_plan(read_plan(out), ctx.settings.base_url)
            if existing["review"].get("artifactRequestId") != review.artifact["requestId"]:
                raise UsageError("--out belongs to another request. Choose a new review path.")
        ctx.out.hint(
            printable(
                f"API artifact: {review.artifact['name']}. "
                + ", ".join(review.endpoints)
                + f". Removed {review.removed} metadata entries. "
                + f"Authentication: {review.artifact['auth']['type']}."
            )
        )
        _confirm(ctx)(
            "Send this generated API definition and settings to Elva and import its collection? "
            "No repository files or Elva AI calls are used."
        )
        ctx.out.hint(
            f"Artifact request {review.artifact['requestId']}. "
            "Retry the same file/requestId after interruption."
        )
        planned = create_artifact_plan(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            artifact=review.artifact,
        )
        destination = out or cache_dir() / "plans" / f"{planned.plan['planId']}.json"
        if out is None:
            destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = validate_plan(read_plan(destination), ctx.settings.base_url)
            if existing["digest"] != planned.plan["digest"]:
                raise UsageError(
                    "Saved review differs from the server plan. Choose a new --out path."
                )
        else:
            save_plan(planned, destination)
        ctx.out.hint(
            printable(
                f"Review: {destination}. API contract + MCP: "
                f"{planned.plan['review']['contract']['name']}."
            )
        )
        common = {
            "request_id": review.artifact["requestId"],
            "plan_file": str(destination),
            "source_uploaded": False,
            "elva_ai_used": False,
            "collection_ids": [s["collectionId"] for s in planned.plan["review"]["sources"]],
        }
        if plan_only:
            ctx.out.result(
                AgentResult(
                    "planned",
                    {**common, "plan": planned.plan},
                    "elva apply " + shlex.quote(str(destination)),
                )
            )
            return
        result = apply_plan(
            base_url=ctx.settings.base_url,
            workspace=ctx.settings.workspace,
            plan=planned.plan,
            confirm=_confirm(ctx),
        ).result
        ctx.out.result(
            AgentResult(
                "drafts_created",
                {**common, "result": result},
                f"elva contract publish {result['contractId']}",
            )
        )


@app.command("setup")
def setup(
    click_ctx: typer.Context,
    target: str = typer.Option(..., help="Agent to configure: codex, claude or all."),
    user: bool = typer.Option(
        False,
        "--user",
        help="Install for your user account across projects; default is this project.",
    ),
    path: Path | None = typer.Option(
        None, help="Project directory; defaults to current directory."
    ),
) -> None:
    """Install the bundled, discoverable Elva skill. Does not read your agent credentials."""
    from elva_cli.core.agent_setup import install_skill

    ctx = get_ctx(click_ctx)
    with _errors(ctx):
        if user and path:
            raise UsageError("Use --user or --path, not both.")
        root = Path.home() if user else (path or ctx.cwd).resolve()
        installed = install_skill(root, target)
        ctx.out.result(
            AgentResult(
                "installed",
                {"files": installed, "scope": "user" if user else "project", "target": target},
                "Restart or reload your agent, then ask it to create an MCP "
                "from this repository using Elva.",
            )
        )


@app.callback()
def root() -> None:
    """Artifact-only workflows for existing coding agents."""
