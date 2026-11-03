#!/usr/bin/env python3
"""Build the PropWire header brand lockup (v3) as pure-path SVGs.

Why paths, not <text>: propwire-logo.svg is loaded via <img>, and SVGs in
img context cannot fetch webfonts — the previous Montserrat / JetBrains Mono
<text> elements silently fell back to a generic OS sans, so the wordmark
rendered differently (and worse) on every platform. This script converts the
shaped glyph runs to explicit SVG paths with uharfbuzz + fontTools, so every
visitor sees the identical letterforms at any DPR.

Outputs (both, deterministic):
  viewer/propwire-logo.svg        dark-terminal palette (default theme)
  viewer/propwire-logo-dark.svg   dark-ink palette for the light theme

The viewBox is computed from the actual ink bounding box and snapped to an
exact 4:1 aspect so the lockup fills the CSS brand box (208x52 / 176x44 /
136x34, all 4:1) with no letterboxing and no dead margin.

Fonts: Montserrat Bold (700) + JetBrains Mono SemiBold (600), both OFL,
downloaded once into the font cache dir and instanced with fontTools.
Usage: python3 scripts/build_logo_lockup.py [--font-cache DIR]
"""
import argparse
import os
import sys
import urllib.request

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform
import uharfbuzz as hb

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_CACHE_DEFAULT = os.path.join(os.path.dirname(REPO), "scripts", "fonts")

FONT_URLS = {
    "Montserrat[wght].ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "JetBrainsMono[wght].ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
}

# ── Layout (viewBox units = px at 1:1) ──────────────────────────────────────
MARK_TRANSFORM = (16, 12, 0.58)          # translate(16,12) scale(0.58)
WORDMARK_X, WORDMARK_BASELINE, WORDMARK_SIZE, WORDMARK_TRACK = 142, 72, 44, 2.0
SUBTITLE_X, SUBTITLE_BASELINE, SUBTITLE_SIZE, SUBTITLE_TRACK = 144, 101, 11, 2.0
WORDMARK_TEXT = "PropWire"
SUBTITLE_TEXT = "QUANTITATIVE SPORTS BETTING TERMINAL"

# The trend-arrow P mark, verbatim geometry from v2 (favicon-consistent).
MARK_PATHS = [
    "M 146.1 12.0 L 179.3 12.0 L 182.8 14.0 L 184.4 17.0 L 184.4 52.2 L 183.6 54.0 L 181.1 56.3 L 178.1 57.0 L 175.1 56.3 L 172.8 54.2 L 171.5 50.2 L 171.5 35.6 L 171.0 35.4 L 115.7 92.0 L 108.9 97.2 L 101.9 100.8 L 93.3 103.0 L 89.3 103.5 L 58.1 103.8 L 58.1 181.7 L 56.9 185.2 L 54.6 187.2 L 52.4 188.0 L 21.4 188.0 L 17.7 186.2 L 16.4 184.7 L 15.6 182.5 L 15.6 24.6 L 16.7 22.3 L 18.4 20.5 L 20.7 19.5 L 96.6 19.5 L 100.6 20.0 L 107.7 21.6 L 112.2 23.1 L 120.5 26.8 L 125.0 29.6 L 131.3 34.4 L 134.3 37.4 L 135.6 39.9 L 135.6 42.7 L 134.1 45.7 L 131.6 47.5 L 128.0 47.7 L 124.8 46.2 L 121.0 42.7 L 113.5 37.6 L 107.9 35.1 L 99.4 32.9 L 95.9 32.4 L 28.5 32.6 L 28.5 174.7 L 44.8 174.9 L 45.3 174.2 L 45.3 95.5 L 46.1 93.7 L 47.3 92.2 L 50.1 90.7 L 87.8 90.7 L 91.8 90.2 L 98.4 88.2 L 105.4 83.9 L 162.5 25.8 L 162.5 24.8 L 146.6 24.8 L 143.4 23.3 L 142.1 21.8 L 141.4 19.8 L 141.4 16.8 L 142.6 14.3 L 144.4 12.8 L 145.9 12.3 Z",
    "M 146.1 66.6 L 149.2 66.6 L 151.4 67.6 L 152.9 69.1 L 153.9 71.3 L 154.2 87.7 L 153.4 93.7 L 150.7 103.8 L 147.9 110.1 L 143.9 116.8 L 138.1 124.1 L 131.8 129.9 L 123.0 135.7 L 115.2 139.2 L 104.4 142.0 L 100.1 142.5 L 71.2 142.5 L 69.5 141.7 L 67.2 139.5 L 66.4 137.7 L 66.4 134.4 L 68.4 131.2 L 71.7 129.7 L 97.9 129.7 L 106.4 128.4 L 111.2 126.9 L 117.7 123.9 L 125.5 118.4 L 132.8 110.3 L 138.3 100.0 L 139.9 95.5 L 141.4 86.7 L 141.4 71.6 L 142.4 69.3 L 144.1 67.6 L 145.9 66.8 Z",
]
MARK_RAW_BBOX = (15.6, 12.0, 184.4, 188.0)   # control-point hull of both paths

