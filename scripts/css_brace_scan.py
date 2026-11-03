#!/usr/bin/env python3
"""CSS brace-balance state-machine scan (Task 61 protocol, reused for v176).

Walks style.css ignoring braces inside strings/comments/url() tokens and
reports the running depth plus the line of any unmatched close. Used after
every structural CSS edit — the v174 dead-on-arrival bug class must never
ship again.
"""
from __future__ import annotations
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "viewer/style.css")
text = path.read_text(encoding="utf-8")

depth = 0
i = 0
line = 1
in_string = False
in_comment = False
errors = []
stack = []

while i < len(text):
    ch = text[i]
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if ch == "\n":
        line += 1
        i += 1
        continue
    if in_comment:
        if ch == "*" and nxt == "/":
            in_comment = False
            i += 2
            continue
        i += 1
        continue
    if in_string:
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            in_string = False
        i += 1
        continue
    if ch == "/" and nxt == "*":
        in_comment = True
        i += 2
        continue
    if ch == '"':
        in_string = True
        i += 1
        continue
    if ch == "u" and text[i:i+4] == "url(":
        # url(...) — skip to matching paren, braces inside are not structural
        j = i + 4
        while j < len(text) and text[j] != ")":
            j += 1
        i = j + 1
        continue
    if ch == "{":
        depth += 1
        stack.append(line)
        i += 1
        continue
    if ch == "}":
        depth -= 1
        if depth < 0:
            errors.append(f"line {line}: unmatched close brace (depth {depth})")
            depth = 0
        elif stack:
            stack.pop()
        i += 1
        continue
    i += 1

print(f"final depth: {depth}")
if stack:
    print("unclosed open braces at lines:", stack[:10])
if errors:
    print("ERRORS:")
    for e in errors:
        print("  -", e)
    sys.exit(1)
if depth != 0:
    sys.exit(1)
print("BALANCED")
