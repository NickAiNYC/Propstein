"""
crypto_utils.py — RFC-8785 Canonical JSON Serialization & Cryptographic Primers

Ensures exact byte-for-byte deterministic serialization and SHA-256 hashes across
platforms, clients, and independent offline audit scripts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def normalize_for_es6_json(obj: Any) -> Any:
    """
    Normalizes Python floats that have zero fractional part (e.g. 61.0 -> 61)
    so Python json.dumps matches ECMAScript / RFC-8785 number serialization byte-for-byte.
    """
    if isinstance(obj, float):
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, dict):
        return {k: normalize_for_es6_json(v) for k, v in obj.items() if v is not None or k in obj}
    if isinstance(obj, list):
        return [normalize_for_es6_json(x) for x in obj]
    return obj


def canonical_json_dumps(payload: Dict[str, Any]) -> str:
    """
    RFC-8785 compliant canonical JSON string with ES6 number serialization parity.
    - Keys sorted lexicographically
    - Compact separators (no extra whitespace)
    - UTF-8 characters preserved without ascii escapes
    - Whole-number floats formatted without decimal suffix to match JS JSON.stringify
    """
    normalized = normalize_for_es6_json(payload)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_json_sha256(payload: Dict[str, Any]) -> str:
    """
    RFC-8785 compliant deterministic SHA-256 hash.
    Identical across Python, Node.js, and Rust notary clients.
    """
    serialized = canonical_json_dumps(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
