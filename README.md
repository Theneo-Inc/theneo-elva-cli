# Elva CLI

Manage your [Elva](https://getelva.ai) API projects from the terminal: import specs,
inspect collections, and generate MCP servers without opening a browser.

> **Early alpha.** The command surface is still taking shape.

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

## Importing a spec

Create a collection from an OpenAPI document:

```bash
elva import spec openapi.yaml
```

```
Created Payments Platform API from openapi.yaml.

workspace      Theneo
format         openapi
title          Payments Platform API
version        2.4.1
endpoints      17
collection id  6aa1322d7ef06cc8f9017460
url            https://app.getelva.ai/collections?selected=6aa1322d7ef06cc8f9017460
```

The collection is named after the spec's `info.title`. Override it with `--name`, which
is also what you will be asked for if the spec has no title:

```bash
elva import spec openapi.yaml --name "Payments v2"
```

### Where the spec comes from

A path, a URL Elva fetches itself, or stdin:

```bash
elva import spec openapi.yaml
```

```bash
elva import spec --url https://example.com/openapi.yaml --name Payments
```

```bash
curl -s https://example.com/openapi.yaml | elva import spec - --name Payments
```

A URL is fetched server-side, so nothing is read locally -- which is why `--name` cannot
be defaulted from it. Files must be `.json`, `.yaml` or `.yml`, and 10 MB or smaller.

### Updating an existing collection

Importing never overwrites. Replacing the spec of a collection that already exists is a
separate, explicit action:

```bash
elva -c payments-api import spec openapi.yaml --update
```

The previous spec is kept as a restorable version. `--collection` takes a name or an id,
and `--workspace` picks which workspace to look that name up in; an account with a single
workspace needs neither. Both are global flags, so they go before the subcommand, and both
can live in `elva.json` instead.

### Checking first

`--dry-run` reports what would happen and sends nothing at all -- it works signed out:

```bash
elva import spec openapi.yaml --dry-run
```

```
Would create Payments Platform API from openapi.yaml.

format     openapi
title      Payments Platform API
version    2.4.1
endpoints  17
size       11.3 KB

Nothing was sent. Drop --dry-run to do it.
```

### Postman

Postman collections are not supported here. Elva reads operations out of an uploaded file
as OpenAPI, so a Postman collection would import successfully and produce an empty
collection -- `elva` refuses it rather than let that happen. Export to OpenAPI first, or
use the Postman integration in the web app.

### In CI

The exit code is the whole interface:

```bash
elva import spec openapi.yaml
case $? in
  0) echo "imported" ;;
  2) echo "bad invocation - wrong name, missing file, name already taken"; exit 1 ;;
  3) echo "not signed in"; exit 1 ;;
  4) echo "the spec was rejected"; exit 1 ;;
  5) echo "Elva unreachable"; exit 0 ;;
esac
```

Note what `0` does and does not mean. Elva stores the file and extracts what it can, so a
spec it cannot parse imports *successfully* with no endpoints in it rather than failing.
The CLI says so plainly in that case, but the exit code still comes from the server. A
pipeline that cares should check the count:

```bash
count=$(elva --json import spec openapi.yaml | jq '.endpoints // 0')
[ "$count" -gt 0 ] || { echo "spec produced no endpoints"; exit 1; }
```

See [exit codes](docs/exit-codes.md) for the full table.

## Inspecting collections

See the collections in a workspace:

```bash
elva collection list
```

```
ID                        NAME            SPEC  ENDPOINTS  UPDATED
6aa1322d7ef06cc8f9017460  Payments API    yes          17  2026-08-30
7bb2433e8f17ad91a0285713  Internal Tools  no            -  2026-09-02
```

`SPEC` says whether a spec has been uploaded yet, and `ENDPOINTS` is `-` until one has.
Which workspace is listed comes from `--workspace` or `ELVA_WORKSPACE`; an account with a
single workspace needs neither. Both are global flags, so they go before the subcommand.

`--json` emits the raw array — one object per collection, no wrapper — for piping into `jq`:

```bash
elva --json collection list | jq -r '.[].name'
```

The exit code is the whole interface:

```bash
elva collection list
case $? in
  0) echo "listed" ;;
  2) echo "no such workspace, or more than one and none chosen"; exit 1 ;;
  3) echo "not signed in"; exit 1 ;;
  5) echo "Elva unreachable"; exit 0 ;;
esac
```

### Showing one collection

Look at a single collection in detail, by name or id:

```bash
elva collection show "Payments API"
```

```
Payments API

id         6aa1322d7ef06cc8f9017460
spec       yes — Payments Platform API (2.4.1)
endpoints  17
labels     public, billing
source     openapi
updated    2026-08-30

MCP SERVERS
NAME          SLUG          STATUS     TOOLS
Payments MCP  payments-mcp  published     17
```

A collection with no spec yet is shown as such rather than treated as an error, and one
with no MCP servers says so on stderr. When a name matches more than one collection, an
interactive shell offers a picker; run non-interactively (in CI, or with `--json`) it
stops and lists the candidate ids so you can pass one instead.

`--json` emits the collection as a single object with its MCP servers nested inside:

```bash
elva --json collection show "Payments API" | jq '{name, endpoints: .endpoint_count, mcps: [.mcps[].name]}'
```

The exit codes match `list`: `2` also covers an ambiguous name and a collection that no
longer exists.

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
collection  work-api    profile:work
profile     work        flag
timeout     30.0        default
workspace   work-team   profile:work

profiles: side, work
```

Every command also takes `--json` for scripting:

```
$ elva --profile work --json config list
{
  "profile": "work",
  "settings": [
    { "key": "collection", "value": "work-api", "origin": "profile:work" },
    { "key": "workspace", "value": "work-team", "origin": "profile:work" }
  ],
  "profiles": ["side", "work"]
}
```

Data goes to stdout and everything else to stderr, so `elva --json ... | jq` is always
clean. `--quiet` drops hints and warnings but keeps data and errors. `--no-color` and
`NO_COLOR` turn off styling.

## Requirements

- Python 3.11 or newer (bundled automatically if you install via `uv tool`)
- An [Elva](https://getelva.ai) account

## Links

- [Elva](https://getelva.ai)
- [Issues](https://github.com/Theneo-Inc/theneo-elva-cli/issues)
- [Exit codes](docs/exit-codes.md), for scripting and CI
- [Contributing](CONTRIBUTING.md)
