# Email-only CLI signup

Sign up or sign in with an email and a one-time verification code. No first name,
last name, company name, password, browser form, or GitHub connection is required.
This requires the matching email-signup backend release and configured SMTP.

```bash
elva auth signup --email you@example.com
```

In an interactive terminal, enter the eight-digit code in the masked prompt.
Leave the prompt empty to finish later. The command verifies email ownership,
creates a new account and its default workspace when needed, then saves credentials
in the normal keyring or private file store. Existing verified accounts retain
their password and workspaces; an unverified preregistration password is removed.
The signup workspace name initially uses the email and can be changed later.

`auth register` is an alias. `auth login --email EMAIL` uses this same flow;
`auth login` without `--email` keeps browser sign-in/SSO available.

## Agents and interrupted sessions

Prepare the API artifact locally, then start signup:

```bash
elva --json auth signup --email you@example.com --continue-artifact sanitized.json
elva --json auth verify SESSION_ID --code-stdin
elva --json auth resume SESSION_ID
```

The verification command reads one code from stdin; do not place the code in the
command line or shell history. A human can instead run `elva auth verify SESSION_ID`
and use the masked prompt. An agent with previously authorized mailbox access can
read the matching code and supply stdin directly without another user action.
Otherwise the user completes email verification. A verification code never grants
access without the private proof retained by the initiating CLI profile.

JSON auth results use top-level `status`, `session_id`, `email`, `expires_at`,
`workspace_id`, `artifact_file`, `next_action` and `message`. A pending verification
is a successful request (exit 0), not a completed login. `processing` means account
provisioning is still running; `auth resume SESSION_ID --wait 30` can wait up to
60 seconds. Errors return `status: error`, a stable error `code`, `message`, `hint`
and `retryable`, as well as the usual nonzero exit code.

The code/session expires after 20 minutes and accepts at most eight attempts.
Repeating signup for the same email/server reuses its session and never resets the
code or attempt count. `--restart` requests a fresh session, subject to rate limits.
The server also limits start requests by IP and normalized email.

`--continue-artifact` stores only a local path and file hash alongside the private
session. It does not upload the artifact. After successful login, `next_action`
continues draft creation. If the artifact changed, it requests local validation
instead. Account creation never publishes an MCP; the subsequent authorized
artifact and contract workflow controls draft creation and publication.

A lost response or failure to save credentials can be recovered with `auth resume`.
The backend retains the same encrypted credential pair for at most ten minutes
(or the original session expiry, whichever comes first), until the CLI acknowledges
durable storage. Acknowledgement clears that cache. Cleanup retries verify the
stored account identity and terminate instead of looping. Logged-out or rotated
credentials cannot be recovered from the old server cache; sign in again.

Credentials from this flow are bound to their Elva API origin on reads, refreshes
and logout. `ELVA_TOKEN` still overrides saved credentials; when it is set, signup
withholds automatic continuation and explains that the override must be removed.
No credentials, code or verifier appear in normal JSON/text output. Session files
use private directory/file permissions and are removed after acknowledgement.
