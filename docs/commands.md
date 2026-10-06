# Command guide

See [the quickstart](../README.md) for the existing-agent workflow. These commands
describe this source checkout and require the matching backend. Shell examples use
POSIX syntax; adapt quoting for your shell.

## Your default workspace

`--workspace` is optional. A single Elva workspace is selected automatically.
With several workspaces, the CLI uses your configured selection (flags,
environment, project/profile/user config). Without one, it uses the default
returned by Elva, falling back to the first accessible workspace, like the web
app. Your browser's last-selected workspace is stored in the browser and is not
shared with the CLI.

```bash
elva workspace list              # * marks the active/default workspace
elva workspace switch Acme       # save a selection for subsequent commands
elva repo list                  # use the default; no workspace flag needed
elva --workspace Other repo list # override it for this command
```

Workspace-scoped PATs can discover and use their own workspace automatically
with the matching backend. Their scope and your membership are still enforced
on the server. An explicitly configured workspace that is no longer accessible
produces an error rather than silently sending a mutation somewhere else.

## Scan local source with Elva AI

No OpenAPI file or GitHub connection is needed. Sign in to Elva once with
`elva auth login`, then run this inside your API repository:

```bash
elva --prompt "Find the endpoints for external customers and create an MCP. Exclude internal notes."
```

The CLI uses your default Elva workspace, uploads a filtered snapshot of your
current source (including uncommitted code), and uses Elva's scanner and AI to
infer the OpenAPI specification. Elva imports the generated API collections,
selects endpoints and fields for the contract, and shows the review. Confirming
creates **an API contract and MCP as drafts in Elva**. It asks for the audience
when ambiguous, and for the live API URL when it cannot find one in the source.
It never asks you to write the specification.

For an agent or CI:

```bash
elva --yes --json --prompt "Create an MCP for external customer order lookups; exclude internal notes" \
  --path services/orders --audience partner \
  --api-base-url https://api.example.com --out customer.plan.json
```

Use `--auth-type api_key --api-key-header X-API-Key` for an API-key upstream,
`--auth-type none` for a public upstream, or the default `bearer`. Customer
credentials are supplied through the MCP connection flow, never placed in plans.
`--plan-only` saves a review without creating the contract/MCP, but scanning still
creates API source collections. `--name` sets the contract name; inferred names
include a unique suffix. Workflow flags go before subcommands only when using
`--prompt` or `--resume` directly.

If interrupted, missing an API URL, or retrying an AI planning failure after
scanning, resume the printed job instead of uploading again:

```bash
elva --yes --json --resume JOB_ID --api-base-url https://api.example.com
```

Failed source scans must be retried with a new prompt. Jobs waiting for input or
with failed planning are retained for seven days. Successful plans have their own
expiry. Retrying `elva apply customer.plan.json` reuses the same artifact IDs.
The JSON result includes `status`, `plan_file`, created resource IDs and
`next_action`. Publication uses the contract's existing release policy:

```bash
elva --yes contract publish CONTRACT_ID
```

This requires the matching unreleased CLI/backend/runtime; it is not available
in PyPI 0.5.0. See [local source details](local-source.md) for source filtering,
limits and recovery.

## Syncing a GitHub repository

Sign in to Elva and connect your GitHub account in the Elva web app first. The CLI
uses that existing GitHub connection; it does not request a GitHub token or read
your local Git credentials.

```bash
# Connect and scan a branch. GitHub HTTPS and SSH clone URLs also work.
elva --yes repo connect acme/payments --branch main --wait

# Inspect connections, then rescan the saved branch after pushing changes.
elva repo list
elva --yes repo sync acme/payments --wait

# Inspect or resume waiting using the scan job ID printed by connect/sync.
elva repo status JOB_ID --wait

# CI: stdout contains one JSON result; progress and errors go to stderr.
elva --yes --json repo sync acme/payments --wait --wait-timeout 600
```

Sync reads the **remote GitHub branch**, so push local changes first. It creates,
updates, or removes generated API collections using Elva's existing scanner.
Removing a generated collection also removes its associated MCP servers. Sync
does not publish new MCP servers or rebuild existing deployments; review the
collections before creating/publishing servers with `elva mcp`.

New CLI connections default to static scanning. Add `--ai` to allow AI extraction,
or `--no-ai` to disable it. Reconnecting preserves the saved branch and AI setting
unless overridden. `sync` always uses those saved settings. A connection already
linked to another workspace must be disconnected there before reconnecting.
An already-running scan is reused; changes to connection settings do not restart
that scan. Run `repo sync` after it finishes to scan with the new settings.

Without `--wait`, success means a scan was **queued or already running**. With
`--wait`, the CLI reports progress, the scanned commit, collection changes and
scan warnings. The default wait limit is 900 seconds. A timeout or Ctrl-C stops
the local wait while the remote scan continues; use `repo status JOB_ID` in the
same workspace to inspect it later. Failed, cancelled, or incomplete scans return
a nonzero exit code. If the queue is full during connection, the repository can
still be connected: the CLI reports this and tells you to retry `repo sync`.

