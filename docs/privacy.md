# Data flow and privacy

## Existing-agent workflow

Your agent reads routes, handlers, types and authorization logic using its own tools
and configured AI provider. Elva does not launch another AI CLI or read its credentials.
`agent schema` and `agent validate` are offline. `agent create` sends the generated
API definition and settings to Elva to create a collection, contract and MCP.
No GitHub connection is needed.

Review paths, schemas and descriptions for confidential content. The validator
removes examples/defaults, vendor extensions, external metadata and unused schemas,
and rejects recognized credential patterns. These are heuristic checks, not a
substitute for reviewing the artifact. Keep source snippets, local paths, secrets,
real customer data and private fields out of it.

## Source scanning and other inputs

Root `elva --prompt` uploads a filtered local source snapshot, including eligible
uncommitted files. See [local source](local-source.md) for filters and limits.
`repo connect` / `repo sync` let Elva read a connected remote GitHub branch; local
unpushed changes are not scanned. The CLI does not extract a GitHub token from your
checkout. `mcp plan` and contract `--prompt` invoke Elva AI with their selected inputs.
There is no silent fallback from existing-agent artifacts to these modes.

OpenAPI imports send the API document. Insights reviews also send their API document,
even when no account is required. URL spec fetching uses Elva's proxy. Postman import
uses the supplied Postman credential to fetch the selected collection and imports
that API definition into Elva.

## Signup

Signup sends email and protocol fields binding verification to the requesting CLI.
The continuation artifact path/hash are stored locally, not sent during signup.
Codes use masked input or stdin; credentials use the keyring/private-file store.
`ELVA_TOKEN` overrides stored login. Keep secrets out of issues, logs and artifacts.
See [email signup](email-signup.md).

This describes CLI data flow, not a service retention or compliance policy.
Contact support@theneo.io for service-side handling questions.
