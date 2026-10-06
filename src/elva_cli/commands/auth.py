from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path  # noqa: TC003 - Typer resolves option types at runtime
from typing import TYPE_CHECKING

import typer

from elva_cli.core.services.auth_result import AuthFailure
from elva_cli.errors import ApiError, ElvaError, UsageError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from elva_cli.context import Ctx

from elva_cli.context import get_ctx

app = typer.Typer(name="auth", help="Sign in and manage credentials.", no_args_is_help=True)


@app.command("login")
def login(
    click_ctx: typer.Context,
    email: str | None = typer.Option(None, help="Sign in using only an email verification code."),
) -> None:
    """Sign in via your browser, or use --email for passwordless verification."""
    from elva_cli.core.services.auth import login as login_service

    ctx = get_ctx(click_ctx)
    if email is not None:
        _email_signup(ctx, email, None, False)
        return
    result = login_service(
        base_url=ctx.settings.base_url,
        on_progress=ctx.out.hint,
        interactive=ctx.interactive,
    )
    ctx.out.result(result)


@contextmanager
def _email_errors(ctx: Ctx) -> Iterator[None]:
    try:
        yield
    except ElvaError as exc:
        if ctx.out.json_mode:
            ctx.out.result(
                AuthFailure("error", exc.code, exc.message, exc.hint, isinstance(exc, ApiError))
            )
        raise


def _email_signup(ctx: Ctx, email: str | None, artifact: Path | None, restart: bool) -> None:
    from elva_cli.core.services.email_auth import finish_signup, start_signup
    from elva_cli.ui.prompts import text

    with _email_errors(ctx):
        address = text(email, prompt="Email address", flag="--email", ctx=ctx)
        result = start_signup(
            base_url=ctx.settings.base_url, email=address, artifact=artifact, restart=restart
        )
        if ctx.interactive and not ctx.out.json_mode and result.status == "pending_verification":
            import questionary

            ctx.out.hint(f"Check your email. Signup session: {result.session_id}")
            code = questionary.password(
                "Email verification code (or leave empty to finish later)"
            ).unsafe_ask()
            if code:
                result = finish_signup(
                    base_url=ctx.settings.base_url,
                    session_id=str(result.session_id),
                    code=str(code),
                    wait_seconds=30,
                )
        ctx.out.result(result)


@app.command("signup")
@app.command("register")
def register(
    click_ctx: typer.Context,
    email: str | None = typer.Option(
        None, help="Your email address; the only account detail required."
    ),
    continue_artifact: Path | None = typer.Option(
        None, help="Keep a generated API artifact locally to resume after signup."
    ),
    restart: bool = typer.Option(
        False, help="Replace the local pending session and request a fresh email code."
    ),
) -> None:
    """Sign up with only your email; verify in this CLI. Also signs in existing users."""
    _email_signup(get_ctx(click_ctx), email, continue_artifact, restart)


@app.command("verify")
def verify(
    click_ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Session ID returned by signup."),
    code_stdin: bool = typer.Option(
        False, help="Read the verification code from stdin, never command arguments."
    ),
) -> None:
    """Verify the emailed code and save authentication in the requesting CLI."""
    from elva_cli.core.services.email_auth import finish_signup

    ctx = get_ctx(click_ctx)
    with _email_errors(ctx):
        if code_stdin:
            import sys

            code = sys.stdin.readline(128).strip()
        elif ctx.interactive:
            import questionary

            code = str(questionary.password("Email verification code").unsafe_ask() or "")
        else:
            raise UsageError("Use --code-stdin to supply the emailed verification code.")
        ctx.out.result(
            finish_signup(
                base_url=ctx.settings.base_url, session_id=session_id, code=code, wait_seconds=30
            )
        )


@app.command("resume")
def resume(
    click_ctx: typer.Context,
    session_id: str = typer.Argument(..., help="Session ID returned by signup."),
    wait: float = typer.Option(
        0, min=0, max=60, help="Wait up to this many seconds for account provisioning."
    ),
) -> None:
    """Resume signup after verification or retry saving credentials after interruption."""
    from elva_cli.core.services.email_auth import finish_signup

    ctx = get_ctx(click_ctx)
    with _email_errors(ctx):
        ctx.out.result(
            finish_signup(base_url=ctx.settings.base_url, session_id=session_id, wait_seconds=wait)
        )


@app.command("logout")
def logout(click_ctx: typer.Context) -> None:
    """Sign out and forget your stored credentials."""
    from elva_cli.auth import ENV_TOKEN
    from elva_cli.core.services.auth import logout as logout_service

    ctx = get_ctx(click_ctx)
    result = logout_service(base_url=ctx.settings.base_url)
    ctx.out.result(result)
    if ctx.env.get(ENV_TOKEN):
        ctx.out.warn(
            f"{ENV_TOKEN} is set and will still be used to authenticate. "
            "Unset it to fully sign out."
        )
