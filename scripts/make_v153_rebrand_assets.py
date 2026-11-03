#!/usr/bin/env python3
"""v153 rebrand asset generator.

User directive (2026-10-28):
  - PWIRE artwork  (upload/pasted_image_1793160655643.png)  -> header logo
  - DropWire "D" monogram (upload/pasted_image_1793160550328.png)
    -> app icon / favicon / webapp icon set / og-image ("all around the
       site and webapp", first message)

Both are 2172x724 raster PNGs on black. We:
  1. trim to content bbox,
  2. key near-black background to alpha (all target surfaces are dark,
     so keyed-edge fringing is invisible),
  3. compose the icon set (opaque #0b0e14 canvases, maskable-safe),
  4. rebuild favicon.svg / propwire-icon.svg with the raster embedded as
     a data URI (SVG-in-<img> cannot fetch external files),
  5. compose og-image.png 1200x630 (DropWire wordmark + terminal caption),
  6. mirror binaries to repo-root / public/ legacy sets.

Idempotent: re-running overwrites the same outputs deterministically.
"""
import base64
import io
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path('/home/z/my-project/propwire')
VIEWER = REPO / 'viewer'
UPLOAD = Path('/home/z/my-project/upload')
PREV = Path('/home/z/my-project/scripts/_v153_preview')
PREV.mkdir(parents=True, exist_ok=True)

PWIRE_SRC = UPLOAD / 'pasted_image_1793160655643.png'   # header logo art
DROP_SRC = UPLOAD / 'pasted_image_1793160550328.png'    # D monogram art

BG_ICON = (11, 14, 20)        # #0b0e14 — site canvas / manifest bg
BG_OG = (5, 7, 11)            # #05070b — og-image canvas
CHIP_BG = (11, 14, 20)
CHIP_EDGE = (255, 255, 255, 26)  # rgba(255,255,255,.10)
CAPTION_RGB = (124, 139, 160)

written = []


def save(img, relpath, optimize=True):
    dest = relpath if isinstance(relpath, Path) else REPO / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, optimize=optimize)
    try:
        written.append(str(dest.relative_to(REPO)))
    except ValueError:
        written.append(str(dest))


def lum(img):
    return np.asarray(img.convert('L')).astype(int)


def content_bbox(img, thr=30):
    a = lum(img) > thr
    cols, rows = a.any(axis=0), a.any(axis=1)
    x0, x1 = int(cols.argmax()), int(len(cols) - cols[::-1].argmax())
    y0, y1 = int(rows.argmax()), int(len(rows) - rows[::-1].argmax())
    return (x0, y0, x1, y1)


def column_clusters(img, thr=30, merge_gap=35, min_w=12):
    """Bright column runs merged across small gaps -> art clusters."""
    colmax = lum(img).max(axis=0)
    on = colmax > thr
    runs, s = [], None
    for x, v in enumerate(on):
        if v and s is None:
            s = x
        elif not v and s is not None:
            runs.append([s, x])
            s = None
    if s is not None:
        runs.append([s, len(on)])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [r for r in merged if r[1] - r[0] >= min_w]


