# Releasing Elva CLI

Release an exact reviewed tag. `hatch-vcs` derives the version from Git; do not edit
a version field or reuse a published version. Development/local versions are not
release artifacts.

## Before tagging

Finish [repository readiness](docs/repository-readiness.md). Confirm full CI passed
for the exact commit. The current release workflow builds and smoke-tests packages;
it does not itself require full CI. Preserve the existing standalone binary and
shell installer pipeline when changing the release workflow.

```bash
uv lock --check
uv sync --locked --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
uvx twine check dist/*
```

Regenerate and review `uv.lock` after dependency changes. Do not use frozen mode to
hide stale metadata. Install the wheel outside the checkout in a clean environment,
then run `scripts/smoke_wheel.py` using that environment's Python. Verify minimum
supported Typer, packaged skill/schema assets and source-archive docs/examples.

```bash
elva --json agent validate --from examples/customer-orders/artifact.json
```

## Feature acceptance

| Feature | Evidence |
|---|---|
| Email signup | Real delivery, saved login, default workspace, existing-account login and interrupted-flow recovery. |
| Existing agent | Local spec generation/validation, signup, create/retry/publish; no source or Elva AI calls. |
| Discovery | Install skill and reload actual clients; test without supplying the skill text. |
| Hosted MCP | Handshake/tool listing and authorized calls with intended endpoint/field visibility. |
| Repository sync | Connect a disposable GitHub repo, push a change, sync and inspect results. |
| Elva AI | Representative framework extraction and governed plan/recovery quality. |

Ship with matching backend capabilities and runtime contract enforcement. Apply
email-session/index migrations and configure SMTP. Record which checks use fixtures
versus real services; unit tests do not prove delivery, discovery or upstream access.
Update the changelog and source-preview notice when the workflow becomes available.

## Publish

A `vX.Y.Z` tag push triggers production publishing; do this only for an authorized
release after acceptance. The [workflow](.github/workflows/release.yml) builds and
checks distributions, publishes through PyPI Trusted Publishing, builds standalone
binaries, and uploads release assets. Confirm publisher/environment settings exist.
Manual dispatch targets TestPyPI and still requires an exact version tag; plan a
rehearsal that does not inadvertently trigger production publication.

After release, check `uvx --refresh --from elva-cli==X.Y.Z elva --version` and the
standalone installer from clean environments. Release notes should cover notable
changes, installation, backend requirements and known limitations.

For failed publishing, inspect the failing stage before retrying. Used versions
need a new version; assess yanking a broken release and publish a corrected version.
Maintain more than one authorized package owner. No publishing is performed by
editing this document or pushing a feature branch.
