# Contributing to Elva CLI

Use GitHub issues for reproducible bugs and feature requests. Report vulnerabilities
privately using [SECURITY.md](SECURITY.md).

## Setup

Use Python 3.11 or newer. Clone the repository and check out the intended branch:

```bash
git clone https://github.com/Theneo-Inc/theneo-elva-cli.git
cd theneo-elva-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
elva --version
elva --help
```

In PowerShell, use `py -m venv .venv` and `.venv\Scripts\Activate.ps1`.
Alternatively, run `uv sync --locked --extra dev` and `uv run elva --help`.
When changing dependencies, run `uv lock`, review its diff and commit `uv.lock`
with `pyproject.toml`. Verify freshness with `uv lock --check`.

## Checks

Run focused tests while editing, then the complete checks before merging:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Plain `mypy` checks source and tests; `mypy src` does not match CI. CI also defines
Linux/macOS/Windows coverage for Python 3.11–3.13 and a clean-wheel/minimum-Typer
check. Record actual results; a configured matrix is not evidence that it passed.

Tests use synthetic data and isolated CLI profiles. Preserve that isolation.
Use real services, email, source upload or publication only in the user's authorized
scope and environment. Never include tokens or customer data in fixtures.

## Architecture

- `commands/`: Typer options and command orchestration.
- `core/services/`: service calls and typed results.
- `core/api/`: HTTP transport and API target resolution.
- `core/spec/`: API format detection and normalization.
- `core/agent_*.py`: artifact validation and skill installation.
- `auth/`: credentials, browser/email sessions and refresh.
- `settings/`: profiles, configuration and precedence.
- `ui/`: terminal output and prompts.
- `assets/elva-mcp/`: canonical installed skill.

These paths are under `src/elva_cli/`. Keep terminal I/O at the command/UI boundary
and expensive imports lazy. Every interactive input needs an unattended equivalent.
Preserve exit codes, JSON contracts, retry IDs and the distinction between drafts
and publication. Keep Python and backend artifact schemas aligned.

## Documentation and PRs

Keep the README focused on onboarding and detailed commands in `docs/`. Update help,
the relevant guide and changelog for public behavior changes. Maintain one canonical
skill in `src/elva_cli/assets/elva-mcp/`.

Validate examples offline and check relative links:

```bash
elva --json agent validate --from examples/customer-orders/artifact.json
```

The example is synthetic. Local validation, resource creation, publication, live
runtime access and native agent discovery are separate checks.

PRs should describe the problem, resulting behavior, validation and any backend
compatibility requirements. Do not edit generated `src/elva_cli/_version.py`.
See [AGENTS.md](AGENTS.md), [RELEASING.md](RELEASING.md) and
[repository readiness](docs/repository-readiness.md).