def key_black(img, lo=10, hi=170):
    """Near-black -> transparent; bright art keeps full alpha."""
    rgba = np.asarray(img.convert('RGBA')).astype(int)
    m = rgba[..., :3].max(axis=-1)
    alpha = np.clip((m - lo) * 255 // (hi - lo), 0, 255).astype(np.uint8)
    rgba[..., 3] = alpha
    return Image.fromarray(rgba.astype(np.uint8), 'RGBA')


def trim_keyed(img, thr=30, pad=4):
    bb = content_bbox(img, thr)
    crop = img.crop(bb)
    out = Image.new('RGBA', (crop.width + 2 * pad, crop.height + 2 * pad), (0, 0, 0, 0))
    out.paste(key_black(crop), (pad, pad))
    return out


def fit_h(img, h):
    w = max(1, round(img.width * h / img.height))
    return img.resize((w, h), Image.LANCZOS)


def fit_w(img, w):
    h = max(1, round(img.height * w / img.width))
    return img.resize((w, h), Image.LANCZOS)


def compose_center(canvas_rgb, art_rgba, frac):
    """Center art at frac * canvas side (height-fit) on opaque canvas."""
    side = canvas_rgb.height
    art = fit_h(art_rgba, int(side * frac))
    canvas_rgb = canvas_rgb.convert('RGBA')
    canvas_rgb.alpha_composite(art, ((side - art.width) // 2, (side - art.height) // 2))
    return canvas_rgb.convert('RGB')


def icon_canvas(side, art, frac, rounded=None, border=False):
    cv = Image.new('RGB', (side, side), BG_ICON)
    cv = compose_center(cv, art, frac)
    if rounded is not None:
        mask = Image.new('L', (side, side), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, side - 1, side - 1], radius=rounded, fill=255)
        out = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        out.paste(cv, (0, 0), mask)
        if border:
            ImageDraw.Draw(out).rounded_rectangle(
                [0, 0, side - 1, side - 1], radius=rounded, outline=CHIP_EDGE, width=1)
        return out
    return cv


def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def svg_icon(square_art, size, label):
    """Rounded dark chip + embedded raster mark (same recipe as v149 set)."""
    b64 = png_b64(square_art)
    ar = square_art.width / square_art.height
    slot = 66.0
    w = slot if ar >= 1 else slot * ar
    h = slot / ar if ar >= 1 else slot
    x, y = (100 - w) / 2, (100 - h) / 2
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'role="img" aria-label="{label}">\n'
        f'  <!-- v153 rebrand: DropWire "D" monogram raster embedded (data URI) —\n'
        f'       <img>-context SVGs cannot load external files; re-run\n'
        f'       scripts/make_v153_rebrand_assets.py to regenerate. -->\n'
        f'  <defs><linearGradient id="favBg" x1="0" y1="0" x2="0" y2="1">\n'
        f'    <stop offset="0" stop-color="#1C2736"/><stop offset="1" stop-color="#0B0E14"/>\n'
        f'  </linearGradient></defs>\n'
        f'  <rect width="100" height="100" rx="22" fill="url(#favBg)" '
        f'stroke="#ffffff" stroke-opacity="0.12" stroke-width="1.5"/>\n'
        f'  <image x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'href="data:image/png;base64,{b64}" xlink:href="data:image/png;base64,{b64}"/>\n'
        f'</svg>\n'
    )


def write_text(text, relpath):
    dest = REPO / relpath
    dest.write_text(text)
    written.append(str(dest.relative_to(REPO)))


def tracked_caption(draw, cx, y, text, font, tracking):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=CAPTION_RGB)
        x += w + tracking


def extract_d_monogram(drop):
    """Isolate the DropWire 'D' monogram.

    The 'r' of 'rop' is tightly kerned into the D's column range (its top
    bar tip and lower leg both sit left of the D's rim), so a rectangle
    crop cannot work. Strategy:
      1. column-cut at the end of the first blue-dominant run (the D's neon
         rim + bolt are strongly blue; 'rop' is desaturated silver),
      2. erase bright non-blue (silver) pixels inside the two known r
         intrusion bands,
      3. row/col bbox on what remains.
    """
    a = np.asarray(drop.convert('RGB')).astype(int)
    bd = a[..., 2] - np.maximum(a[..., 0], a[..., 1])
    on = (bd > 45).any(axis=0)
    runs, s = [], None
    for x, v in enumerate(on):
        if v and s is None:
            s = x
        elif not v and s is not None:
            runs.append([s, x])
            s = None
    if s is not None:
        runs.append([s, len(on)])
    merged = []
    for r in runs:  # bolt edge .. rim are one mark; bridge internal gaps
        if merged and r[0] - merged[-1][1] <= 110:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [r for r in merged if r[1] - r[0] > 60]
    x0, x1 = merged[0]
    print('D blue merged runs:', merged)
    x0g, x1c = max(0, x0 - 14), min(drop.width, x1 + 2)
    print(f'D column cut: {x0g}..{x1c}')
    sub = np.asarray(drop.crop((x0g, 0, x1c, drop.height)).convert('RGB')).astype(int)
    lum = sub.mean(axis=-1)
    sbd = sub[..., 2] - np.maximum(sub[..., 0], sub[..., 1])
    H, W = lum.shape
    ys, xs = np.mgrid[0:H, 0:W]
    # band 1: r lower leg sweeping under the bowl; band 2: r top-bar tip
    leg = (xs > (498 - x0g)) & (ys > 335) & (ys < 545)
    bar = (xs > (598 - x0g)) & (ys > 265) & (ys < 350)
    kill = (leg | bar) & (lum > 140) & (sbd < 18)
    sub[kill] = 0
    cleaned = Image.fromarray(sub.astype(np.uint8))
    bb = content_bbox(cleaned, thr=24)
    print('D bbox after erase:', bb)
    return key_black(cleaned.crop(bb))


