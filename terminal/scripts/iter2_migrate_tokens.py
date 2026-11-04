#!/usr/bin/env python3
"""Iteration 2 · Task 1 — Production token port for viewer/style.css.

1. Replaces the leading :root block with the canonical PropStein 2027 (PR-1)
   token set: --ps-* canonical names + every legacy alias remapped onto them.
2. Strips custom-property declarations from the four legacy :root override
   layers (the v145–v179 rebrand strata) so there is exactly ONE source of
   truth; their component rules are preserved untouched.
3. Sweeps legacy hardcoded palette literals (hex + rgb triplets) to the
   canonical values so !important rules cannot fight the token layer.

Idempotent: run twice, second run replaces nothing.
Only colors migrate. Geometry (radius, spacing, fonts, shadows, layout)
resolves to the values the final cascade produced before this change.
"""
import json
import re
import sys

CSS_PATH = "/home/z/my-project/propstein-src/viewer/style.css"
REPORT_PATH = "/home/z/my-project/scripts/iter2_token_report.json"

CANONICAL = """:root {
  color-scheme: dark;
  /* ══════════════════════════════════════════════════════════════════════
     PROPSTEIN 2027 DESIGN TOKENS (PR-1) — one source of truth
     Graphite research terminal · sapphire accent. Canonical names are the
     --ps-* set. Every legacy alias below resolves onto the same values so
     the existing rule base inherits the palette without per-rule edits.
     ══════════════════════════════════════════════════════════════════════ */

  /* — canonical palette — */
  --ps-canvas: #0B0D11;            /* graphite canvas */
  --ps-workspace: #10141B;         /* deep graphite workspace */
  --ps-panel: #151B23;             /* charcoal surface — cards, panels */
  --ps-elevated: #1C2530;          /* elevated graphite — sheets, controls */
  --ps-nav: #151B23;               /* navigation band matches panels */
  --ps-workscreen: #1A2230;        /* hover / active row surface */
  --ps-border: #303948;            /* structural border */
  --ps-border-soft: #232B38;       /* quieter inner hairline */
  --ps-sapphire: #38BDF8;          /* sapphire primary accent */
  --ps-sapphire-hover: #7DD3FC;    /* soft sapphire — emphasis, active */
  --ps-sapphire-surface: #102B3B;  /* subtle selected surface */
  --ps-mint: #D8FFC5;              /* secondary model reference markers */
  --ps-caution: #F5B86B;           /* caution amber — uncertainty, warnings */
  --ps-danger: #F87171;            /* true error / rejection only */
  --ps-text: #F3F4F6;              /* main text */
  --ps-text-muted: #A2ADBC;        /* secondary text */

  /* — evidence status vocabulary (fail-closed, never decorative) — */
  --status-verified: #7EE2A8;
  --status-observed: var(--ps-caution);
  --status-model: var(--ps-text-muted);
  --status-stale: #F0A05A;
  --status-archived: #8B96A8;
  --status-unavailable: #6B7686;

  /* — legacy semantic names → canonical values — */
  --bg-app: var(--ps-canvas);
  --bg-app-raised: var(--ps-elevated);
  --bg-card: var(--ps-panel);
  --bg-card-hover: var(--ps-workscreen);
  --border-subtle: var(--ps-border);
  --text-main: var(--ps-text);
  --text-muted-2: var(--ps-text-muted);
  --accent-primary: var(--ps-sapphire);
  --accent-primary-hover: var(--ps-sapphire-hover);
  --accent-primary-bright: var(--ps-sapphire);
  --accent-cyan: var(--ps-sapphire);
  --accent-success: #10B981;       /* profit / edge emerald — unchanged */
  --accent-warning: var(--ps-caution);
  --accent-surface: var(--ps-sapphire-surface);

  --bg-canvas: var(--ps-canvas);
  --bg-surface: var(--ps-panel);
  --bg-elevated: var(--ps-elevated);
  --border-hairline: var(--ps-border);

  --brand-accent: var(--ps-sapphire);
  --brand-accent-bright: var(--ps-sapphire-hover);
  --brand-accent-dim: var(--ps-sapphire-surface);
  --brand-accent-border: var(--ps-sapphire);
  --brand-accent-glow: transparent;
  --brand-blue: var(--ps-sapphire);
  --brand-blue-muted: rgba(56, 189, 248, 0.12);
  --brand-blue-border: rgba(56, 189, 248, 0.28);

  --baby-blue: var(--ps-sapphire);
  --baby-blue-bright: var(--ps-sapphire-hover);
  --baby-blue-ring: var(--ps-sapphire);
  --baby-blue-glow: transparent;

  --warn-amber: var(--ps-caution);
  --under-cyan: var(--ps-sapphire);
  --text-primary: var(--ps-text);
  --text-secondary: var(--ps-text-muted);
  --text-muted: var(--ps-text-muted);

  --bg: var(--ps-canvas);
  --surface: var(--ps-panel);
  --surface-2: var(--ps-panel);
  --surface-3: var(--ps-workscreen);
  --surface-row-hover: var(--ps-workscreen);
  --text: var(--ps-text);
  --text-dim: var(--ps-text-muted);
  --muted: var(--ps-text-muted);
  --faint: #64748B;
  --line: var(--ps-border);
  --line-strong: #3D4A5E;
  --accent: var(--ps-sapphire);
  --accent-ink: #0B0D11;
  --amber: var(--ps-caution);
  --amber-bg: rgba(245, 184, 107, 0.08);
  --danger: var(--ps-danger);

  /* — geometry & type: unchanged (resolves as before this migration) — */
  --radius: 4px;
  --radius-sm: 2px;
  --radius-lg: 4px;
  --radius-pill: 999px;
  --edge-hi: none;
  --shadow-sm: none;
  --shadow-md: none;
  --shadow: 0 16px 40px -24px rgba(0, 0, 0, 0.85);
  --font-display: 'Space Grotesk', 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif;
  --mono: 'JetBrains Mono', 'SF Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace;
  --sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* — pw-* chrome names → canonical — */
  --pw-bg-deep: var(--ps-canvas);
  --pw-bg-bar: var(--ps-canvas);
  --pw-bg-control: var(--ps-elevated);
  --pw-bg-canvas: var(--ps-canvas);
  --pw-bg-card: var(--ps-panel);
  --pw-bg-card-hover: var(--ps-workscreen);
  --pw-bg-inset: var(--ps-canvas);
  --pw-bg-elevated: var(--ps-elevated);
  --pw-bg-surface: var(--ps-panel);
  --pw-border: var(--ps-border);
  --pw-border-hairline: var(--ps-border-soft);
  --pw-border-subtle: var(--ps-border);
  --pw-border-active: rgba(56, 189, 248, 0.4);
  --pw-text-primary: var(--ps-text);
  --pw-text-secondary: var(--ps-text-muted);
  --pw-text-muted: var(--ps-text-muted);
  --pw-accent: var(--ps-sapphire);
  --pw-accent-bright: var(--ps-sapphire-hover);
  --pw-accent-dim: var(--ps-sapphire-surface);
  --pw-accent-border: var(--ps-sapphire);
  --pw-accent-blue: var(--ps-sapphire);
  --pw-accent-blue-subtle: rgba(56, 189, 248, 0.12);
  --pw-accent-lime: var(--ps-sapphire);
  --pw-state-active: #4ade80;
  --pw-state-active-bg: rgba(74, 222, 128, 0.12);
  --pw-state-verify: var(--ps-caution);
  --pw-state-verify-bg: rgba(245, 184, 107, 0.14);
  --pw-state-subgate: var(--ps-text-muted);
  --pw-state-negative: var(--ps-danger);
  --pw-font-sans: var(--sans);
  --pw-font-mono: var(--mono);
}"""

