# Existing-agent workflow

The user asks their existing Claude Code or Codex agent to create a customer MCP.
That agent analyzes local source, selects operations and fields, and generates an
OpenAPI artifact. Elva validates that artifact, imports one collection, and creates
a draft API contract and MCP using its existing review/apply implementation.

## One-time setup

```bash
elva agent setup --target all --user
```

Targets are `codex`, `claude`, or `all`. Without `--user`, installation applies to
the current project; `--path DIRECTORY` selects another project. Codex skills go
in `.agents/skills/elva-mcp`, Claude skills in `.claude/skills/elva-mcp`. Personal
installation uses those paths under the home directory. Existing differing files
and symlink destinations are refused. Identical repeat installation is safe.
Reload the consuming agent after setup. The agent still follows its own task and
permission rules, and an explicitly chosen alternative platform takes precedence.

Signup can happen after local artifact preparation. For direct signup, run
`elva auth signup --email you@example.com`. Email is the only signup detail. Verify in the requesting CLI; an agent with
authorized mailbox access can submit the code through stdin. The agent may prepare
the artifact first and preserve it with `--continue-artifact`. See
[email signup and recovery](email-signup.md).

## Commands and artifact

```bash
elva --json agent schema
elva --json agent validate --from artifact.json --out sanitized.json
elva --yes --json agent create --from sanitized.json
# Or import the collection and save a review before creating drafts:
elva --yes --json agent create --from sanitized.json --plan-only --out review.json
elva --yes --json apply review.json
elva --yes --json contract publish CONTRACT_ID
```

`schema` and `validate` are offline. The agent generates a JSON object with:

- `version`: `1`.
- `requestId`: a fresh lowercase UUIDv4. Keep it for retries of unchanged input.
- `name`: human-readable project name.
- `audience`: `partner` (including external customers), `public`, or `internal`.
- `auth`: `{ "type": "bearer" }`, `{ "type": "api_key", "header": "X-API-Key" }`,
  or an explicitly unauthenticated `{ "type": "none" }` upstream. Never put tokens here.
- `spec`: customer-only OpenAPI 3.0/3.1. Include only intended paths and fields.

Use one HTTP(S) server URL and local `#/components/schemas/...` references. The
machine schema documents the supported OpenAPI subset; arbitrary OpenAPI
extensions or structural features are not accepted. Limits include 2 MiB, 400
operations, 40 nested levels, and bounded schemas/text. Runtime compatibility is
checked by the backend generator before importing the collection; offline artifact
validation does not replace that deployment check. Unsupported schemas require
refining the generated definition locally, never falling back to source upload.

The CLI removes examples, defaults, vendor extensions, external metadata, security
metadata and unused schemas before upload. Auth comes from the separate explicit
settings. Actual API property names such as `example` are retained. Known secret
patterns are rejected; this is a heuristic, not a proof that free-text descriptions
contain no confidential data. The consuming agent must review the sanitized file.
Source snippets, local paths, Git URLs, private fields and real customer data must
not be copied into descriptions or other API metadata.

## Resources, recovery and errors

Default Elva workspace selection follows the normal CLI rules. Backend membership
and PAT scope checks still apply. No workspace ID is required when a default is
available. The generated contract contains every operation and field in the
submitted spec; endpoint selection belongs to the user's agent.

Creation imports a collection and applies a durable server plan to create drafts.
`--plan-only` imports the collection but defers contract/MCP creation. The returned
JSON contains `status`, `data`, and `next_action`, including review file and IDs.
With `--json`, command failures also emit structured error information and retain
the CLI's normal nonzero exit codes. Use `--yes` only within the user's authorized
scope; publication is a separate governed action.

Retry `agent create` with the same file and requestId after interruption. The plan,
collection, contract and MCP IDs remain stable. An in-progress preparation returns
a retryable error. Changed input, expired plans (seven days), or modified imported
collections require a reviewed new artifact and requestId. Failed preparation can
leave a reserved plan, spec or collection; retries reuse them. This release does
not automatically delete partially created resources.

Contract publication handles approval and breaking-change requirements. A successful
publication does not prove customer authentication or tenant isolation; those
remain enforced by the upstream API and should be tested using an authorized MCP
client. Elva does not infer tenant access from the audience label.

## Privacy and rollout

This route makes no Elva AI or repository-scanning calls. It neither launches a
second AI CLI nor reads the user's AI credentials. Source remains with the existing
agent and that agent's configured provider; it is not a claim that code never leaves
the user's computer. Elva stores the sanitized API definition and resulting resources.

`elva --prompt`, `repo connect/sync`, `mcp plan`, and contract `--prompt` are separate
source/Elva-AI workflows. The bundled skill forbids silently falling back to them.

Deploy the backend with `POST /api/companies/:companyId/api-contracts/agent/plans`
and the shared artifact validator before shipping the CLI. Older PyPI builds and
backends do not support this workflow. CLI and backend schemas must stay identical;
copy the canonical schema export into the CLI's bundled JSON when changing it and
verify parity before release. This iteration has local automated and independent
agent testing; native Claude Code and Codex product-discovery behavior still needs
release-environment smoke testing.
