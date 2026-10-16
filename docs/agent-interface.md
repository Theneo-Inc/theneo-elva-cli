# Interface for agents and automation

Use the [bundled skill](../src/elva_cli/assets/elva-mcp/SKILL.md) for the full workflow.

## Discovery

```bash
elva --version
elva --json schema
elva --json agent schema
```

Command and artifact schemas are available offline. They describe the installed CLI,
not the configured backend's capabilities. `agent schema` returns `data.schema`.
Install the skill with `elva agent setup --target all --user`, then reload the client.
Repository `AGENTS.md` and `CLAUDE.md` guide CLI development, not consumer installation.

## Inputs

Global flags precede the command. Supply values explicitly in unattended use.
`--yes` confirms a mutation within the user's authorization; it does not authorize
later unrelated actions. Creation and publication remain separate, with backend
governance. Generate the customer-only artifact from source without uploading source.
Use masked input/stdin for verification codes. Access email only when authorized.

## Output and recovery

JSON shapes vary by command:

| Family | Shape |
|---|---|
| `agent schema/validate/create/setup` | `status`, `data`, `next_action` |
| Email `auth signup/verify/resume` | Top-level `status`, `session_id`, `email`, continuation fields and `next_action` |
| `whoami` | Top-level `email` and optional company information |
| `collection list/endpoints` | Array |
| `workspace list` | Object with `workspaces` and selection information |

Agent domain errors use `status: error` and `data.code/message/hint/retryable`.
Email-auth errors put those error fields at the top level. Some parser/older-command
errors use stderr only. Always check process exit status as well as stdout.

`pending_verification` is not authenticated, even when the request exits successfully.
`valid` means offline validation, not upstream verification. `planned` may already
include an imported collection. `drafts_created` does not mean the MCP is published.
Publication can be partial; a URL does not prove a successful authorized MCP call.

| State | Action |
|---|---|
| Pending verification | Submit the matching code in the same CLI profile. |
| Signup processing | `auth resume SESSION_ID --wait 30`; do not request another email to poll. |
| Expired/exhausted session | Start with `auth signup --email EMAIL --restart`, respecting rate limits. |
| Artifact creation interrupted | Retry unchanged artifact with the same `requestId`, or apply the saved plan. |
| Changed artifact, expired plan or changed collection | Review a new artifact and assign a fresh UUID. |
| Incomplete publication | Inspect results; some destinations may already be live. |
| Forbidden | Resolve workspace/approver access; logging in again does not grant permission. |

Do not blindly replay timed-out mutations. See [exit codes](exit-codes.md).
Returned commands use POSIX quoting; Windows integrations should construct argument
arrays from structured fields instead of evaluating `next_action` in the shell.

## Acceptance

Test a fresh profile and unfamiliar repository in actual supported agent clients.
Verify native skill discovery, selected endpoints/fields, email verification,
workspace selection, interrupted-work recovery and actual publication state.
Test an authorized customer MCP call. Supplying the skill text directly to an agent
or passing unit tests does not establish automatic discovery.
