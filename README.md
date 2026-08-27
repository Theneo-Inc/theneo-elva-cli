# Elva CLI

Manage your [Elva](https://getelva.ai) API projects from the terminal: import specs,
inspect collections, and generate MCP servers without opening a browser.

> **Early alpha.** The command surface is still taking shape. This release ships
> `--version` and `--help` only; the first working commands land in `0.1.0`.

## Install

Requires Python 3.11 or newer.

```bash
uv tool install elva-cli
```

Or with [pipx](https://pipx.pypa.io/), if you already use it:

```bash
pipx install elva-cli
```

Either way, `elva` is then available from any directory:

```bash
elva --version
elva --help
```

To try it without installing anything:

```bash
uvx --from elva-cli elva --version
```

Don't have `uv`? It is a single command and no prerequisites:

```bash
curl -fsSL https://astral.sh/uv/install.sh | sh          # macOS, Linux
powershell -c "irm https://astral.sh/uv/install.ps1|iex" # Windows
```

### Upgrade

```bash
uv tool upgrade elva-cli      # or: pipx upgrade elva-cli
```

### Why not `pip install`?

On Ubuntu, Debian, Fedora and Homebrew macOS, `pip install elva-cli` fails with
`externally-managed-environment`. Those systems reserve their Python for the OS package
manager ([PEP 668](https://peps.python.org/pep-0668/)), and `--user` is blocked too.

`uv tool` and `pipx` are the supported way to install a Python command-line application:
they give it a private environment and put just the `elva` command on your `PATH`, so it
can never conflict with your projects' dependencies.

Inside an already-activated virtualenv, `pip install elva-cli` works fine.

## Requirements

- Python 3.11 or newer (bundled automatically if you install via `uv tool`)
- An [Elva](https://getelva.ai) account

## Links

- [Elva](https://getelva.ai)
- [Issues](https://github.com/Theneo-Inc/theneo-elva-cli/issues)
- [Contributing](CONTRIBUTING.md)
