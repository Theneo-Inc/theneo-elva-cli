"""The login flow's result type, kept apart from the flow itself.

elva_cli.ui.renderables.auth has to import this class at runtime (singledispatch
resolves the annotation when it registers the renderer). Keeping it here means
that import — and so `import elva_cli.ui.renderables`, which every rendered
command pulls in — does not drag in http.server / urllib / webbrowser.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoginResult:
    email: str