# hex literal sweep (case-insensitive) — legacy rebrand palette → canonical
HEX_MAP = {
    "#0b0e14": "#0B0D11", "#0f131a": "#0B0D11", "#070B14": "#0B0D11",
    "#080b0f": "#0B0D11",
    "#11141B": "#151B23", "#111620": "#151B23", "#141a23": "#151B23",
    "#131a24": "#151B23",
    "#171B24": "#1A2230", "#171f2c": "#1A2230", "#1a212d": "#1A2230",
    "#1c2432": "#1C2530", "#161c28": "#1C2530", "#161d2c": "#1C2530",
    "#222733": "#303948", "#232c3b": "#303948", "#273244": "#303948",
    "#293240": "#303948",
    "#2d3a4d": "#3D4A5E",
    "#80c6f6": "#38BDF8", "#b7e5ff": "#7DD3FC", "#4BA3F5": "#38BDF8",
    "#8b949e": "#A2ADBC", "#94a3b8": "#A2ADBC", "#9CA3AF": "#A2ADBC",
    "#d9a441": "#F5B86B", "#f5b455": "#F5B86B", "#F59E0B": "#F5B86B",
    "#b4535a": "#F87171",
    "#0C2538": "#102B3B",
}

# rgb() triplet sweep inside rgba?()/rgb()
RGB_MAP = {
    (11, 14, 20): (11, 13, 17), (15, 19, 26): (11, 13, 17),
    (7, 11, 20): (11, 13, 17), (8, 11, 15): (11, 13, 17),
    (17, 20, 27): (21, 27, 35), (20, 26, 35): (21, 27, 35),
    (17, 22, 32): (21, 27, 35),
    (23, 27, 36): (26, 34, 48), (22, 31, 44): (26, 34, 48),
    (26, 33, 45): (26, 34, 48),
    (28, 36, 50): (28, 37, 48), (22, 28, 40): (28, 37, 48),
    (34, 39, 51): (48, 57, 72), (35, 44, 59): (48, 57, 72),
    (41, 50, 64): (48, 57, 72), (39, 58, 77): (48, 57, 72),
    (45, 58, 77): (61, 74, 94),
    (128, 198, 246): (56, 189, 248), (183, 229, 255): (125, 211, 252),
    (75, 163, 245): (56, 189, 248),
    (139, 148, 158): (162, 173, 188), (148, 163, 184): (162, 173, 188),
    (156, 163, 175): (162, 173, 188),
    (217, 164, 65): (245, 184, 107), (245, 158, 11): (245, 184, 107),
    (245, 180, 85): (245, 184, 107),
    (180, 83, 90): (248, 113, 113),
    (12, 37, 56): (16, 43, 59),
}

