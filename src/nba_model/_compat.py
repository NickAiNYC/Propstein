"""Bridge to PropWire's shared trust primitives (src/crypto_utils.py).

The repo's convention is "src/ is on sys.path, import modules flat"
(see freeze_slate.py, tests/test_provenance.py). nba_model keeps that
convention but centralizes the lookup here so exactly one module knows
how the bridge works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]


def crypto_utils():
    """Return the shared crypto_utils module (RFC-8785 canonical JSON + SHA-256)."""
    try:
        import crypto_utils  # noqa: F401  (repo convention: src on sys.path)
        return sys.modules["crypto_utils"]
    except ImportError:
        pass
    if str(_SRC_DIR) not in sys.path:
        sys.path.insert(0, str(_SRC_DIR))
    import crypto_utils
    return crypto_utils
