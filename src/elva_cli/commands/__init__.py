"""Command modules: one per top-level command.

Each module owns a `typer.Typer` app named `app`, parses its own arguments, calls
exactly one service, and hands the returned Result to `ctx.out`. No logic here."""
