"""Prompts that always have a non-interactive equivalent.

Every helper takes the flag value first. If it was supplied, no question is ever
asked. If it was not and there is no TTY, the result is a usage error rather than
a hang -- a CLI that blocks waiting for input in CI is the worst failure mode
there is.

These live in ui/ so that nothing under core/ can reach them.
"""