`repo list` shows repositories connected by your linked GitHub identity in the
selected workspace. `sync` also accepts the Elva repository ID from that list.
If the generated spec lacks an API server URL, configure the repository's base
URL in the Elva web app before using its endpoints. This feature requires the
workspace-scoped repository API; older backends are rejected before any write.

## API insights

Use the same checks and grading engine as Elva's API Insights page:

```bash
elva insights checks
elva insights checks --category Security
elva insights review openapi.yaml
cat openapi.yaml | elva --json insights review - --fail-under 80
elva insights show "Payments API" --fail-under 80
```

File and stdin reviews do not need a login or workspace. The document is sent
to Elva's review endpoint; the limit is 2 MiB. `insights show` reviews a saved
collection's current spec in your default workspace and requires authentication.
Output includes design, developer experience, AI readiness and security scores,
the overall grade, scorable status and individual findings.

`--fail-under` optionally gates CI on the **overall** score. Exit 4 means the
score is below the threshold or the document is unscorable. Without that flag,
a completed review exits 0 even if it contains failed checks or an N/A grade;
an invalid/unreviewable input still exits 4. An unavailable API exits 5.
`--json` emits the full review, including coverage and unscorable reason.

## API contracts

```bash
elva contract list
elva --yes contract create --name "Partner API" --audience partner
elva --yes contract create --from contract.json
elva --json contract show "Partner API" > contract-snapshot.json
# Edit the snapshot, then save its fields without publishing:
elva --yes contract update "Partner API" --from contract-snapshot.json
elva --yes contract sync "Partner API" --from reviewed-sync.json
elva --yes contract approve "Partner API" --note "Reviewed the current schema"
elva --yes contract reject "Partner API" --note "Response fields need changes"
elva --yes contract publish "Partner API"
elva --yes contract delete "Partner API"
```

Use an exact contract name or ID. `--from` accepts a JSON file or `-` for stdin
(2 MiB limit). Creation starts as a draft. A name-only create starts an empty
draft; a full definition can select endpoints, shape fields, configure
destinations and set governance. See [the contract JSON guide](contracts.md)
for definitions and sync payloads.

Update and sync do not publish. An explicit `status: active` write is rejected
with guidance to use `contract publish`; when editing the complete `show --json`
envelope, its status metadata is omitted automatically. Other read-only fields
remain protected by the backend. Contract sync applies the reviewed `changes`,
`collections` and optional field snapshots supplied in its JSON; it does not
automatically choose how to merge source drift.

Publishing uses the saved destinations (including MCP when enabled) or activates
the contract in Elva when none are configured. Backend approvals and release
policies always apply. Partial, skipped, or failed destination results remain
visible and exit 5; some destinations may already have published successfully.
Publishing, stakeholder changes and sync may trigger the existing notification
workflow. Deletion removes associated hosted artifacts and the contract's MCP
deployment. All mutations prompt in a terminal and require global `--yes` in CI.

Admins can create, update, sync, publish and delete contracts. Members can read;
approval/rejection additionally requires being an assigned approver. JWT login
and workspace-scoped PATs work with the matching backend.

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

`--dry-run` reports what would happen without creating or updating a collection.
Local files are checked offline; `--url` fetches the document through Elva. Both work signed out:

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

See [exit codes](exit-codes.md) for the full table.

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
The default workspace is used unless overridden by `--workspace`, `ELVA_WORKSPACE`,
or saved config. Global flags go before the subcommand.

`--json` emits the raw array — one object per collection, no wrapper — for piping into `jq`:

```bash
elva --json collection list | jq -r '.[].name'
```

The exit code is the whole interface:

```bash
elva collection list
case $? in
  0) echo "listed" ;;
  2) echo "workspace or command input needs attention"; exit 1 ;;
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
COLLECTION="my-api"
elva --json collection endpoints "$COLLECTION" | jq '[.[].key]' \
  | elva --collection "$COLLECTION" --json mcp create --name my-mcp --operations - --dry-run
```

The JSON array preserves the space inside each method/path key. Global options
belong before the command. An empty selection is rejected; omit `--operations` to
use the default selection. `--dry-run` previews all operations and exclusions without
saving anything. To save the reviewed configuration, use
`elva --collection "$COLLECTION" --yes mcp create --name my-mcp --draft` with the
same operation selection, then use
`elva --yes mcp publish my-mcp` to publish it. Drafts reserve a hosted server slot
and cannot replace a published server; use a different name for a separate draft.

The exit codes match `list`, plus two the spec adds: `2` when the collection has
no spec uploaded, and `4` when the uploaded spec cannot be parsed. See
[exit codes](exit-codes.md).

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
