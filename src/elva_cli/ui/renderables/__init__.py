"""Rich renderers for Result objects, dispatched on type.

Keeping the data to presentation mapping here is what stops --json from drifting
from human output: both start from the same dataclass.
"""

from __future__ import annotations

from elva_cli.ui.renderables import config as _config  # noqa: F401  registers renderers
from elva_cli.ui.renderables.base import render

__all__ = ["render"]
