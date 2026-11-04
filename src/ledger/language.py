"""Commercial-language denylist for the ledger API surface."""

from __future__ import annotations

import re

# Word-boundary phrases. The ledger surface must fail closed if any appear
# in a response or in user-facing copy owned by this package.
FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bedge\b", re.IGNORECASE), "edge"),
    (re.compile(r"\+EV\b", re.IGNORECASE), "+EV"),
    (re.compile(r"value bet", re.IGNORECASE), "value bet"),
    (re.compile(r"\blean\b", re.IGNORECASE), "lean"),
    (re.compile(r"\block\b", re.IGNORECASE), "lock"),
    (re.compile(r"best bet", re.IGNORECASE), "best bet"),
    (re.compile(r"\brecommended\b", re.IGNORECASE), "recommended"),
    (re.compile(r"\bguaranteed\b", re.IGNORECASE), "guaranteed"),
    (re.compile(r"\bsnipe\b", re.IGNORECASE), "snipe"),
    (re.compile(r"act now", re.IGNORECASE), "act now"),
    (re.compile(r"bet now", re.IGNORECASE), "bet now"),
    (re.compile(r"cash out", re.IGNORECASE), "cash out"),
    (re.compile(r"\bhedge\b", re.IGNORECASE), "hedge"),
    (re.compile(r"stake sizing", re.IGNORECASE), "stake sizing"),
)


def find_forbidden(text: str) -> list[str]:
    found: list[str] = []
    for pattern, label in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found
