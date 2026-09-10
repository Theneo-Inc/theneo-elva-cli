# Changelog

## Unreleased

### Added
- **Identify as a first-class refresh client (ELVA-200).** Every request now
  sends `X-Elva-Client: cli` and a `User-Agent: elva-cli/<version>`. The refresh
  and CLI-login exchanges carry the marker so the backend routes them on the
  body-token path and, once its compatibility flag is turned off, does not
  reject the CLI as an unmarked client.
- **Refresh-and-retry on 401.** An idempotent request (GET/HEAD) that returns
  401 on a token that looked valid now forces one refresh and retries once.
  Non-idempotent requests (the spec upload) are never auto-replayed.
- **Backoff on transient refresh failures.** A refresh that hits 429/5xx or a
  network error is retried with backoff (1s/2s/4s) before surfacing as a
  transient `ApiError` (exit 5); it never forces a re-login.

### Changed
- Refresh continues to happen proactively ~60s before the access token expires
  and to persist the rotated token atomically (temp file + rename, 0600) before
  the response is used — unchanged, but now covered by explicit tests.
- **`elva import spec --url` now fetches through Elva and uploads like a file.**
  The URL is fetched via Elva's `fetch-file` proxy (the same path the web app
  uses, so a spec host only Elva can reach still works), a JSON spec is stored
  as YAML to match a web-app import instead of one minified line, and `--name`
  now defaults from the fetched spec's `info.title`. `--dry-run --url` reports
  the real title/version/endpoint count/size, and a spec URL that 404s or times
  out is now a usage error (exit 2) rather than a late server rejection. Local
  `.json` files are converted to YAML on import for the same consistency.

### Compatibility
This version works with **both** the flagged and the unflagged backend:
- While the backend keeps `AUTH_ALLOW_BODY_REFRESH_TOKEN` on, unmarked body
  refreshes still work, so **older CLI versions keep working** too.
- Once the backend turns that flag off (this CLI version being the minimum
  supported), the server rejects unmarked and legacy ("family-less") refresh
  tokens with `401 REFRESH_TOKEN_LEGACY`. This CLI maps that to
  *"Your session has expired. Run `elva auth login` to sign in again."*
  (exit code 3). **Older CLI versions stop working at that point** and users
  must upgrade and re-login once.
