#!/usr/bin/env python3
"""v153 rebrand version sweep.

Wires the v153 brand assets into the live shell and bumps every version
marker per the repo convention:
  - buster      2026_v153  (x5 shell refs per page + sw.js precache)
  - legacy refs ?v=v149 / ?v=2026_v1 / stale ledger 2026_v148 -> 2026_v153
  - cache       propwire-v153-prod
  - build-hash  2026-w8-v18
  - header logo imgs -> propwire-logo-pwire[-light].png (PWIRE art)
Books badges stay ?v=v152 (binaries unchanged this version). Idempotent.
"""
import re
from pathlib import Path

REPO = Path('/home/z/my-project/propwire')

PAGES = [
    'viewer/index.html',
    'viewer/audit.html',
    'viewer/verify.html',
    'viewer/ledger.html',
    'viewer/ledger/index.html',
]

# (file, list of (pattern, replacement, expected_min_count))
EDITS = []


def apply(path, edits, label):
    p = REPO / path
    src = p.read_text()
    out = src
    report = []
    for pat, rep, minc in edits:
        if isinstance(pat, str):
            n = out.count(pat)
            out = out.replace(pat, rep)
        else:
            out, n = pat.subn(rep, out)
        ok = n >= minc
        report.append((ok, n, pat if isinstance(pat, str) else pat.pattern))
        if not ok:
            print(f'  !! {label}: expected >={minc} of {pat!r}, got {n}')
    p.write_text(out)
    return report


def sub(pattern, repl, minc=1):
    return (re.compile(pattern), repl, minc)


def lit(old, new, minc=1):
    return (old, new, minc)


LOGO_DARK = sub(r'/propwire-logo\.svg\?v=[^"]*',
                '/propwire-logo-pwire.png?v=2026_v153')
LOGO_LIGHT = sub(r'/propwire-logo-dark\.svg\?v=[^"]*',
                 '/propwire-logo-pwire-light.png?v=2026_v153')
OG = lit('og-image.png?v=2026_v1"', 'og-image.png?v=2026_v153"', 2)

page_edits = [
    LOGO_DARK, LOGO_LIGHT,
    lit('?v=v149', '?v=2026_v153', 8),
    OG,
    lit('2026_v152', '2026_v153', 5),
    lit('2026_v148', '2026_v153', 0),      # ledger/index.html stale busters
    lit('2026-w8-v17', '2026-w8-v18', 1),
]

sw_edits = [
    lit('propwire-v152-prod', 'propwire-v153-prod'),
    lit("'/propwire-logo.svg?v=2026_v152',", "'/propwire-logo-pwire.png?v=2026_v153',"),
    lit("'/propwire-logo-dark.svg?v=2026_v152',", "'/propwire-logo-pwire-light.png?v=2026_v153',"),
    lit('?v=v149', '?v=2026_v153', 5),
    lit('2026_v152', '2026_v153', 5),
]

webmanifest_edits = [lit('?v=v149', '?v=2026_v153', 4)]

seo_gen_edits = [lit('?v=v149', '?v=2026_v153', 2)]

harness_edits = [
    lit('?v=v149', '?v=2026_v153', 0),
    lit('2026_v152', '2026_v153', 0),
    lit('2026-w8-v17', '2026-w8-v18', 0),
    lit('propwire-v152-prod', 'propwire-v153-prod', 0),
]

JOBS = [
    *[(p, page_edits, p) for p in PAGES],
    ('viewer/sw.js', sw_edits, 'sw.js'),
    ('viewer/site.webmanifest', webmanifest_edits, 'site.webmanifest'),
    ('scripts/build_public_pages.py', seo_gen_edits, 'build_public_pages.py'),
    ('scripts/verify_v149_ios.mjs', harness_edits, 'verify_v149_ios.mjs'),
    ('scripts/verify_v150_csp.mjs', harness_edits, 'verify_v150_csp.mjs'),
    ('scripts/verify_v151_autopilot.mjs', harness_edits, 'verify_v151_autopilot.mjs'),
    ('scripts/verify_v152_books.mjs', harness_edits, 'verify_v152_books.mjs'),
]


def main():
    for path, edits, label in JOBS:
        rep = apply(path, edits, label)
        changes = [(n, p) for ok, n, p in rep if n]
        print(f'{label}: {sum(n for n, _ in changes)} replacements')
        for n, p in changes:
            print(f'    {n:2d} x {p[:90]}')

    # ── residual stale-marker audit ────────────────────────────────────────
    stale = re.compile(r'\?v=v149|2026_v148|2026_v152|2026-w8-v17'
                       r'|propwire-logo\.svg\?v|propwire-logo-dark\.svg\?v'
                       r'|propwire-v152-prod')
    bad = []
    for path, _, _ in JOBS:
        text = (REPO / path).read_text()
        for i, line in enumerate(text.splitlines(), 1):
            if stale.search(line) and 'books/' not in line and '?v=v152' not in line:
                bad.append(f'{path}:{i}: {line.strip()[:110]}')
    if bad:
        print('\nSTALE MARKERS REMAIN:')
        for b in bad:
            print('  ', b)
        raise SystemExit(1)
    print('\nsweep clean: zero stale markers across all touched files')


if __name__ == '__main__':
    main()
