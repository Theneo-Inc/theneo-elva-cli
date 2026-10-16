# API contract JSON

`contract create --from FILE` accepts the backend contract definition, not an
OpenAPI document. Import your API as a collection first, then use the ID from
`elva --json collection list`. A minimal selected-endpoint definition is:

```json
{
  "name": "Partner API",
  "audience": "partner",
  "description": "Partner access to users",
  "collections": [
    {
      "collection": "0123456789abcdef01234567",
      "collectionName": "Users",
      "endpoints": [{"method": "GET", "path": "/users"}],
      "sourceEndpoints": [{"method": "GET", "path": "/users"}]
    }
  ],
  "publishing": {
    "platforms": [],
    "platformConfigs": [],
    "publicArtifacts": false,
    "mockServer": false,
    "mcpServer": false
  },
  "governance": {
    "breakingChangePolicy": "block",
    "requireApproval": false,
    "stakeholders": []
  }
}
```

Replace the example ID and endpoint with your collection's actual values. The
backend verifies collection membership and stamps source hashes. Creation
always sends `status: draft`. `--name` and `--audience` are an alternative to
`--from`, not overrides for it.

For field shaping, `endpointSchemas` entries use `collection`, `method`, `path`,
and `fields`. Fields use the existing contract shape: `name`, `path`, `location`
(`parameter`, `requestBody`, `response`), `type`, `included`, `required`, `pii`,
`internal`, and optional descriptions, examples, constraints and overrides.
For publishing, supply the same `publishing.platformConfigs` and governance
fields used by the web app. Provider credentials are configured in Elva and
never passed as CLI flags.

## Updating

You can send a sparse patch such as `{"description":"Revised partner API"}` or
edit a complete snapshot:

```bash
elva --json contract show "Partner API" > contract.json
elva --yes contract update "Partner API" --from contract.json
```

The CLI unwraps `contract`/`apiContract` response envelopes and omits their status
metadata, so saving a published snapshot does not publish it again or make it a
draft. A raw write with `status: active` is rejected; use `contract publish`.
The backend strips server-owned fields such as approval decisions, source
hashes and version bookkeeping.

## Syncing reviewed source changes

`contract sync` applies an explicitly reviewed change set using the existing
sync API. It does not independently choose endpoint/field merges. For example,
after reviewing a newly added endpoint:

```json
{
  "changes": [{"kind":"drift", "message":"Added users health endpoint"}],
  "collections": [{
    "collection":"0123456789abcdef01234567",
    "collectionName":"Users",
    "endpoints":[{"method":"GET","path":"/users"},{"method":"GET","path":"/users/health"}],
    "sourceEndpoints":[{"method":"GET","path":"/users"},{"method":"GET","path":"/users/health"}]
  }],
  "refreshedCollections":["0123456789abcdef01234567"],
  "dismissedAlerts":[]
}
```

Include the full desired selection in `collections`. Include `endpointSchemas`
when resolving field drift; otherwise existing field snapshots remain. Only
list source collections whose drift is fully resolved in `refreshedCollections`;
omitting it or supplying an empty list means all existing sources under the
backend's legacy behavior. Sync accumulates pending changes and can invalidate
approval; it does not publish a release.

## Decisions and publishing

`approve` and `reject` call the dedicated approval endpoint. Being an admin is
not a substitute for being an assigned approver. Publishing obeys the current
approval fingerprint and breaking-change policy. `contract publish` reports
each configured destination as published, unchanged, skipped or failed. A
nonzero exit after partial publication is not a rollback.

The contract list/show JSON is the backend's current contract representation.
It includes drift, source-missing flags, governance and release history so CI
can inspect these before applying or publishing changes.
