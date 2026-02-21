"""Platform detection and helpers."""

from __future__ import annotations

import os
import sys


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland"


def is_x11() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "x11" or "DISPLAY" in os.environ
