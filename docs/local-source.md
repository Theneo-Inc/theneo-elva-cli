# Local source to MCP and API contract

Run `elva --prompt "Find external customer endpoints and create an MCP"` from the
API checkout after signing in to Elva. The command scans the current working tree;
it does not require a Git remote, a GitHub connection, or a prebuilt specification.
No build scripts, package installers or repository hooks run. This workflow uses
Elva's hosted AI, so source leaves your machine after the upload confirmation.
`--yes` accepts that upload and the subsequent reviewed draft creation.

## What is sent

The default is the closest Git checkout root, or the current directory outside
Git. `--path` narrows the source directory. Git ignore rules (including global and
repository-local excludes) and `.elvaignore` rules are applied independently.
An include rule in `.gitignore` cannot override an `.elvaignore` exclusion.
Parent rules within the checkout/current project apply when choosing a subfolder.

Dotfiles, symlinks, common dependencies, build output, test fixtures and secret
files are excluded. Only supported source/manifest/configuration file types are
sent. Common embedded credentials, private keys and token patterns are redacted.
Redaction is heuristic; use `.elvaignore` to exclude confidential files and do not
assume that every possible secret format can be recognized. No remote URL,
Git credential or raw source is written into the saved review plan.

Limits: 500 files, 4 MiB total UTF-8 source, 256 KiB per file, 400 discovered routes
and 50 detected services. The encoded upload is separately bounded. Narrow
`--path` or add `.elvaignore` instead of accepting a silently truncated snapshot.

The server writes files into a private temporary directory, validates paths,
reapplies redaction, then removes that directory when the scan completes or fails.
Generated specifications and imported collections remain in Elva. Saved plans
contain endpoint schemas and examples and should be handled as project data.
A server-process crash may leave a temporary directory for normal OS cleanup.

## Pipeline and review

Elva runs its static route analyzers, AI fallback extraction, request-body type
extraction and AI response-schema inference. It generates OpenAPI collections,
then uses the grounded contract planner to select endpoints and fields. The plan
records the filtered source digest, file count and available Git revision metadata.

The audience is inferred from clear customer/partner/public/internal wording;
otherwise a terminal prompt asks, or CI must supply `--audience`. This is a
convenience inference and is displayed for review. A live `--api-base-url` is
required if the source does not establish a single URL. All tools in one plan use
that upstream; narrow to one API service if a monorepo has different API hosts.

Bearer authentication is the default. Set `--auth-type api_key` with an optional
`--api-key-header`, or explicitly use `--auth-type none` for a public upstream.
Review these settings and the exact endpoint/field choices before publication.
API credentials and the upstream API must enforce customer data isolation; a
contract limits tools and fields, but does not implement tenant authorization.

The result creates drafts. `elva contract publish CONTRACT_ID` publishes through
existing approvals and breaking-change policies. AI schema inference is a proposal,
not proof that every dynamic route or conditional response has been found. The
scanner's supported frameworks, inference budgets and route heuristics still apply.
A representative live-AI evaluation is required before claiming repository-wide
endpoint completeness or production quality across frameworks.

## Automation and recovery

Discover flags with `elva --json schema`. Supply `--yes --json --prompt`, and use
explicit audience, URL and authentication when known. Successful stdout is one
JSON result; review/progress/errors go to stderr. Exit codes retain existing CLI
semantics. Missing input includes `ELVA_INPUT_REQUIRED` and a resume command;
errors are currently text on stderr even under `--json`.

`elva --resume JOB_ID` waits for a running job, supplies a missing URL, or retries
failed planning from existing collections. An explicit replacement URL is accepted
when retrying failed planning. It preserves source, name, audience and auth settings.
A source scan failure without stored collections needs a new upload; it cannot be
resumed from source because the server does not persist raw source in the job.
After draft-application errors, use the printed plan file with `elva apply FILE`.
Job POST submission itself is not idempotent if the initial response is lost;
once the job ID is known, reuse it rather than issuing another prompt.

Installing the CLI alone does not cause arbitrary agents to discover or prefer it.
Teams must expose Elva in their agent tool setup/instructions or a supported plugin.
This entry point makes the execution path available once the agent knows Elva.
