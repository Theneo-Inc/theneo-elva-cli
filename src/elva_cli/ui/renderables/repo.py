from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from elva_cli.core.services.repo_result import RepoListResult, RepoScanResult  # noqa: TC001
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render


@render.register
def _(result: RepoListResult) -> RenderableType:
    if not result.repositories:
        return Text(
            "No connected repositories in this workspace. Use 'elva repo connect OWNER/REPO'."
        )
    table = Table(box=None, pad_edge=False, header_style="elva.key")
    for column in ("ID", "REPOSITORY", "BRANCH", "AI", "LAST SCAN", "JOB ID"):
        table.add_column(column)
    for repo in result.repositories:
        table.add_row(
            repo.id,
            printable(f"{repo.owner}/{repo.name}"),
            printable(repo.branch),
            "on" if repo.ai_enabled else "off",
            printable(repo.last_scan_at or "-"),
            repo.last_scan_job_id or "-",
        )
    return table


@render.register
def _(result: RepoScanResult) -> RenderableType:
    repo, job = result.repository, result.job
    state = job.status if job else ("already running" if result.already_running else "queued")
    if result.scan_job_id is None:
        state = "connected; scan not queued"
    lines: list[RenderableType] = [
        Text(printable(f"{repo.owner}/{repo.name} ({repo.branch}): {state}"))
    ]
    if result.scan_job_id:
        lines.append(Text(f"Scan job: {result.scan_job_id}"))
    if job:
        lines.append(Text(printable(f"Progress: {job.progress:g}% {job.current_step or ''}")))
        if job.commit_sha:
            lines.append(Text(printable(f"Commit: {job.commit_sha}")))
        if job.collections:
            for action in ("created", "updated", "unchanged", "removed"):
                refs = job.collections[action]
                names = ", ".join(str(ref.get("name") or ref.get("id")) for ref in refs)
                lines.append(
                    Text(
                        printable(
                            f"{action.capitalize()}: {len(refs)}" + (f" ({names})" if names else "")
                        )
                    )
                )
            if job.collections.get("skipped"):
                lines.append(
                    Text(printable(f"Collection sync skipped: {job.collections['skipped']}"))
                )
        for error in job.errors:
            lines.append(
                Text(
                    printable(f"Scan warning [{error.get('step', '')}]: {error.get('message', '')}")
                )
            )
    return Group(*lines)