# ── Palettes ────────────────────────────────────────────────────────────────
# 2026-10 restyle: brand moved lime -> baby blue (white + baby-blue dark
# theme, FanDuel-calibrated). Ramps anchor on the CSS tokens:
# --baby-blue #7dd3fc / bright #bae6fd / deep #38bdf8.
DARK_PALETTE = {
    "prop": "#FFFFFF",
    "mark_grad": ("#A5DCFB", "#5CB9F0"),     # vertical: lighter baby-blue top
    "wire_grad": ("#8FD2F8", "#47AEE8"),     # horizontal sheen on "Wire"
    "subtitle": "#8B949E",
}
LIGHT_PALETTE = {
    "prop": "#17202b",
    "mark_grad": ("#3D8FD0", "#22619C"),
    "wire_grad": ("#2F7CBC", "#1C5286"),
    "subtitle": "#526174",
}


def fetch_fonts(cache_dir: str) -> dict:
    os.makedirs(cache_dir, exist_ok=True)
    paths = {}
    for name, url in FONT_URLS.items():
        dest = os.path.join(cache_dir, name)
        if not os.path.exists(dest):
            print(f"downloading {name} ...")
            urllib.request.urlretrieve(url, dest)
        paths[name] = dest
    return paths


def instance_font(var_path: str, wght: int) -> tuple:
    """Instance a variable font at `wght`; return (bytes, TTFont) pair.

    The bytes and the TTFont come from the same instanced snapshot, so
    HarfBuzz metrics and fontTools outlines are guaranteed to agree.
    (Reading via font.reader.file is wrong: the read starts at the parser's
    current file position and yields truncated garbage -> HB maps every
    character to gid 0 / .notdef, i.e. tofu.)"""
    font = TTFont(var_path)
    if "fvar" in font:
        instantiateVariableFont(font, {"wght": wght}, inplace=True)
    import io
    buf = io.BytesIO()
    font.save(buf)
    data = buf.getvalue()
    return data, TTFont(io.BytesIO(data))


def shape_run(font_bytes: bytes, text: str, size: float, track_px: float):
    """HarfBuzz shape -> list of (glyph_id, x_pen_units, y_pen_units)."""
    face = hb.Face(font_bytes)
    font = hb.Font(face)
    upem = face.upem
    font.scale = (upem, upem)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    track_units = track_px * upem / size
    placed, x = [], 0.0
    for i, info in enumerate(buf.glyph_infos):
        pos = buf.glyph_positions[i]
        placed.append((info.codepoint, x + pos.x_offset, -pos.y_offset))
        x += pos.x_advance + (track_units if i < len(buf.glyph_infos) - 1 else 0)
    return placed, x, upem


