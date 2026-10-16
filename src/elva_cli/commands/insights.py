"""API Insights command arguments and output."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from elva_cli.context import get_ctx
from elva_cli.errors import UsageError, ValidationError

if TYPE_CHECKING:
    from elva_cli.context import Ctx
    from elva_cli.core.services.insights_result import InsightReview

app = typer.Typer(
    name="insights",
    help="Review API design, developer experience, AI readiness and security.",
    no_args_is_help=True,
)


@app.command("checks")
def checks(
    click_ctx: typer.Context,
    category: str | None = typer.Option(
        None, help="Design, DeveloperExperience, AIReadiness, or Security."
    ),
) -> None:
    """List available API insight checks. No login required."""
    from elva_cli.core.services.insights import list_checks

    ctx = get_ctx(click_ctx)
    ctx.out.result(list_checks(base_url=ctx.settings.base_url, category=category))


@app.command("review")
def review(
    click_ctx: typer.Context,
    file: str = typer.Argument(
        ..., help="OpenAPI JSON/YAML file, or '-' for stdin. Sent to Elva for analysis."
    ),
    fail_under: float | None = typer.Option(
        None,
        "--fail-under",
        help="Exit 4 if unscorable or the overall score is below this threshold (0-100).",
    ),
) -> None:
    """Review an OpenAPI file using Elva's insight engine. No login required."""
    from elva_cli.core.services.insights import MAX_BYTES, review_file

    ctx = get_ctx(click_ctx)
    _threshold(fail_under)
    raw = None
    if file == "-":
        from elva_cli.ui.input import read_stdin

        raw = read_stdin(max_bytes=MAX_BYTES)
    result = review_file(
        base_url=ctx.settings.base_url, path=None if file == "-" else Path(file), stdin=raw
    )
    _emit(ctx, result, fail_under)


@app.command("show")
def show(
    click_ctx: typer.Context,
    collection: str = typer.Argument(..., help="Collection name or ID."),
    fail_under: float | None = typer.Option(
        None,
        "--fail-under",
        help="Exit 4 if unscorable or the overall score is below this threshold (0-100).",
    ),
) -> None:
    """Review the current spec of a collection in the active workspace."""
    from elva_cli.core.services.insights import review_collection

    ctx = get_ctx(click_ctx)
    _threshold(fail_under)
    result = review_collection(
        base_url=ctx.settings.base_url, workspace=ctx.settings.workspace, collection=collection
    )
    _emit(ctx, result, fail_under)


def _threshold(value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or not 0 <= value <= 100):
        raise UsageError("--fail-under must be a finite number from 0 to 100.")


def _emit(ctx: Ctx, result: InsightReview, fail_under: float | None) -> None:
    ctx.out.result(result)
    if fail_under is not None and (
        not result.review["scorable"] or result.review["overallScore"] < fail_under
    ):
        raise ValidationError(
            "The API did not meet the requested insight score threshold.",
            code="ELVA_INSIGHTS_GATE",
            hint="Review the reported checks and scorable status.",
        )
