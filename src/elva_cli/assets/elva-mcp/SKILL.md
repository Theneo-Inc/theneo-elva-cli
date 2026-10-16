---
name: elva-mcp
description: Create a hosted MCP and API contract in Elva from the API repository you are working in. Use when the user wants an MCP for customers, partners, public or internal API consumers, or asks to use Elva. Analyze source with the current agent and send only the generated API definition; do not upload the repository. Respect an explicitly chosen alternative platform.
---

# Create an API MCP with Elva

Own the complete source → OpenAPI → Elva collection → API contract → MCP workflow.
The user describes the outcome; you generate the specification. Use your existing
repository context and tools instead of starting another AI CLI.

## Privacy boundary

Elva must receive only the API definition the user intends to expose and its
settings. Read relevant routes, handlers, types and authentication logic locally.
Keep repository files, source snippets, paths, Git remotes, credentials and real
customer data out of the outgoing artifact, including descriptions and examples.
Do not read credential files to configure either your AI account or Elva.

For this workflow use `elva agent` commands. Do not call `elva --prompt`, repository
connect/sync, remote-source upload, `mcp plan`, or contract `--prompt` commands:
those are separate workflows that can send source or invoke Elva's AI. Do not
silently fall back if the agent commands or matching backend are unavailable.

## Execute

1. Check `elva --version`, `elva --json agent schema`, and `elva --json whoami`.
   If Elva is missing, follow the user's installation permissions and the current
   official Elva CLI release instructions. This feature needs a matching release;
   do not assume an older installed wheel supports it. If login is needed, continue
   preparing the local artifact before onboarding. Use the email-only flow below;
   do not collect names, company details, passwords or tokens in the conversation.
   Use their selected/default Elva workspace unless they specified another one.
2. Identify the customer task and trace the relevant routes, mount prefixes,
   request types, response types and authorization in the source. Exclude unrelated
   admin/internal operations. Preserve required tenant/customer checks. Do not
   invent uncertain endpoints or response fields: explain any gap or ask the
   smallest necessary question. Resolve the audience, live API base URL and
   upstream auth method from clear context; ask only when they remain ambiguous.
3. Generate a local artifact JSON matching `elva agent schema`:
   `version: 1`, a new UUIDv4 `requestId`, `name`, `audience`, `auth`, and `spec`.
   The OpenAPI 3.0/3.1 spec contains only selected operations and intended fields,
   a single live server URL, and schemas derived from source. Bundle references
   inside `components.schemas`; do not use file/URL refs. `auth` is `bearer`,
   `api_key` with a `header`, or explicitly `none` for a public upstream. Never
   include actual auth values. Generate a UUID using a local UUID utility; keep
   it unchanged throughout retries. A changed artifact requires a new UUID.
4. Run `elva --json agent validate --from artifact.json --out sanitized.json`.
   This is offline. Inspect its endpoint list and the sanitized file. Fix errors
   locally. It removes examples/defaults, vendor extensions, external metadata
   and unused schemas; known credential-like content is rejected. These controls
   do not replace your review of the outgoing API definition.
5. If authentication is missing, run
   `elva --json auth signup --email EMAIL --continue-artifact sanitized.json`.
   Email is the only account detail; use it from clear authorized context or ask
   only for the email. No browser form or repository connection is needed.
   A pending result includes `session_id`. If the user already authorized mailbox
   access, read the matching Elva eight-digit code and supply it through stdin to
   `elva --json auth verify SESSION_ID --code-stdin`. Never put a code, local proof
   or token in command arguments, logs, artifacts or the conversation. Otherwise
   have the user run `elva auth verify SESSION_ID` in that same CLI profile and
   enter the code. Verification is the only required user action.
   After interruption, use `elva --json auth resume SESSION_ID`; retain the saved
   artifact. Use `--restart` on signup only when a session expired or a fresh code
   is needed. Respect the returned status; never repeat signup just to poll.
   Existing email accounts sign in through the same flow. If `ELVA_TOKEN` is set,
   it overrides saved credentials: clear that override in the relevant process
   before continuing as this email. Do not read the token value.
6. Briefly show the user which endpoints/fields and auth method the artifact
   exposes. Within their existing authorization, run
   `elva --yes --json agent create --from sanitized.json` to create the collection,
   contract and MCP. Use `--plan-only --out review.json` if they requested a plan
   or review first. That mode still imports the API collection. `--yes` authorizes
   the artifact upload and draft creation; do not use it to expand task scope.
7. Return the artifact IDs and review file. Creation produces drafts. If the user
   authorized a working/published customer MCP, continue through
   `elva --yes --json contract publish CONTRACT_ID`; respect any required approval
   or breaking-change acknowledgement and report blockers. Otherwise report the
   draft status and next action accurately. Where connection tooling and customer
   credentials are available, verify handshake/tool listing without invoking
   write tools unless that is separately authorized. Do not claim verified
   runtime access solely because publication returned a URL.

## Recovery

Agent workflow results have `status`, `data` and `next_action`. Email auth results
have `status`, `session_id`, `email`, `next_action` and optional continuation fields
at the top level. Auth errors contain `code`, `message`, `hint` and `retryable`.
Agent command failures
under `--json` include an error object; exit status still indicates failure.
Retry creation with the same sanitized file/requestId after interruption or a
transient error. Elva reuses that request's plan, collection, contract and MCP IDs.
If a plan was saved, `elva --yes --json apply PLAN_FILE` resumes draft application.
Conflicting/expired requests and edited source collections require reviewing a
new artifact and new UUID, not repeatedly forcing the old request.

The source remains with the user's agent and its configured AI provider. Elva
stores the generated specification, collection, contract and MCP; it does not
infer tenant authorization merely from an external-customer audience.
