"""Configuration schema and precedence resolution.

Order, highest first: command flags, ELVA_* environment, project elva.json,
the selected profile in the user config, user config, defaults. Resolved once in
the root callback and frozen onto the Ctx.
"""
