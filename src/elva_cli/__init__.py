from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("elva-cli")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
