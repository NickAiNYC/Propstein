#!/usr/bin/env python3
"""v154 header-logo swap + version sweep.

Owner directive: DROPWIRE wordmark recolored (DROP white, WIRE lighter baby
blue) replaces the v153 PWIRE header art. Assets from
make_v154_dropwire_logo.py. This sweep wires them in and bumps every marker:
  - header imgs  propwire-logo-pwire[-light] -> propwire-logo-dropwire[-light]
  - buster       2026_v153 -> 2026_v154 (x5 shell refs per page + sw.js)
  - cache        propwire-v153-prod -> propwire-v154-prod
  - build-hash   2026-w8-v18 -> 2026-w8-v19
  - harness re-pins incl. v153's lockup envelope (new art aspect 3.763 vs
    pwire 4.609 -> rendered w 90.3px @ h24, bound 96 recalibrated to 86) and
    light-chip width (488px, bound 540 -> 440)
Books badges stay ?v=v152 (binaries unchanged). Old pwire slot PNGs are
removed once unreferenced. Idempotent.
"""
import os
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

LOGO_DARK = sub = None  # placeholder to keep linters quiet


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


LOGO_DARK = sub(r'/propwire-logo-pwire\.png\?v=[^"]*',
                '/propwire-logo-dropwire.png?v=2026_v154')
LOGO_LIGHT = sub(r'/propwire-logo-pwire-light\.png\?v=[^"]*',
                 '/propwire-logo-dropwire-light.png?v=2026_v154')

page_edits = [
    LOGO_DARK, LOGO_LIGHT,
    lit('?v=2026_v153', '?v=2026_v154', 5),
    lit('2026-w8-v18', '2026-w8-v19', 1),
]

sw_edits = [
    lit('propwire-v153-prod', 'propwire-v154-prod'),
    lit("'/propwire-logo-pwire.png?v=2026_v153',",
        "'/propwire-logo-dropwire.png?v=2026_v154',"),
    lit("'/propwire-logo-pwire-light.png?v=2026_v153',",
        "'/propwire-logo-dropwire-light.png?v=2026_v154',"),
    lit('?v=2026_v153', '?v=2026_v154', 3),
]

webmanifest_edits = [lit('?v=2026_v153', '?v=2026_v154', 4)]

seo_gen_edits = [lit('?v=2026_v153', '?v=2026_v154', 2)]

harness_edits = [
    lit('2026_v153', '2026_v154', 0),
    lit('2026-w8-v18', '2026-w8-v19', 0),
    lit('propwire-v153-prod', 'propwire-v154-prod', 0),
]

v153_harness_edits = harness_edits + [
    lit('propwire-logo-pwire', 'propwire-logo-dropwire', 0),
    lit('ll.w > 540', 'll.w > 440', 1),
    lit('vis.w >= 96', 'vis.w >= 86', 1),
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
    ('scripts/verify_v153_rebrand.mjs', v153_harness_edits, 'verify_v153_rebrand.mjs'),
]

# dead once pages + sw no longer reference them
DEAD_ASSETS = [
    'viewer/propwire-logo-pwire.png',
    'viewer/propwire-logo-pwire-light.png',
]


def main():
    for path, edits, label in JOBS:
        rep = apply(path, edits, label)
        changes = [(n, p) for ok, n, p in rep if n]
        print(f'{label}: {sum(n for n, _ in changes)} replacements')
        for n, p in changes:
            print(f'    {n:2d} x {p[:90]}')

    # ── remove dead pwire slot assets (only if truly unreferenced) ────────
    tracked = [str(p) for p, _, _ in JOBS]
    for rel in DEAD_ASSETS:
        refs = [t for t in tracked
                if 'propwire-logo-pwire' in (REPO / t).read_text()]
        if refs:
            print(f'keep {rel}: still referenced in {refs}')
            continue
        f = REPO / rel
        if f.exists():
            os.remove(f)
            print(f'removed dead asset {rel}')

    # ── residual stale-marker audit ────────────────────────────────────────
    stale = re.compile(r'2026_v153|2026-w8-v18|propwire-v153-prod'
                       r'|propwire-logo-pwire')
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
