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

## Configuration

Settings can come from several places. Highest priority wins:

1. Command flags: `--workspace`, `--collection`, `--profile`
2. Environment: `ELVA_WORKSPACE`, `ELVA_COLLECTION`, `ELVA_PROFILE`, `ELVA_TIMEOUT`
3. `elva.json` in your project
4. The selected profile in your user config
5. Your user config
6. Built in defaults

### Project file

Commit an `elva.json` next to your spec and stop repeating flags:

```json
{
  "workspace": "payments-team",
  "collection": "payments-api"
}
```

It is found by walking up from the current directory to the repo root, so it works
from any subfolder. Keep secrets out of it, it is meant to be committed.

### User config and profiles

| Platform | Location |
|---|---|
| Linux | `~/.config/elva/config.json` |
| macOS | `~/Library/Application Support/elva/config.json` |
| Windows | `%LOCALAPPDATA%\elva\config.json` |

A profile is a named set of defaults. Useful when you work across more than one
workspace and do not want a project file for each:

```json
{
  "profiles": {
    "work": { "workspace": "work-team", "collection": "work-api" },
    "side": { "workspace": "side-team" }
  }
}
```

```bash
elva --profile work collection list
```

A project file beats a profile, so a repo with its own `elva.json` always wins over
whichever profile you have selected.

### Seeing what was resolved

When something targets the wrong place, these two answer it:

```bash
elva config path    # which files were read, and whether they exist
elva config list    # each value, and which layer set it
```

```
$ elva --profile work config list
collection    work-api                        profile:work
profile       work                            flag
timeout       30.0                            default
workspace     work-team                       profile:work

profiles      side, work
```

## Requirements

- Python 3.11 or newer (bundled automatically if you install via `uv tool`)
- An [Elva](https://getelva.ai) account

## Links

- [Elva](https://getelva.ai)
- [Issues](https://github.com/Theneo-Inc/theneo-elva-cli/issues)
- [Exit codes](docs/exit-codes.md), for scripting and CI
- [Contributing](CONTRIBUTING.md)
