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

## Authentication

Sign in via your browser once; the session refreshes itself after that:

```bash
elva auth login
```

```
Opening https://api.getelva.ai/api/auth/cli/authorize?redirect_uri=...
If your browser didn't open, paste that URL in manually.
Waiting for you to finish signing in...
Signed in.
```

No account yet? `elva auth register` runs the same browser flow against the sign-up
page instead. Both need a real browser and a terminal, so they refuse outright rather
than hang when run unattended (over SSH, in CI, with stdin closed):

```bash
elva auth login
```

```
ELVA_AUTH: elva auth login requires a browser and can't run unattended.
  -> In CI or scripts, set ELVA_TOKEN instead.
```

### Who you are

```bash
elva whoami
```

```
Signed in as jamie@example.com.
```

### Signing out

```bash
elva auth logout
```

```
Signed out.
```

Running it with nothing to sign out of says so rather than erroring:

```
You weren't signed in.
```

### In CI

Every command needs *some* credential, and a real login is a human-only, browser-only
flow — CI supplies one directly instead:

```bash
export ELVA_TOKEN=...     # a personal access token, or a session token you already have
elva mcp list
```

`ELVA_TOKEN` is checked first, ahead of anything `elva auth login` stored, and only ever
read from the environment — never from a config file, since `elva.json` is meant to be
committed. `elva auth logout` cannot remove it; if it's set, logout warns that it's
still active and has to be unset by hand.

The exit code says what kind of credential problem it is:

```bash
elva whoami
case $? in
  0) echo "signed in" ;;
  3) echo "not signed in, or the session is no longer valid"; exit 1 ;;
  5) echo "Elva unreachable"; exit 0 ;;
esac
```

See [exit codes](docs/exit-codes.md) for the full table.

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

### Endpoints of a collection

List the operations in a collection's uploaded OpenAPI spec:

```bash
elva collection endpoints "Payments API"
```

```
METHOD  PATH                 OPERATION ID       SUMMARY                 TAGS
GET     /invoices            listInvoices       List invoices           billing
POST    /invoices            createInvoice      Create an invoice       billing
GET     /invoices/{id}       getInvoice         Fetch one invoice       billing
DELETE  /invoices/{id}       deleteInvoice      Void an invoice         billing
```

"Endpoints" here means the operations in the spec you uploaded — one row per
method-and-path. A collection with no spec yet is an error (exit `2`); upload one
with `elva import spec` first.

Narrow the list with repeatable filters. Each flag is an OR within itself and an
AND across the three; `--method` is case-insensitive and `--path` matches by prefix:

```bash
elva collection endpoints "Payments API" --tag billing --method get --path /invoices
```

`--json` emits the raw array — one object per operation, no wrapper. Each object
carries `key`, `method`, `path`, `operation_id` (may be `null`), `summary` and
`tags`. The `key` is `"<METHOD> <path>"` (for example `"GET /invoices/{id}"`),
which is unambiguous even when a spec omits or repeats `operationId`, and it is
what to pipe into `elva mcp create --operations`:

```bash
elva collection endpoints my-api --json | jq -r '.[].key' \
  | elva mcp create --name my-mcp --operations -
```

