lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy

test:
    uv run pytest

check: lint test
