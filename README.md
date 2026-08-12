# Elva CLI

CLI for Theneo Editor

...i will update soon

## Quick start

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
elva 0.1.0 (python 3.12.3, linux-x86_64)
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

The version comes from the git tag via `hatch-vcs` — there is nothing to bump by hand. An untagged checkout reports something like
`0.0.post1.dev1+g5aaf07a.d20260812`; tag a release and it becomes clean:

```bash
git tag v0.1.0
```