DECL_RE = re.compile(r"^\s*--[A-Za-z0-9-]+\s*:[^;]*;?\s*$")
ROOT_RE = re.compile(r":root\s*\{[^{}]*\}", re.DOTALL)


def main():
    css = open(CSS_PATH).read()
    report = {"root_blocks_seen": 0, "declarations_stripped": 0,
              "blocks_removed": 0, "hex_replacements": {}, "rgb_replacements": {}}

    blocks = list(ROOT_RE.finditer(css))
    report["root_blocks_seen"] = len(blocks)
    if not blocks:
        sys.exit("no :root blocks found — aborting")

    out, cursor = [], 0
    for i, m in enumerate(blocks):
        out.append(css[cursor:m.start()])
        body = m.group(0)
        if i == 0:
            # leading block → canonical token layer (idempotence guard:
            # skip if it is already the canonical block)
            if "--ps-canvas" not in body:
                out.append(CANONICAL)
            else:
                out.append(body)
        else:
            inner = body[body.index("{") + 1:body.rindex("}")]
            kept = [ln for ln in inner.split("\n") if not DECL_RE.match(ln)]
            kept_text = "\n".join(kept).strip()
            n_decl = len([ln for ln in inner.split("\n") if DECL_RE.match(ln)])
            report["declarations_stripped"] += n_decl
            if kept_text:
                out.append(":root {" + kept_text + "\n}")
            else:
                report["blocks_removed"] += 1
        cursor = m.end()
    out.append(css[cursor:])
    css = "".join(out)

    # hex sweep
    for src, dst in HEX_MAP.items():
        n = len(re.findall(src, css, re.IGNORECASE))
        if n:
            css = re.sub(src, dst, css, flags=re.IGNORECASE)
            report["hex_replacements"][f"{src} -> {dst}"] = n

    # rgb triplet sweep
    def fix_rgb(m):
        fn, r, g, b, rest = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
        tgt = RGB_MAP.get((r, g, b))
        if tgt:
            report["rgb_replacements"][f"({r},{g},{b}) -> ({tgt[0]},{tgt[1]},{tgt[2]})"] = \
                report["rgb_replacements"].get(f"({r},{g},{b}) -> ({tgt[0]},{tgt[1]},{tgt[2]})", 0) + 1
            return f"{fn}{tgt[0]}, {tgt[1]}, {tgt[2]}{rest}"
        return m.group(0)
    css = re.sub(r"(rgba?\()(\d+),\s*(\d+),\s*(\d+)([,)])", fix_rgb, css)

    # safety: malformed color functions would void entire rules (CSS error
    # recovery) — fail loudly instead of shipping a broken stylesheet.
    if re.search(r"rgba?\(\(", css):
        sys.exit("FATAL: malformed rgba(( produced — aborting write")
    open(CSS_PATH, "w").write(css)
    json.dump(report, open(REPORT_PATH, "w"), indent=1)
    total_hex = sum(report["hex_replacements"].values())
    total_rgb = sum(report["rgb_replacements"].values())
    print(f"root blocks: {report['root_blocks_seen']} (1 canonical + "
          f"{report['blocks_removed']} empty legacy removed, "
          f"{report['declarations_stripped']} declarations stripped)")
    print(f"hex literals remapped: {total_hex} across {len(report['hex_replacements'])} mappings")
    print(f"rgb triplets remapped: {total_rgb} across {len(report['rgb_replacements'])} mappings")
    print("report ->", REPORT_PATH)


if __name__ == "__main__":
    main()
