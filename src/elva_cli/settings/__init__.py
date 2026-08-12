"""Configuration schema and precedence resolution.

Order, highest first: command flags, ELVA_* environment, project elva.toml, user
config.toml, defaults. Resolved once in the root callback and frozen onto the Ctx;
nothing downstream re-reads the environment or the filesystem."""
