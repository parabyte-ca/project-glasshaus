"""Single source of the running version (mirrors the repo-level VERSION file)."""

import os
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("glasshaus")
except PackageNotFoundError:  # pragma: no cover - running from a raw checkout
    __version__ = "0.0.0+unknown"

BUILD_SHA = os.getenv("GLASSHAUS_BUILD_SHA", "dev")
