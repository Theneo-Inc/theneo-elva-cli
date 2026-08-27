# Contributing to Elva CLI

## Setup

Requires Python 3.11 or newer.

```bash
git clone git@github.com:Theneo-Inc/theneo-elva-cli.git
cd theneo-elva-cli

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

`-e` is an editable install, so source edits take effect with no reinstall.

With [uv](https://docs.astral.sh/uv/) instead:

```bash
uv sync --extra dev
uv run elva --version
```

## Running it

```bash
elva --version
elva --help
python -m elva_cli --version    # same entry point
```

`elva` is only on your `PATH` in a shell where the venv is activated. A fresh terminal
will say `command not found` until you `source .venv/bin/activate` — that is normal, not
a broken install.

To skip activation, symlink it once. The console script's shebang points at the venv's
interpreter by absolute path, so it works from anywhere:

```bash
ln -s "$PWD/.venv/bin/elva" ~/.local/bin/elva
```

**Do not use `uv tool install --editable` for this.** It registers a global tool named
`elva-cli` that shadows the published package, so `uvx` and `uv tool install` will keep
reporting your local dev version instead of what is on PyPI. If you already did, undo it
with `uv tool uninstall elva-cli`.

## Checks

All three must pass before a PR merges.

```bash
ruff check .           # lint
ruff format .          # format
mypy                   # types, strict
pytest
```

## Architecture

The load-bearing rule: **only `ui/` may touch the terminal.** Nothing beneath it prints,
prompts, colours, spins or exits.

```
src/elva_cli/
├── main.py          Typer root, global flags, error boundary
├── registry.py      lazy dispatch: command name -> module path
├── commands/        parse args -> call ONE service -> hand result to ui
│ ─────────────────  stdout/stdin boundary
├── core/
│   ├── services/    one function per use case -> returns a Result dataclass
│   ├── api/         client.py + generated/ (openapi-python-client)
│   └── spec/        loader, validate, diff
├── ui/              console, output, prompts, theme, renderables/, views/
├── context.py       Ctx dataclass -> typer.Context.obj
├── settings/        configuration schema and precedence
├── auth/            credential store and login flow
└── errors.py        ElvaError hierarchy + ExitCode
```

Every module carries a docstring stating what belongs in it. Read those first.

Four conventions that are cheap now and expensive later:

- **Services return typed dataclasses, never formatted strings.** `ui/output.py` decides
  whether that becomes a table or JSON. This is why `--json` costs nothing per command.
- **Every prompt takes its flag value first** — return it if present, prompt if there is a
  TTY, otherwise exit `2`. A CLI that hangs waiting for input in CI is the worst failure
  mode there is.
- **Exit codes are a public contract.** `0` ok, `1` unexpected, `2` usage, `3` auth,
  `4` spec failed validation, `5` network/API, `130` interrupted. Never collapse `4` into
  `1`; pipelines rely on the difference.
- **Keep expensive imports out of module scope.** `httpx`, `pydantic` and Textual are
  imported inside the functions that use them so `elva --version` does not pay for them.
  Budget: under 200ms.

## Releasing

See [RELEASING.md](RELEASING.md).
