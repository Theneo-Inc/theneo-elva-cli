# Exit codes

`elva` exit codes are a **public contract**. CI pipelines and agents branch on
them, so a shipped code is never renumbered and never reused for a different
meaning. Adding a new code is safe; changing an existing one is a breaking change.

| Code | Name | Meaning | Typical caller response |
|---:|---|---|---|
| `0` | `OK` | Succeeded. | continue |
| `1` | `UNEXPECTED` | The CLI hit a fault it does not model. A crash file was written and its path printed. | treat as a bug; report it |
| `2` | `USAGE` | Bad flags or arguments, or an answer was required with no terminal to ask on. | fix the invocation |
| `3` | `AUTH` | Not authenticated, the stored credentials no longer work, or the account is not allowed to do this. | re-authenticate, then retry — **unless** the code is `ELVA_FORBIDDEN` |
| `4` | `VALIDATION` | **The input spec is invalid. The CLI worked correctly.** | fail the build; show the report |
| `5` | `API` | The Elva API was unreachable or returned a server error. | retry reads with backoff; inspect mutations first |
| `130` | `INTERRUPTED` | Interrupted by Ctrl-C (`128 + SIGINT`). | no action |

## Why `4` is separate from `1`

This is the distinction the whole table exists for.

`4` means *your API spec is wrong*. `1` means *the tool broke*. Collapsing them
forces every pipeline into one of two bad choices: ignore failures, or block on
failures it cannot diagnose. Keeping them apart lets CI do the obvious thing:

```bash
elva --yes import spec openapi.yaml
case $? in
  0) echo "spec imported" ;;
  4) echo "spec has problems"; exit 1 ;;      # our fault, fail the build
  5) echo "Elva unreachable"; exit 0 ;;       # not our fault, do not block
  *) echo "elva itself failed"; exit 1 ;;
esac
```

## `3` is two different things

Both are authorization failures, so both exit `3` — the numeric codes are a
contract every command shares, and one route's permission check is not a reason
to widen it. The **error code** separates them, because the remedy differs:

| Code | Means | What fixes it |
|---|---|---|
| `ELVA_AUTH` | Not signed in, or the credentials expired. | `elva auth login`, or a fresh token |
| `ELVA_FORBIDDEN` | Signed in fine, but this account may not do this. | someone grants the access; retrying never helps |

`elva import postman` is the first command to raise the second: listing Postman
collections needs any access to the workspace, importing one needs the editor
role. A pipeline that retries on `3` should check which it got:

```bash
if ! err=$(elva import postman Billing 2>&1 >/dev/null); then
  case "$err" in
    *ELVA_FORBIDDEN*) echo "$err"; echo "ask an admin for editor access"; exit 1 ;;
    *ELVA_AUTH*) elva auth login && elva import postman Billing ;;
    *) echo "$err"; exit 1 ;;
  esac
fi
```

## Retrying

For read-only requests, `5` can be retried with backoff. After a timeout on a
create or update, check the resource before retrying: the server may have completed it. `3` is retryable after
re-authenticating, unless it came with `ELVA_FORBIDDEN`. `2` and `4` will produce
the same result every time — retrying is pointless. `1` may or may not be
deterministic; treat it as a bug.

## Error output

Many commands print domain failures to **stderr** in this shape:

```
ELVA_AUTH: session expired
  -> Run 'elva auth login' to sign in.
```

- A stable machine-readable code (`ELVA_*`) that can be grepped and will not
  change wording between releases.
- A human message.
- Where one exists, the next action to take.

Parser failures use Typer usage text with exit `2`. Under `--json`, agent and email-auth domain errors also return structured stdout errors; older commands may use stderr only. See [the agent interface](agent-interface.md) for the different envelopes. Always inspect the exit code.

Codes currently defined: `ELVA_ERROR`, `ELVA_USAGE`, `ELVA_CONFIG`, `ELVA_AUTH`,
`ELVA_FORBIDDEN`, `ELVA_VALIDATION`, `ELVA_API`, `ELVA_CRASH`, `ELVA_AMBIGUOUS_COLLECTION`.

`ELVA_AMBIGUOUS_COLLECTION` is a specialisation of `ELVA_USAGE` (exit `2`): a
collection name matched more than one collection, so the reference was not enough
to act on. Pass the id instead.

## Cases worth calling out

`elva collection endpoints` reads a collection's uploaded spec, and the two
outcomes it adds are the reason exit `2` and exit `4` are kept apart:

- **No spec uploaded** → exit `2` (`ELVA_USAGE`). The collection exists but has no
  spec, so there is nothing to list. Fix it by uploading one with
  `elva import spec`; retrying unchanged gives the same result.
- **Spec cannot be parsed** → exit `4` (`ELVA_VALIDATION`). A spec is stored but is
  not JSON or YAML, or is not an OpenAPI document (no `paths`). The CLI worked
  correctly; the spec is wrong.

