# Elva CLI

Turn your API repository into a hosted Model Context Protocol (MCP) server and an
API contract with your existing coding agent.

Describe the customer use case. Your agent finds relevant endpoints and fields,
generates OpenAPI, and uses Elva to create the collection, contract and MCP.
**You do not need to write the spec or connect GitHub for this workflow.**

> **Source preview:** these new workflows are not released together yet. Use the
> [checkout setup](CONTRIBUTING.md#setup) to try this branch. Registry installation
> installs the published version, which may have fewer commands. Check
> `elva --version` and `elva agent --help`. The matching backend is also required.

## Install

Requires Python 3.11 or newer for the Python package:

```bash
uv tool install elva-cli
elva --version
```

Alternatively use `pipx install elva-cli`. Upgrade with `uv tool upgrade elva-cli`
or `pipx upgrade elva-cli`. Standalone binaries and the shell installer are built
by the existing release workflow; see [release instructions](RELEASING.md).

## Ask your agent for a customer MCP

Read or share the [Elva agent skill (`SKILL.md`)](src/elva_cli/assets/elva-mcp/SKILL.md).
It teaches an agent to find endpoints, generate the spec, handle email signup,
and create the contract and MCP. Install the bundled skill, then reload your agent:

```bash
elva agent setup --target all --user
```

Use `--target claude` or `--target codex` for one client. Omit `--user` to install
only in the current API repository. Analysis uses your agent's existing tools and
AI provider; Elva does not launch another AI CLI or read its credentials.

Open your API repository in the agent and ask:

> Create and publish an MCP for external customers from this repository, with an
> API contract. Include customer order lookups, expose only the fields customers
> need, and exclude internal administration endpoints and internal notes.

The agent derives and validates the spec, then creates the Elva resources. It can
ask for missing context, such as the live API URL or authentication method.
Publication follows your workspace's approval rules.

**The result:** an API collection, API contract and MCP in Elva. Creation produces
drafts. Successful publication provides a connection endpoint; verify the published
MCP with authorized customer credentials before claiming runtime access works.

Skill installation enables discovery; automatic selection still depends on the
agent and context. If needed, explicitly ask it to use Elva. See the
[agent workflow](docs/agent-workflow.md) for the complete process.

## Sign up with only your email

The agent can start signup when needed, or you can run:

```bash
elva auth signup --email you@example.com
```

Enter the emailed code in the masked prompt. No first name, last name, company
or password is required. New accounts receive a default workspace; existing
accounts sign in to their existing workspaces. An agent with authorized mailbox
access can submit the code through stdin. Interrupted signup can resume without
repeating API analysis. See [email signup and recovery](docs/email-signup.md).

Browser sign-in remains available through `elva auth login`. The default workspace
is selected automatically; use `elva workspace list` or `elva workspace switch NAME`
when you need another one.

## What Elva receives

| Workflow | Data sent to Elva |
|---|---|
| Existing agent: `agent create` | Generated API definition and settings; no repository files. |
| Elva AI: root `--prompt` | Filtered local source snapshot, including eligible uncommitted files. |
| GitHub: `repo connect` / `repo sync` | Elva reads the connected remote branch. Unpushed changes are not scanned. |
| `insights review` | Supplied API document, including unauthenticated reviews. |

`agent schema` and `agent validate` work offline. Source analysis stays with your
agent and its configured provider; this does not mean its AI runs entirely on your
computer. See [data flow and privacy](docs/privacy.md).

## Documentation

| Task | Guide |
|---|---|
| Create a customer MCP using your agent | [Agent workflow](docs/agent-workflow.md) |
| Integrate an agent or CI | [JSON, discovery and recovery](docs/agent-interface.md) |
| Try the artifact offline | [Customer-orders example](examples/customer-orders/README.md) |
| Import specs, sync GitHub, inspect collections and insights | [Command guide](docs/commands.md) |
| Select contract fields and manage publication | [Contracts](docs/contracts.md) |
| Ask Elva AI to propose changes | [AI plans](docs/ai-plans.md) |
| Upload a local source snapshot to Elva AI | [Local source](docs/local-source.md) |
| Resolve errors | [Troubleshooting](docs/troubleshooting.md) |

Global flags precede the command: `elva --json --workspace Acme collection list`.
Use `elva --help`, command-specific `--help`, or `elva --json schema` for discovery.

## Project and support

- [Elva](https://getelva.ai) · [Documentation](docs/README.md) · [Changelog](CHANGELOG.md)
- [Issues](https://github.com/Theneo-Inc/theneo-elva-cli/issues) · [Private security reporting](SECURITY.md)
- [Contributing](CONTRIBUTING.md) · [Repository agent instructions](AGENTS.md) · [Releasing](RELEASING.md)
