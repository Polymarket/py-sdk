"""Package version helpers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polymarket-client")
except PackageNotFoundError:
    __version__ = "1.0.0"