These never cross with exit `5`. A spec the backend cannot fetch from storage, an
unreachable server, or any other transport failure is exit `5` (`ELVA_API`) — never
`4`. And a malformed spec is always `4` — never `5`. So a pipeline can trust that
`4` means *fix the spec* and `5` means *retry later*.

## Crash files

An exception the CLI does not model is never shown as a traceback. It is written
to a file and only the path is printed:

```
ELVA_CRASH: unexpected error: RuntimeError: kaboom
  -> Details written to ~/.cache/elva/crashes/crash-1756652400-8891.log.
```

The file records the elva version, the Python version, the platform and the
traceback. **It deliberately does not record `argv`** — a crash report is kept on
disk, and a secret mistyped onto a command line must not outlive the process.

If the crash directory cannot be written (read-only filesystem, no `HOME`), the
error is still reported and the exit code is still `1`.

## Where this is implemented

- [`src/elva_cli/errors.py`](../src/elva_cli/errors.py) — `ExitCode` and the
  `ElvaError` hierarchy.
- [`src/elva_cli/main.py`](../src/elva_cli/main.py) — `_run()`, the single
  boundary every failure passes through.
- [`tests/unit/test_exit_codes.py`](../tests/unit/test_exit_codes.py) — asserts
  the numeric values, so renumbering fails the build.

## Repository scans

Repository commands retain the same numeric exit codes and add these stable
machine codes:

| Code | Exit | Meaning / next step |
| --- | ---: | --- |
| `ELVA_GITHUB_AUTH` | 3 | Connect or reconnect GitHub in the Elva web app; refreshing the Elva login does not fix this. |
| `ELVA_REPO_SCOPE` | 5 | The backend did not confirm the requested workspace; deploy the matching repository API. No write is attempted after a failed preflight. |
| `ELVA_REPO_QUEUE_FULL` | 5 | Queue or request limit reached. A connect result may include a saved repository with no job; retry `repo sync` later. |
| `ELVA_REPO_PLAN_LIMIT` | 5 | Review the workspace plan and connected repositories before retrying. |
| `ELVA_REPO_WAIT_TIMEOUT` | 5 | The local wait expired. Inspect the existing job with `repo status JOB_ID`. |
| `ELVA_REPO_SCAN_FAILED` | 5 | The backend scan failed. Read the job's errors before retrying. |
| `ELVA_REPO_SCAN_CANCELLED` | 2 | The remote scan was cancelled. Start a new sync when appropriate. |
| `ELVA_REPO_SYNC_INCOMPLETE` | 4 | The scan finished without confirming collection sync (for example, no endpoints found and existing collections preserved). Review the scan result. |

Exit 4 also covers repository scan output that could not be materialized into
collections. Exit 0 without `--wait` means a job was accepted or already running;
it does not assert that collections changed. A completed scan with nonfatal
warnings and valid collection results still exits 0 and includes those warnings.
Ctrl-C exits 130 and leaves the remote job running. In JSON mode, a failed scan
or wait includes its `error` and job ID in the single stdout result, followed by
the normal error on stderr. Failures before a result exists use stderr only.

## API insights and contracts

`ELVA_INSIGHTS_GATE` (exit 4) means the overall score was below `--fail-under`,
or the document was unscorable. The full review is emitted before the error so
CI can keep its findings. Without a threshold, a completed report can contain
failed checks or N/A grades and still exit 0; invalid/unreviewable inputs exit 4.

`ELVA_CONTRACT_PUBLISH_INCOMPLETE` (exit 5) means at least one configured
destination failed or was skipped, or no destination outcome was returned.
The result lists every outcome; successful destinations are not rolled back.
Membership/role/approver denial exits 3, invalid input or a blocked release exits
2, and contract validation rejection (HTTP 422) exits 4. Update and sync never
implicitly publish.

## AI plans

`ELVA_PLAN_PENDING` (5): the planning job is still running; resume with `elva plan show JOB_ID`. `ELVA_PLAN_UNAVAILABLE` (5): planning could not complete because of a provider/server failure. `ELVA_PLAN_FAILED` (4): the plan was rejected. An incomplete plan cannot be applied (4). Modified files, wrong workspaces, source/revision conflicts and a contract MCP sent to standalone publish are usage conflicts (2). Apply is idempotent: retry the same review file after uncertain network failures; never blindly create another plan/resource.


## Local source prompt jobs

`ELVA_INPUT_REQUIRED` (2): source scanning completed but the API host is missing.
Use the printed `elva --resume JOB_ID --api-base-url URL` command.
`ELVA_PLAN_PENDING` (5): local source planning is still running; resume the job.
A failed planning job with retained source collections can be retried with
`--resume` without another upload. Failed scanning without collections requires
a new prompt. Source limit/URL/filename errors fail before upload where possible.