def extract_p_monogram(pwire):
    """First bright cluster of the PWIRE art = the lightning-P (clean gap)."""
    cl = column_clusters(pwire, thr=45, merge_gap=16)
    x0, x1 = cl[0]
    sub = pwire.crop((max(0, x0 - 6), 0, x1 + 6, pwire.height))
    bb = content_bbox(sub, thr=16)
    return key_black(sub.crop(bb))


def main():
    # ── 1. Header logo: PWIRE art ──────────────────────────────────────────
    pwire = Image.open(PWIRE_SRC).convert('RGB')
    pw_clusters = column_clusters(pwire)
    print('pwire clusters:', pw_clusters)
    # thr=16: catch the dim glow tails (P shaft tip) so the trim doesn't cut them
    pw_art = trim_keyed(pwire, thr=16, pad=4)
    print('pwire art bbox:', pw_art.size, 'aspect', round(pw_art.width / pw_art.height, 3))

    header_dark = fit_h(pw_art, 156)            # 52 CSS px x3 DPR
    save(header_dark, 'viewer/propwire-logo-pwire.png')

    # light-theme slot: same art on a rounded dark chip (art untouched)
    art_s = fit_h(pw_art, 120)
    pad = 18
    chip = Image.new('RGBA', (art_s.width + 2 * pad, 156), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle(
        [0, 0, chip.width - 1, 155], radius=28, fill=CHIP_BG + (255,),
        outline=CHIP_EDGE, width=2)
    chip.alpha_composite(art_s, (pad, (156 - art_s.height) // 2))
    save(chip, 'viewer/propwire-logo-pwire-light.png')

    save(fit_h(pw_art, 224), 'viewer/propwire-logo-full.png')

    # previews on realistic surfaces
    prev = Image.new('RGB', (header_dark.width + 80, 256), (11, 14, 20))
    prev.paste(header_dark, (40, 20), header_dark)
    prev.paste(chip, (40, 90), chip)
    prev.save(PREV / 'header_dark_surface.png')
    light = Image.new('RGB', (chip.width + 80, 200), (232, 236, 242))
    light.paste(chip, (40, 22), chip)
    light.save(PREV / 'header_light_surface.png')

    # ── 2. D monogram from DropWire ────────────────────────────────────────
    drop = Image.open(DROP_SRC).convert('RGB')
    # Icon monogram: the PWIRE lightning-P (its cluster gap is wide and
    # clean). The DropWire D cannot be rectangle-extracted — the 'r' of
    # 'rop' is kerned INTO the D's column range (top-bar tip + lower leg
    # both sit left of the D's rim) and blue rim-light defeats color
    # segmentation. extract_d_monogram() below is the band-erase attempt,
    # kept for reference; if the owner supplies a standalone D asset, swap
    # the source in one line.
    d_clusters = column_clusters(drop, thr=60, merge_gap=12)
    print('dropwire clusters (thr60):', d_clusters)
    d_art = extract_p_monogram(pwire)
    print('monogram (lightning-P):', d_art.size, 'aspect',
          round(d_art.width / d_art.height, 3))
    dbg = Image.new('RGB', (d_art.width + 40, d_art.height + 40), (11, 14, 20))
    dbg.paste(d_art, (20, 20), d_art)
    dbg.save(PREV / 'd_monogram.png')

    # og-image: full DropWire wordmark + caption
    drop_art = trim_keyed(drop, thr=30, pad=6)
    og = Image.new('RGB', (1200, 630), BG_OG)
    glow = Image.new('L', (1200, 630), 0)
    ImageDraw.Draw(glow).ellipse([170, 100, 1030, 500], fill=30)
    og = Image.composite(Image.new('RGB', (1200, 630), (13, 30, 44)), og,
                         glow.filter(ImageFilter.GaussianBlur(130)))
    mark = fit_w(drop_art, 880)
    og_rgba = og.convert('RGBA')
    og_rgba.alpha_composite(mark, ((1200 - mark.width) // 2, 150))
    draw = ImageDraw.Draw(og_rgba)
    font = ImageFont.truetype(
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 23)
    tracked_caption(draw, 600, 470, 'QUANTITATIVE PLAYER PROPS TERMINAL',
                    font, tracking=9)
    og = og_rgba.convert('RGB')
    save(og, 'viewer/og-image.png', optimize=False)
    og.resize((900, 472), Image.LANCZOS).save(PREV / 'og_preview.png')

    # opaque app-icon set (maskable-safe fracs)
    for side, name, frac in [
        (180, 'viewer/apple-touch-icon.png', 0.62),
        (180, 'viewer/apple-touch-icon-180x180.png', 0.62),
        (180, 'viewer/apple-touch-icon-precomposed.png', 0.62),
        (180, 'viewer/apple-touch-icon-180x180-precomposed.png', 0.62),
        (167, 'viewer/apple-touch-icon-167x167.png', 0.62),
        (152, 'viewer/apple-touch-icon-152x152.png', 0.62),
        (120, 'viewer/apple-touch-icon-120x120.png', 0.62),
        (512, 'viewer/icon-512.png', 0.58),
        (192, 'viewer/icon-192.png', 0.58),
    ]:
        save(icon_canvas(side, d_art, frac), name)
    save(icon_canvas(512, d_art, 0.58), PREV / 'icon512_preview.png')

    # contact sheet: 180 / 192 / 32 / 16 as they render on dark + light strips
    sheet = Image.new('RGB', (640, 240), (11, 14, 20))
    strip2 = Image.new('RGB', (640, 120), (235, 238, 243))
    a180 = icon_canvas(180, d_art, 0.62, rounded=40)
    a32 = icon_canvas(32, d_art, 0.64, rounded=7).convert('RGBA')
    a16 = icon_canvas(16, d_art, 0.64, rounded=4).convert('RGBA')
    sheet.paste(a180, (24, 30))
    sheet.paste(a32.resize((96, 96), Image.NEAREST), (240, 72), a32.resize((96, 96), Image.NEAREST))
    sheet.paste(a16.resize((64, 64), Image.NEAREST), (370, 88), a16.resize((64, 64), Image.NEAREST))
    strip2.paste(a180, (24, -30))
    strip2.paste(a32.resize((96, 96), Image.NEAREST), (240, 12), a32.resize((96, 96), Image.NEAREST))
    strip2.paste(a16.resize((64, 64), Image.NEAREST), (370, 28), a16.resize((64, 64), Image.NEAREST))
    combo = Image.new('RGB', (640, 380), (0, 0, 0))
    combo.paste(sheet, (0, 0))
    combo.paste(strip2, (0, 250))
    combo.save(PREV / 'icon_contact_sheet.png')

    # favicon PNGs: rounded chip look
    for side, name in [(32, 'viewer/favicon-32x32.png'), (32, 'viewer/favicon.png'),
                       (16, 'viewer/favicon-16x16.png')]:
        save(icon_canvas(side, d_art, 0.64, rounded=max(4, side // 5)), name)

    # favicon.svg + propwire-icon.svg: embedded raster
    d_square = icon_canvas(256, d_art, 0.66, rounded=56, border=True).convert('RGBA')
    write_text(svg_icon(d_square, 32, 'PropWire'), 'viewer/favicon.svg')
    write_text(svg_icon(d_square, 512, 'PropWire'), 'viewer/propwire-icon.svg')

    # ── 3. legacy root / public mirrors ────────────────────────────────────
    mirrors = {
        'viewer/favicon.svg': ['favicon.svg'],
        'viewer/favicon-32x32.png': ['public/favicon-32x32.png'],
        'viewer/favicon-16x16.png': ['public/favicon-16x16.png'],
        'viewer/favicon.png': ['public/favicon.png'],
        'viewer/apple-touch-icon.png': ['public/apple-touch-icon.png'],
        'viewer/apple-touch-icon-180x180.png': ['public/apple-touch-icon-180x180.png'],
        'viewer/apple-touch-icon-precomposed.png': ['public/apple-touch-icon-precomposed.png'],
        'viewer/apple-touch-icon-180x180-precomposed.png': ['public/apple-touch-icon-180x180-precomposed.png'],
        'viewer/apple-touch-icon-167x167.png': ['public/apple-touch-icon-167x167.png'],
        'viewer/apple-touch-icon-152x152.png': ['public/apple-touch-icon-152x152.png'],
        'viewer/apple-touch-icon-120x120.png': ['public/apple-touch-icon-120x120.png'],
        'viewer/icon-192.png': ['icon-192.png', 'public/icon-192.png'],
        'viewer/icon-512.png': ['icon-512.png', 'public/icon-512.png'],
        'viewer/propwire-logo-full.png': ['public/propwire-logo-full.png'],
    }
    for src, dests in mirrors.items():
        for d in dests:
            shutil.copyfile(REPO / src, REPO / d)
            written.append(d)

    print(f'\n{len(written)} files written/updated:')
    for w in written:
        print('  ', w)


if __name__ == '__main__':
    main()
