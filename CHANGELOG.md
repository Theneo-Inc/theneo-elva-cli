# Changelog

## Unreleased

### Repository documentation
- Add an agent-first quickstart, shareable skill link, recovery/privacy guides,
  contributor instructions, offline example and issue/PR templates.
- Restore features onto current main, retaining standalone installer support.

### Email-only CLI onboarding

- Add `auth signup` / `auth register` with email-only verification, automatic account
  and default workspace setup, `auth verify --code-stdin`, and `auth resume`.
- Preserve a generated API artifact locally with `--continue-artifact`; return its
  next command after login without source upload or another signup form.
- Bind signup proof and newly saved credentials to their API origin, recover lost
  responses, keep codes out of arguments/output, and acknowledge durable storage.
- Teach the bundled agent skill to complete onboarding with authorized email access.


### Existing-agent API artifacts

- Add `agent setup`, `agent schema`, `agent validate`, and `agent create`.
- Bundle discoverable Claude Code/Codex instructions for generating an API definition locally.
- Import only sanitized API artifacts; create resumable collection/contract/MCP drafts without Elva AI or GitHub.
- Require the matching artifact-plan backend before release.

### Prompt from a local checkout
- Add root `--prompt` to scan raw source with Elva AI, generate OpenAPI collections,
  select customer endpoints/fields, and create a reviewed draft contract and MCP.
- No GitHub connection or manually authored specification is required.
- Add audience/API URL follow-ups, bounded filtered uploads, independent ignore
  rules, secret redaction, auth options, `--plan-only` and `--resume` recovery.
- Preserve source collections on planning retries and keep draft publication governed.

### Workspace defaults, API insights and contracts
- Select the default Elva workspace automatically when no selection is configured,
  including accounts with several workspaces. Mark that default in `workspace list`.
- Add `insights checks`, `insights review`, and `insights show`, with JSON output
  and an optional overall-score gate for CI.
- Add `contract list/show/create/update/sync/approve/reject/publish/delete`.
  Creation is draft-only; publication is explicit and reports partial results.
- Support PAT workspace discovery and scoped collection/contract reads and
  lifecycle actions with the matching backend, preserving membership and roles.

### GitHub repository sync
- Add `repo list`, `repo connect`, `repo sync`, and `repo status` using Elva's
  existing linked GitHub account and scan pipeline.
- Support remote branch selection, explicit AI extraction, workspace scoping,
  resumable bounded waits, JSON results, and collection change summaries.
- Preserve reconnect settings, refuse unscoped backends before mutations, and
  report partial connection, failed scans and skipped collection sync accurately.
- Require the matching workspace-scoped repository backend before CLI rollout.

### CLI validation fixes
- Return complete MCP endpoints, including the workspace component, consistently
  from create, show, and publish; drafts have no connection URL.
- Preserve Ctrl-C exit status 130, honor `timeout` / `ELVA_TIMEOUT` in every HTTP
  transport, and reject non-finite timeouts before changing config files.
- Report denied access as `ELVA_FORBIDDEN` (exit 3) without deleting credentials.
- Require Typer 0.27.1 or newer, matching the vendored Click API the CLI uses.
- Correct the endpoints-to-MCP pipeline and distinguish source docs from PyPI 0.5.0.
- Isolate test profiles on macOS as well as Linux/Windows; smoke-test wheel commands.


### Added
- **Identify as a first-class refresh client (ELVA-200).** Every request now
  sends `X-Elva-Client: cli` and a `User-Agent: elva-cli/<version>`. The refresh
  and CLI-login exchanges carry the marker so the backend routes them on the
  body-token path and, once its compatibility flag is turned off, does not
  reject the CLI as an unmarked client.
- **Refresh-and-retry on 401.** An idempotent request (GET/HEAD) that returns
  401 on a token that looked valid now forces one refresh and retries once.
  Non-idempotent requests (the spec upload) are never auto-replayed.
- **Backoff on transient refresh failures.** A refresh that hits 429/5xx or a
  network error is retried with backoff (1s/2s/4s) before surfacing as a
  transient `ApiError` (exit 5); it never forces a re-login.

### Changed
- Refresh continues to happen proactively ~60s before the access token expires
  and to persist the rotated token atomically (temp file + rename, 0600) before
  the response is used — unchanged, but now covered by explicit tests.
- **`elva import spec --url` now fetches through Elva and uploads like a file.**
  The URL is fetched via Elva's `fetch-file` proxy (the same path the web app
  uses, so a spec host only Elva can reach still works), a JSON spec is stored
  as YAML to match a web-app import instead of one minified line, and `--name`
  now defaults from the fetched spec's `info.title`. `--dry-run --url` reports
  the real title/version/endpoint count/size, and a spec URL that 404s or times
  out is now a usage error (exit 2) rather than a late server rejection. Local
  `.json` files are converted to YAML on import for the same consistency.

### Compatibility
This version works with **both** the flagged and the unflagged backend:
- While the backend keeps `AUTH_ALLOW_BODY_REFRESH_TOKEN` on, unmarked body
  refreshes still work, so **older CLI versions keep working** too.
- Once the backend turns that flag off (this CLI version being the minimum
  supported), the server rejects unmarked and legacy ("family-less") refresh
  tokens with `401 REFRESH_TOKEN_LEGACY`. This CLI maps that to
  *"Your session has expired. Run `elva auth login` to sign in again."*
  (exit code 3). **Older CLI versions stop working at that point** and users
  must upgrade and re-login once.
