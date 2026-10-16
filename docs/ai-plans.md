# AI contracts and customer MCPs

These commands require the matching Elva backend, frontend and MCP runtime release. They are not available in the previously published CLI wheel.

For a local checkout with no specification, start with [`elva --prompt`](local-source.md). No GitHub connection is needed; Elva generates the specification from source. The repository commands below remain useful for continuous sync of remote branches.

Elva's AI reads the actual specifications in the selected workspace. It selects endpoints, then applies field instructions to a contract. Repository scanning already generates specifications and materializes collections, so this workflow reuses those collections instead of importing duplicates.

## Create a customer MCP

```bash
elva --yes mcp plan --repo acme/backend --sync \
  --prompt "Customers can view their own orders and track shipments. No writes. Exclude internal notes." \
  --auth-type bearer \
  --out customer-mcp.plan.json

elva --yes apply customer-mcp.plan.json
```

`--sync` connects or rescans the repository and waits for completion. It changes the repository's generated collections and requires confirmation. Without it, planning uses the last complete scan. Connect GitHub in the Elva app first. Previously connected users whose GitHub connection is not linked to their Elva identity should reconnect once after the frontend/backend upgrade.

For a new connection, `--ai` enables AI scanning and `--branch NAME` selects a branch. Existing connections retain their settings; change them with `elva repo connect`. `--source COLLECTION_ID` can be repeated to narrow planning to particular collections, including collections unrelated to GitHub. `--api-base-url https://api.example.com` supplies a missing upstream URL.

Applying creates a **draft contract and draft MCP**. The default authentication setting is `bearer`: customers supply their own upstream API bearer credentials through the existing MCP authentication flow. Use `--auth-type api_key --api-key-header X-API-Key` for header API keys, or explicitly choose `--auth-type none` for a public upstream. These commands do not collect customer credentials. Plans contain source specifications and examples; treat the files as sensitive when the source contains sensitive content. The API must enforce which customer's records a credential can access; endpoint and field filtering do not implement tenant authorization.

Review the saved plan's `review.contract`, `review.openapi`, `review.mcpAuth`, `sources`, `messages` and `blockers`. Plans are immutable review copies. Generate another plan to change the proposal. Existing files are never overwritten.

After verifying the customer authentication and any required contract approvals:

```bash
elva --yes contract publish CONTRACT_ID
# If a Warn release policy requests acknowledgement:
elva --yes contract publish CONTRACT_ID --acknowledge-breaking-changes
```

Contract-created MCPs publish through the contract command. Standalone `mcp publish` and collection-based regeneration cannot bypass the contract's governance. Publishing reuses the draft deployment and preserves its authentication and base URL settings. Public artifact/install-page sharing stays disabled unless explicitly configured.

## Ask AI to create or edit a contract

```bash
elva contract create --source COLLECTION_ID \
  --prompt "An orders API for partners, exposing only id, status and trackingUrl" \
  --plan --out partner.plan.json

elva contract update "Customer API" \
  --prompt "Exclude internalNotes and mark trackingUrl as a URI" \
  --plan --out fields.plan.json

elva contract update "Customer API" --mode compose \
  --prompt "Add the shipment lookup endpoint; keep the existing order endpoints" \
  --plan --out endpoints.plan.json

elva --yes apply fields.plan.json
```

An update defaults to `--mode schema`, which preserves the endpoint selection. `--mode compose` changes the selected endpoints and then applies field instructions. `--plan` or `--out` returns the review without applying it. Without either, `--prompt` prepares a plan and asks to save its changes; `--yes` accepts that draft mutation in automation. `--from` remains available for explicit JSON edits and cannot be combined with `--prompt`.

## Agent integration

```bash
elva --json schema
elva --json mcp plan --source COLLECTION_ID --prompt "Read orders, exclude internal notes" --out plan.json
elva --json plan show JOB_ID --out recovered.plan.json
elva --yes --json apply plan.json
```

`schema` exposes a versioned command/parameter description without authentication, including argument/option kinds, flag markers, defaults, environment variables and choices. Put global options such as `--json`, `--workspace`, `--collection` and `--yes` before the command. The default workspace is used unless one is selected explicitly or in configuration.

Planning runs as a server job; its ID is printed to stderr immediately. The CLI polls for up to ten minutes. A disconnected client can retrieve the completed plan with `plan show JOB_ID`. Completed plans/jobs are retained for seven days. An unfinished job expires after fifteen minutes; a backend restart during planning requires a new plan. Planning cannot create contracts or deployments.

Apply is scoped to the original API server, workspace and user. MCP creation limits are checked during planning and again before apply; quota failures leave the reviewed plan available for retry after entitlement or usage changes. It checks the immutable server review, source specification fingerprints and the target contract's revision. Retrying the same saved plan returns the original receipt or resumes a partial apply using the same contract/deployment identities. Concurrent apply requests are serialized with a lease. After source or contract changes, generate a new plan. A partial failure may leave a draft; its intended contract ID is in the review. Apply receipts describe the completed operation, not the resource's later live state.

A blocked AI plan remains inspectable but cannot be applied. Unknown endpoint/field suggestions and partial AI passes are rejected. Ambiguous field names across request/response locations require an explicit JSON edit. Catalog bounds are explicit: at most 50 collections, the existing AI endpoint/total-field limits, and fewer than 60 captured fields per endpoint. Complex nested fields are presented at the same grouping depth as Elva's contract editor.

Errors retain the existing numeric exit codes. `ELVA_PLAN_PENDING` means resume the job, `ELVA_PLAN_UNAVAILABLE` means the provider/server could not complete planning, and `ELVA_PLAN_FAILED` describes a rejected plan. An apply conflict requires review rather than blindly creating another resource.

## Runtime field enforcement

Contract MCPs carry a versioned response policy. The hosted runtime projects JSON success responses to explicitly declared contract fields, recursively handling objects and arrays, omitting write-only and unknown properties, and validating the projected result. Undeclared input properties are rejected. Existing collection MCPs retain their current behavior.

Undocumented response statuses, upstream error bodies, non-JSON payloads, unresolved/opaque schemas and unsupported schema composition are withheld with a generic tool error. They never fall back to returning the raw response. These failures are recorded in MCP telemetry without the private upstream body. Generation rejects unsupported success schemas with the operation and response location before draft creation or publication. Initial support targets ordinary JSON object/array APIs; unions, recursive/opaque response schemas, dynamic dictionaries and streaming/binary payloads need a separately reviewed response policy before they can be returned.
