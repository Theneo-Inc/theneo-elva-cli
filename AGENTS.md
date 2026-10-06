# Working on Elva CLI

This file guides changes to the CLI source. Agents consuming Elva should use the
[canonical skill](src/elva_cli/assets/elva-mcp/SKILL.md), installed by `elva agent setup`,
and the [agent interface](docs/agent-interface.md).

## Preserve behavior

Keep terminal I/O at the command/UI boundary and expensive imports lazy. Every
interactive input needs an unattended equivalent. Preserve stable JSON fields,
exit codes, retry IDs, and draft/publication separation. The existing-agent path
sends generated API artifacts; never silently switch it to source upload or Elva AI.
Use synthetic data and isolated profiles. Real services, email and publication
must stay within the user's authorized scope. Do not commit secrets or private data.

## Validate and document

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Run relevant tests; complete checks are
`ruff check .`, `ruff format --check .`, `mypy`, and `pytest`. Check changed examples
and links. Align `uv.lock` after dependency changes. Update help, guides and changelog
for public behavior changes. Keep the bundled skill canonical and include required
assets in distributions. Do not edit generated `_version.py`. Report actual checks
and distinguish fixtures from production, runtime and native-agent validation.
