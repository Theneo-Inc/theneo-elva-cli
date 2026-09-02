# Exit codes

`elva` exit codes are a **public contract**. CI pipelines and agents branch on
them, so a shipped code is never renumbered and never reused for a different
meaning. Adding a new code is safe; changing an existing one is a breaking change.

| Code | Name | Meaning | Typical caller response |
|---:|---|---|---|
| `0` | `OK` | Succeeded. | continue |
| `1` | `UNEXPECTED` | The CLI hit a fault it does not model. A crash file was written and its path printed. | treat as a bug; report it |
| `2` | `USAGE` | Bad flags or arguments, or an answer was required with no terminal to ask on. | fix the invocation |
| `3` | `AUTH` | Not authenticated, or the stored credentials no longer work. | re-authenticate, then retry |
| `4` | `VALIDATION` | **The input spec is invalid. The CLI worked correctly.** | fail the build; show the report |
| `5` | `API` | The Elva API was unreachable or returned a server error. | safe to retry with backoff |
| `130` | `INTERRUPTED` | Interrupted by Ctrl-C (`128 + SIGINT`). | no action |

## Why `4` is separate from `1`

This is the distinction the whole table exists for.

`4` means *your API spec is wrong*. `1` means *the tool broke*. Collapsing them
forces every pipeline into one of two bad choices: ignore failures, or block on
failures it cannot diagnose. Keeping them apart lets CI do the obvious thing:

```bash
elva lint openapi.yaml
case $? in
  0) echo "spec is clean" ;;
  4) echo "spec has problems"; exit 1 ;;      # our fault, fail the build
  5) echo "Elva unreachable"; exit 0 ;;       # not our fault, do not block
  *) echo "elva itself failed"; exit 1 ;;
esac
```

## Retrying

Only `5` is safe to retry unconditionally. `3` is retryable after
re-authenticating. `2` and `4` will produce the same result every time — retrying
is pointless. `1` may or may not be deterministic; treat it as a bug.

## Error output

Every user-facing failure prints to **stderr**, never stdout, in one shape:

```
ELVA_AUTH: session expired
  -> Run 'elva auth login' to sign in.
```

- A stable machine-readable code (`ELVA_*`) that can be grepped and will not
  change wording between releases.
- A human message.
- Where one exists, the next action to take.

Codes currently defined: `ELVA_ERROR`, `ELVA_USAGE`, `ELVA_CONFIG`, `ELVA_AUTH`,
`ELVA_VALIDATION`, `ELVA_API`, `ELVA_CRASH`.

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
