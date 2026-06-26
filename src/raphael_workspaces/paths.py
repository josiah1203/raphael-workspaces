"""Platform data paths."""

from __future__ import annotations

import os
from pathlib import Path


def raphael_home() -> Path:
    return Path(os.environ.get("RAPHAEL_HOME", os.path.expanduser("~/.raphael")))
