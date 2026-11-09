"""Put this repo's backend and product-agent directories on ``sys.path``."""

from __future__ import annotations

import os
import sys

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.dirname(_EVAL_DIR)
PROJECT_ROOT = os.path.dirname(os.path.dirname(AGENTS_DIR))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")


def bootstrap() -> str:
    """Insert ``backend/`` and ``scripts/agents/`` at the front of ``sys.path``.

    Returns:
        Absolute path of the repository root. CSV resolution and the default
        report path hang off this directory, so the command does not depend
        on the caller's working directory.
    """
    for path in (BACKEND_DIR, AGENTS_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)
    return PROJECT_ROOT