See [MCP servers](#mcp-servers) for `elva mcp create` itself.

The exit codes match `list`, plus two the spec adds: `2` when the collection has
no spec uploaded, and `4` when the uploaded spec cannot be parsed. See
[exit codes](docs/exit-codes.md).

## MCP servers

See what exists in a workspace:

```bash
elva mcp list
```

```
SLUG          NAME           STATUS     TOOLS  COLLECTION
payments-mcp  Payments MCP   published     17  6aa1322d7ef06cc8f9017460
support-mcp   Support Draft  draft          9  7bb2433e8f17ad91a0285713
```

```bash
elva mcp show payments-mcp
```

```
Slug        payments-mcp
Name        Payments MCP
Status      published
Deployment  acme/payments-mcp
Version     2.4.1
Auth type   bearer
Secret      set
Operations  17
Collection  Payments API
URL         https://runtime.getelva.ai/mcp/payments-mcp
```

Both are read-only, so they work unattended without `--yes` — only creating or
publishing a server needs that.

### Creating one

Generate an MCP server from a collection's uploaded spec:

```bash
elva -c payments-api mcp create --name "Payments MCP"
```

```
warning: This makes an MCP server live and publicly reachable -- there is no way to
undo it from here.
Create and publish this MCP server now? [y/N]: y

Created 'Payments MCP'.

Deployment  acme/payments-mcp
Slug        payments-mcp
Status      published
Tools       17
Auth type   none
Secret      not set
URL         https://runtime.getelva.ai/mcp/payments-mcp
```

With nothing else given, every operation in the collection's spec is included. Narrow
it with repeated `--operations "METHOD /path"` (the same `key` shape
[`collection endpoints`](#endpoints-of-a-collection) prints), or pipe a bulk list in
with a single `--operations -`:

```bash
elva collection endpoints payments-api --json | jq -r '.[].key' \
  | elva mcp create --name "Payments MCP" --operations -
```

Auth is `--auth-type none` (the default), `bearer`, or `api_key` (with
`--api-key-header`/`--api-key-in`); anything else — `oauth`, `openid_connect`, `basic`,
`jwt` — needs a full request body via `--from` instead. `--client-secret` attaches a
secret to an `oauth`/`openid_connect` config from `--from` without ever putting it on
the command line: `env:NAME`, `file:PATH`, or `-` for stdin, never the secret itself.

`--base-url` overrides the upstream host the spec's `servers[0].url` would otherwise
give, and `--timeout` sets the upstream request timeout in milliseconds (1000-300000).

### Making it live is a confirmation boundary

Creating a server — like publishing one — makes it publicly reachable immediately,
so both warn and ask first, interactively. Unattended, that becomes a hard requirement
for `--yes` rather than a silent default:

```bash
elva mcp create --name "Payments MCP" </dev/null
```

```
ELVA_USAGE: cannot ask for confirmation: Create and publish this MCP server now?
  -> Pass --yes to confirm without prompting.
```

### Drafting instead of publishing immediately

`--draft` creates the server without making it live — nothing to confirm, since
nothing is exposed yet:

```bash
elva mcp create --name "Payments MCP" --draft
```

```
Created 'Payments MCP' as a draft.

Deployment  acme/payments-mcp
Slug        payments-mcp
Status      draft            not serving traffic
Tools       17
Auth type   none
Secret      not set
URL

Publish it with: elva mcp publish payments-mcp
```

Publish it when it's ready:

```bash
elva mcp publish payments-mcp
```

```
warning: This makes an MCP server live and publicly reachable -- there is no way to
undo it from here.
Publish 'payments-mcp' now? [y/N]: y

Published 'Payments MCP'.

Deployment  acme/payments-mcp
Slug        payments-mcp
Status      published
...
```

Publishing an already-published server is a no-op, not an error — it reports the
current state and exits `0` rather than regenerating anything:

```
'Payments MCP' is already published.
```

`--dry-run` (on `create` only) reports the tool count and which operations would be
included without creating anything, and — like `--draft` — needs no confirmation,
since nothing is created either way. The two can't be combined: a dry run creates
nothing to leave as a draft.

### Recent requests

```bash
elva mcp logs payments-mcp
```

```
TIME                  TOOL          STATUS  DURATION  AGENT   ERROR
2026-09-12T10:03:21Z  list_invoices  200       142ms  claude
2026-09-12T10:02:58Z  create_invoice 500        88ms  claude  upstream timeout
```

`--limit`/`--page` window through history; `--follow` streams new entries as they
arrive instead, starting from the latest (so it can't be combined with `--page`) and
polling until stdin closes.

### In CI

```bash
elva mcp publish payments-mcp
case $? in
  0) echo "published (or already was)" ;;
  2) echo "bad invocation, no --yes unattended, or the reason it can't publish"; exit 1 ;;
  3) echo "not signed in"; exit 1 ;;
  4) echo "the server refused to publish it (deleted collection, no spec, ...)"; exit 1 ;;
  5) echo "Elva unreachable"; exit 0 ;;
esac
```

See [exit codes](docs/exit-codes.md) for the full table.

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
