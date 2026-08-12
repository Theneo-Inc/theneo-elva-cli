"""Credentials and the login flow.

Token storage sits behind a Protocol (keyring, with a 0600 file fallback for
headless Linux and containers). ELVA_TOKEN overrides both in CI.

The browser handoff needs a /auth/cli endpoint on the JWT side of the backend.
The cookie-session auth used by the catalog and GitHub routes is deliberately
out of scope: a CLI has no cookie jar."""
