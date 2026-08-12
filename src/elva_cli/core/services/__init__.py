"""Use cases: one function per thing the CLI can do.

Each returns a frozen dataclass (a "Result"). Results are plain data and know
nothing about Rich; rendering happens in ui/renderables."""
