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

A path, a URL, or stdin:

```bash
elva import spec openapi.yaml
```

```bash
elva import spec --url https://example.com/openapi.yaml
```

```bash
curl -s https://example.com/openapi.yaml | elva import spec - --name Payments
```

A `--url` is fetched through Elva -- the same proxy the web app uses, so a spec host only
Elva can reach still works -- and then imported like a file, so `--name` defaults from its
`info.title` too. A JSON spec is stored as YAML whichever way it came in, matching the web
app. Files must be `.json`, `.yaml` or `.yml`, and 10 MB or smaller.

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

A Postman collection in a *file* is refused here. Elva reads an uploaded file as OpenAPI,
so a collection would import successfully and produce an empty result -- `elva` stops it
rather than let that happen. Postman collections come from Postman itself instead, with
[`elva import postman`](#importing-from-postman).

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

## Importing from Postman

`elva import postman` reads a collection out of your Postman account and creates an Elva
collection from it:

```bash
elva import postman "Payments Platform API"
```

```
Created 'Payments Platform API' from Postman.

workspace      Theneo
endpoints      17
postman id     12345678-1111-2222-3333-444455556666
collection id  6aa1322d7ef06cc8f9017460
url            https://app.getelva.ai/collections?selected=6aa1322d7ef06cc8f9017460
```

A collection can be named by name or by id. An id is taken at its word and imported
directly; a name has to be looked up first. With nothing named, a terminal gets a list to
pick from:

```bash
elva import postman
```

### The Postman API key

This needs a [Postman API key](https://postman.co/settings/me/api-keys) to read your
collections with. **There is no flag that takes one**, deliberately: argv is readable by
every other process on the machine and a shell writes it to history, so a key passed that
way outlives the command that used it. It comes from one of three places instead:

```bash
export ELVA_POSTMAN_API_KEY=PMAK-...              # the environment
```

```bash
elva import postman                               # a hidden prompt, if that is unset
```

```bash
pass show postman/key | elva import postman --key-stdin    # or the first line of stdin
```

The key is used for the two requests it takes and then dropped. It is never stored, never
logged, taken back out of any message the server echoes it into, and never sent anywhere
but over `https`.

A rejected or expired key exits `3` -- a credential problem, not a bad invocation:

```bash
elva import postman Payments
case $? in
  0) echo "imported" ;;
  2) echo "no key given, or no such collection"; exit 1 ;;
  3) echo "the Postman key was rejected"; exit 1 ;;
  5) echo "Elva or Postman unreachable"; exit 0 ;;
esac
```

### Listing what is there

`--list` shows the collections the key can see and imports nothing:

```
$ elva import postman --list
3 Postman collections.

Payments Platform API  12345678-1111-2222-3333-444455556666  2026-08-14
Billing                12345678-aaaa-bbbb-cccc-ddddeeeeffff  2026-07-02
Internal Webhooks      12345678-9999-8888-7777-666655554444

Import one with: elva import postman <name or id>
```

With `--json` it is a list a script can filter, and the id it prints is exactly what
`elva import postman` takes:

```bash
uid=$(elva --json import postman --list \
  | jq -r '.collections[] | select(.name == "Billing") | .uid')
elva import postman "$uid"
```

Naming one is required wherever there is nobody to ask -- in CI, under `--json`, or with
output redirected. `elva import postman` with nothing named exits `2` there, listing what
was available, rather than guessing which of your collections you meant.

## Configuration

Settings can come from several places. Highest priority wins:

1. Command flags: `--workspace`, `--collection`, `--profile`
2. Environment: `ELVA_WORKSPACE`, `ELVA_COLLECTION`, `ELVA_PROFILE`, `ELVA_TIMEOUT`
3. `elva.json` in your project
4. The selected profile in your user config
5. Your user config
6. Built in defaults

`ELVA_TOKEN` and `ELVA_POSTMAN_API_KEY` are credentials rather than settings. They are
read from the environment only, never from a config file, and a config file that names
one is rejected -- `elva.json` is meant to be committed.

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