def run_to_path(tt: TTFont, placed, upem: int, size: float,
                pen_x: float, baseline_y: float) -> tuple:
    """Bake glyphs into one absolute SVG path string + ink bbox."""
    glyph_order = tt.getGlyphOrder()
    glyph_set = tt.getGlyphSet()
    s = size / upem
    spen = SVGPathPen(glyph_set, ntos=lambda v: f"{v:.2f}")
    bounds = BoundsPen(glyph_set)
    for gid, gx, gy in placed:
        name = glyph_order[gid]
        tx = pen_x + gx * s
        ty = baseline_y - gy * s
        tr = Transform(s, 0, 0, -s, tx, ty)
        glyph_set[name].draw(TransformPen(spen, tr))
        glyph_set[name].draw(TransformPen(bounds, tr))
    return spen.getCommands(), bounds.bounds


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def build_svg(palette: dict, mark_fill: str, prop_path: str, wire_path: str,
              sub_path: str, vb: tuple) -> str:
    x, y, w, h = vb
    mark_top, mark_bot = palette["mark_grad"]
    wire_l, wire_r = palette["wire_grad"]
    return f'''<svg width="{fmt(w)}" height="{fmt(h)}" viewBox="{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PropWire — Quantitative Sports Betting Terminal">
  <!-- PropWire brand lockup v3. Generated by scripts/build_logo_lockup.py
       (Montserrat Bold + JetBrains Mono SemiBold, converted to paths so the
       wordmark is identical on every OS/DPR — <img>-context SVGs cannot load
       webfonts). Do not hand-edit the paths; re-run the generator. -->
  <defs>
    <linearGradient id="pwMark" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{mark_top}"/>
      <stop offset="1" stop-color="{mark_bot}"/>
    </linearGradient>
    <linearGradient id="pwWire" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{wire_l}"/>
      <stop offset="1" stop-color="{wire_r}"/>
    </linearGradient>
  </defs>

  <!-- Trend-arrow P mark (favicon-consistent) -->
  <g transform="translate({MARK_TRANSFORM[0]},{MARK_TRANSFORM[1]}) scale({MARK_TRANSFORM[2]})" fill="url(#pwMark)">
    <path d="{MARK_PATHS[0]}"/>
    <path d="{MARK_PATHS[1]}"/>
  </g>

  <!-- Wordmark: letterform paths, two-tone -->
  <path d="{prop_path}" fill="{palette["prop"]}"/>
  <path d="{wire_path}" fill="url(#pwWire)"/>

  <!-- Subtitle -->
  <path d="{sub_path}" fill="{palette["subtitle"]}"/>
</svg>
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-cache", default=FONT_CACHE_DEFAULT)
    args = ap.parse_args()

    fonts = fetch_fonts(args.font_cache)

    mont_bytes, mont = instance_font(fonts["Montserrat[wght].ttf"], 700)
    jb_bytes, jbmono = instance_font(fonts["JetBrainsMono[wght].ttf"], 600)

    # Shape + bake wordmark: split into PROP and WIRE runs for two-tone fill.
    # Shape the full string once for correct kerning across the boundary.
    placed_full, adv_full, upem_m = shape_run(mont_bytes, WORDMARK_TEXT,
                                              WORDMARK_SIZE, WORDMARK_TRACK)
    # Find the glyph index where "Wire" starts (after "Prop").
    split_units = shape_run(mont_bytes, "Prop", WORDMARK_SIZE, 0)[1]
    placed_prop = [g for g in placed_full if g[1] < split_units]
    placed_wire = [g for g in placed_full if g[1] >= split_units]
    prop_path, prop_bb = run_to_path(mont, placed_prop, upem_m, WORDMARK_SIZE,
                                     WORDMARK_X, WORDMARK_BASELINE)
    wire_path, wire_bb = run_to_path(mont, placed_wire, upem_m, WORDMARK_SIZE,
                                     WORDMARK_X, WORDMARK_BASELINE)
    sub_placed, sub_adv, upem_j = shape_run(jb_bytes, SUBTITLE_TEXT,
                                            SUBTITLE_SIZE, SUBTITLE_TRACK)
    sub_path, sub_bb = run_to_path(jbmono, sub_placed, upem_j, SUBTITLE_SIZE,
                                   SUBTITLE_X, SUBTITLE_BASELINE)

    # Mark ink bbox in final coordinates.
    mtx, mty, ms = MARK_TRANSFORM
    mark_bb = (mtx + MARK_RAW_BBOX[0] * ms, mty + MARK_RAW_BBOX[1] * ms,
               mtx + MARK_RAW_BBOX[2] * ms, mty + MARK_RAW_BBOX[3] * ms)

    xs = [mark_bb[0], prop_bb[0], wire_bb[0], sub_bb[0]]
    ys = [mark_bb[1], prop_bb[1], wire_bb[1], sub_bb[1]]
    xe = [mark_bb[2], prop_bb[2], wire_bb[2], sub_bb[2]]
    ye = [mark_bb[3], prop_bb[3], wire_bb[3], sub_bb[3]]
    ink = (min(xs), min(ys), max(xe), max(ye))
    print(f"ink bbox: {ink[0]:.1f},{ink[1]:.1f} -> {ink[2]:.1f},{ink[3]:.1f} "
          f"(w={ink[2]-ink[0]:.1f} h={ink[3]-ink[1]:.1f})")

    # Snap viewBox to exact 4:1 around the ink box (balanced padding).
    pad = 5.0
    iw, ih = ink[2] - ink[0] + 2 * pad, ink[3] - ink[1] + 2 * pad
    if iw < 4 * ih:
        w, h = 4 * ih, ih
    else:
        w, h = iw, iw / 4
    vx = (ink[0] + ink[2]) / 2 - w / 2
    vy = (ink[1] + ink[3]) / 2 - h / 2
    vb = (vx, vy, w, h)
    print(f"viewBox: {vx:.2f} {vy:.2f} {w:.2f} {h:.2f} (aspect {w/h:.4f})")

    mark_fill = "url(#pwMark)"
    for target, palette in (
        ("viewer/propwire-logo.svg", DARK_PALETTE),
        ("viewer/propwire-logo-dark.svg", LIGHT_PALETTE),
    ):
        out = os.path.join(REPO, target)
        svg = build_svg(palette, mark_fill, prop_path, wire_path, sub_path, vb)
        with open(out, "w") as f:
            f.write(svg)
        print(f"written {target} ({len(svg)} bytes)")

    # Regeneration self-check: file must remain a valid standalone SVG.
    for t in ("viewer/propwire-logo.svg", "viewer/propwire-logo-dark.svg"):
        with open(os.path.join(REPO, t)) as f:
            head = f.read(60)
        assert head.startswith("<svg"), f"{t} malformed"
    return 0


if __name__ == "__main__":
    sys.exit(main())
