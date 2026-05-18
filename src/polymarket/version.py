"""Package version helpers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polymarket-sdk")
except PackageNotFoundError:
    __version__ = "0.2.0"
