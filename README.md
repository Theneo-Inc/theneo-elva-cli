# Elva CLI

CLI for Theneo Editor

## Install

Requires Python 3.11 or newer. Pick one:

```bash
uv tool install elva-cli      # recommended
pipx install elva-cli         # equivalent, if you already use pipx
```

`elva` is then available from any directory, no virtualenv to activate:

```bash
elva --version
elva --help
```

To try it without installing anything:

```bash
uvx --from elva-cli elva --version
```

### Why not `pip install`?

`pip install elva-cli` into a system Python is blocked on Ubuntu, Debian, Fedora and
Homebrew macOS by [PEP 668](https://peps.python.org/pep-0668/), which reports
`externally-managed-environment`. `uv tool` and `pipx` sidestep it by installing into
an isolated environment for you and putting `elva` on your `PATH` -- which is what you
want for a command-line tool anyway. Inside an already-activated virtualenv, plain
`pip install elva-cli` works fine.

### Upgrade

```bash
uv tool upgrade elva-cli      # or: pipx upgrade elva-cli
```


## Development

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Theneo-Inc/theneo-elva-cli.git
cd theneo-elva-cli

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

`-e` installs in editable mode, so your source edits take effect immediately with
no reinstall.

Run it:

```bash
elva --version
elva --help
```

```
$ elva --version
elva 0.0.1 (python 3.12.3, linux-x86_64)
```

`python -m elva_cli --version` runs the same entry point, if you prefer that form.


### With uv (faster)

If you have [uv](https://docs.astral.sh/uv/), it replaces the venv and pip steps:

```bash
uv sync --extra dev
uv run elva --version
```

#### Running `elva` from any directory (development)

To activate everywhere locally:

```bash
uv tool install --editable ~/Desktop/theneo-elva-cli
```

### Checks

```bash
ruff check .        # lint
ruff format .       # format
mypy                # types, strict
```

### Version numbers

The version comes from the git tag via `hatch-vcs` -- there is nothing to bump by hand.
An untagged checkout reports something like `0.0.post1.dev2+gc657326`, which PyPI will
not accept; a tagged one reports a clean `0.0.1`.

To cut a release, see [RELEASING.md](RELEASING.md).

