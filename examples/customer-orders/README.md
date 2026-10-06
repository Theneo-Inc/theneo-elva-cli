# Customer-orders artifact

A synthetic single-endpoint artifact for offline validation:

```bash
elva --json agent validate --from examples/customer-orders/artifact.json
```

No upload occurs. The API host is illustrative, not a live customer API. For real
creation, derive the spec from your repository, use the intended host/auth/audience,
and generate a fresh UUID requestId. Never include authentication values.
See [the agent workflow](../../docs/agent-workflow.md).
