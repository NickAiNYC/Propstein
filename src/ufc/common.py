"""Pure helpers shared by the UFC pipeline (no network)."""
from __future__ import annotations

import math
import re
import unicodedata
from statistics import median
from typing import Iterable, Optional

HONESTY_LABEL = "NO EDGE · model unbacktested vs closing lines"


def norm_name(name: str) -> str:
    """Lowercase ASCII name with punctuation/suffixes removed."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", " ", s.lower())
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(toks)


def names_match(a: str, b: str) -> bool:
    """Exact normalized match, else same last name + same first initial."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta, tb = na.split(), nb.split()
    return ta[-1] == tb[-1] and ta[0][0] == tb[0][0]


def american_to_prob(odds: float) -> float:
    odds = float(odds)
    if odds >= 100:
        return 100.0 / (odds + 100.0)
    if odds <= -100:
        return -odds / (-odds + 100.0)
    raise ValueError(f"invalid American odds {odds}")


def prob_to_american(p: float) -> int:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def no_vig_two_way(a_odds: float, b_odds: float) -> tuple[float, float]:
    pa, pb = american_to_prob(a_odds), american_to_prob(b_odds)
    tot = pa + pb
    return pa / tot, pb / tot


def consensus(values: Iterable[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return float(median(vals)) if vals else None


def wilson(k: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))
