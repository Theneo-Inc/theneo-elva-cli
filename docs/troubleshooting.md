# Troubleshooting

Check `elva --version`, command-specific `--help`, `elva config list`, and, when
signed in, `elva whoami` and `elva workspace list`. Redact credentials before sharing.

| Symptom | Check |
|---|---|
| Unknown command | Installed version may precede these source-preview features. |
| Agent does not choose Elva | Install the skill, reload the client, and explicitly mention Elva if needed. |
| Email not received | Confirm address and delivery configuration; respect retry/rate limits. |
| Verification fails | Use matching session/code in the initiating CLI profile; expired sessions need restart. |
| Signup interrupted | Use `auth resume SESSION_ID` and retain the saved artifact. |
| Login appears unchanged | `ELVA_TOKEN` overrides saved login; remove it from the relevant process without exposing its value. |
| API origin mismatch | Sign in to the intended target; newly saved credentials are origin-bound. |
| Wrong workspace | List workspaces and switch explicitly; backend membership and PAT scope still apply. |
| Existing account has no active workspace | Workspace repair is needed; sign-in does not grant another trial automatically. |
| Artifact rejected | Use offline `agent validate`; correct schema/host/auth and keep secrets out. |
| Draft has no endpoint | Publish through the contract's governance flow. |
| Published URL cannot call upstream | Verify host/auth and an authorized MCP handshake/tool call. |

See [email signup](email-signup.md), [agent recovery](agent-interface.md) and
[exit codes](exit-codes.md). Include the CLI version, command, exit code, redacted
error and a synthetic reproduction in bug reports.
