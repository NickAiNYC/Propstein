#!/usr/bin/env python3
"""v154 merge resolver — re-apply owner-directed brand wiring onto the
invariant redesign pages (merge origin/main -> feat/v153-pwire-rebrand).

Pages were resolved --theirs (2027 redesign structure). This re-applies:
  - header logo srcs -> dropwire pair @ v154 (owner directive: white DROP /
    lighter baby blue WIRE — supersedes invariant's white-cyan SVG swap)
  - busters           ?v=2026_v153 (independent identical counter) -> v154
                      ?v=v149 stragglers -> v154
  - og/twitter        stale ?v=2026_v1 -> v154
  - build-hash        stale 2026-w8-v16 -> 2026-w8-v19
Books badges stay ?v=v152 (binaries unchanged). Idempotent; fails loudly
on any residual stale marker.
"""
import re
from pathlib import Path

REPO = Path('/home/z/my-project/propwire')

PAGES = [
    'viewer/index.html',
    'viewer/audit.html',
    'viewer/verify.html',
    'viewer/ledger.html',
]

EDITS = [
    (re.compile(r'/propwire-logo\.svg\?v=[^"]*'),
     '/propwire-logo-dropwire.png?v=2026_v154', 1),
    (re.compile(r'/propwire-logo-dark\.svg\?v=[^"]*'),
     '/propwire-logo-dropwire-light.png?v=2026_v154', 1),
    ('og-image.png?v=2026_v1"', 'og-image.png?v=2026_v154"', 2),
    ('?v=2026_v153', '?v=2026_v154', 3),
    ('?v=v149', '?v=2026_v154', 0),
    ('2026-w8-v16', '2026-w8-v19', 1),
]

STALE = re.compile(r'propwire-logo\.svg|propwire-logo-dark\.svg'
                   r'|2026_v153|2026-w8-v16|\?v=v149'
                   r'|og-image\.png\?v=2026_v1"')


def main():
    bad = []
    for rel in PAGES:
        p = REPO / rel
        src = p.read_text()
        out = src
        print(f'{rel}:')
        for pat, rep, minc in EDITS:
            if isinstance(pat, str):
                n = out.count(pat)
                out = out.replace(pat, rep)
            else:
                out, n = pat.subn(rep, out)
            flag = '' if n >= minc else f'  !! expected >={minc}'
            print(f'    {n:2d} x {pat if isinstance(pat, str) else pat.pattern}{flag}')
        p.write_text(out)
        for i, line in enumerate(out.splitlines(), 1):
            if STALE.search(line) and 'books/' not in line and '?v=v152' not in line:
                bad.append(f'{rel}:{i}: {line.strip()[:110]}')
    if bad:
        print('\nSTALE MARKERS REMAIN:')
        for b in bad:
            print('  ', b)
        raise SystemExit(1)
    print('\nresolver clean: zero stale markers across the 4 pages')


if __name__ == '__main__':
    main()
