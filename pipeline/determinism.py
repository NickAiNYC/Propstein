"""PropStein pipeline — deterministic primitives.

Mirrors src/lib/domain/determinism.ts so that every stored number is
reproducible from a snapshot, a model version, a seed, and provenance
(the charter's definition of done). All arithmetic is 32-bit clean.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable

_MASK32 = 0xFFFFFFFF


def fnv1a(text: str) -> int:
    """FNV-1a 32-bit hash (ASCII keys — identical to the TS implementation)."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & _MASK32
    return h


def seed_from(*parts: Any) -> int:
    """Deterministic 32-bit seed from any tuple of parts."""
    return fnv1a("|".join(str(p) for p in parts))


def mulberry32(seed: int) -> Callable[[], float]:
    """mulberry32 PRNG — bit-for-bit parity with the TS implementation."""
    a = seed & _MASK32

    def rand() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _MASK32
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & _MASK32
        t = (((t + (((t ^ (t >> 7)) * (t | 61)) & _MASK32)) & _MASK32)) ^ t
        return ((t ^ (t >> 14)) & _MASK32) / 4294967296.0

    return rand


def gauss(rand: Callable[[], float]) -> float:
    """Standard normal draw from a uniform stream (Box–Muller)."""
    u = 0.0
    v = 0.0
    while u == 0.0:
        u = rand()
    while v == 0.0:
        v = rand()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


def normal_cdf(x: float) -> float:
    """Standard normal CDF via the exact erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number in canonical JSON")
        return round(value, 6)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value)}
    raise TypeError(f"unsupported canonical type: {type(value)!r}")


def canonical_json(value: Any) -> str:
    """Canonical JSON for hashing: sorted keys, no whitespace, 6-decimal floats."""
    return json.dumps(_canonicalize(value), separators=(",", ":"), ensure_ascii=False)


def snapshot_hash(record: Any) -> str:
    return sha256_hex(canonical_json(record))


def iso_utc(date_like: Any) -> str:
    """ISO-8601 UTC timestamp, second precision, trailing Z."""
    if isinstance(date_like, str):
        # normalize through datetime
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(date_like.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        date_like = parsed.astimezone(timezone.utc)
    return date_like.strftime("%Y-%m-%dT%H:%M:%SZ")
