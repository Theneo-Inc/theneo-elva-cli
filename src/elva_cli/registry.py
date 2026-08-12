"""Lazy command dispatch.

Maps command name to module path so that the command a user typed is the only
command module imported. Declaring a command here is the only way to add one, so
the startup cost of the tree stays visible in one file."""
