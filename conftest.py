"""Suite defaults for API startup.

The process refuses to boot without an extension signing secret, and it will
try Redis when REDIS_URL is set. Tests get an explicit signing secret and the
in-memory store so lifespan startup stays local and deterministic.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _extension_runtime_defaults_for_tests():
    if not (os.environ.get("EXTENSION_SESSION_SECRET") or "").strip():
        os.environ["EXTENSION_SESSION_SECRET"] = "pytest-only-extension-session-secret"
    os.environ["EXTENSION_SESSION_STORE"] = "memory"
    yield
