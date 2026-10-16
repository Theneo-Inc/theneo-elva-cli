"""A lazy, invocation-scoped HTTP timeout shared by all transports."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_provider: ContextVar[Callable[[], float] | None] = ContextVar("elva_timeout", default=None)


@contextmanager
def use_timeout(provider: Callable[[], float]) -> Iterator[None]:
    """Resolve settings only on a request; config repair must work without them."""
    token = _provider.set(provider)
    try:
        yield
    finally:
        _provider.reset(token)


def request_timeout(fallback: float) -> float:
    provider = _provider.get()
    return provider() if provider is not None else fallback
