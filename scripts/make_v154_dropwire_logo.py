#!/usr/bin/env python3
"""v154 header-logo recolor (owner directive 2026-10-28):

  "use this logo but make it white and make the WIRE a lighter baby blue"

Source: upload/pasted_image_1793162820521.png — 1672x941 RGB, BLACK DROPWIRE
wordmark on WHITE background (lightning-bolt D). Supersedes the v153 PWIRE
header art.

Pipeline (deterministic, idempotent):
  1. ink-coverage alpha: black-on-white is inverted vs the v153 sources, so
     alpha = (hi - lum) scaled; glyph RGB is then REPLACED wholesale by the
     target colors -> recomposited edges carry no dark fringe on any surface
  2. trim to ink bbox (incl. the bolt descender),
  3. find the P|W letter gap via zero-ink column runs -> split x
     ("DROP" -> white, "WIRE" -> lighter baby blue #A8DCF8),
  4. recompose the v153 slot geometry exactly:
       dark slot  propwire-logo-dropwire.png        (fit_h 156 = 3x52 CSS)
       light slot propwire-logo-dropwire-light.png  (art on rounded dark chip)
       full lockup propwire-logo-full.png (224) + public/ mirror
  5. og-image.png 1200x630 rebuilt with the recolored wordmark (height-capped
     fit — this art is ~2.2:1, taller than the v153 drop source),
  6. previews -> scripts/_v154_preview/ (dark/light surfaces + split QA).

Icons (lightning-P set) are intentionally untouched — owner scoped this
change to the logo. Re-run scripts/sweep_v154_busters.py after this.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path('/home/z/my-project/propwire')
VIEWER = REPO / 'viewer'
SRC = Path('/home/z/my-project/upload/pasted_image_1793162820521.png')
PREV = Path('/home/z/my-project/scripts/_v154_preview')
PREV.mkdir(parents=True, exist_ok=True)

WHITE = (255, 255, 255)
BABY = (168, 220, 248)          # #A8DCF8 — lighter baby blue
BG_ICON = (11, 14, 20)          # #0b0e14 — header canvas
CHIP_BG = (11, 14, 20)
CHIP_EDGE = (255, 255, 255, 26)
BG_OG = (5, 7, 11)
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


def ink_alpha(img, lo=40, hi=235):
    """Black-on-white -> ink coverage alpha, RGB reset to pure carriers."""
    lum = np.asarray(img.convert('L')).astype(int)
    alpha = np.clip((hi - lum) * 255 // (hi - lo), 0, 255).astype(np.uint8)
    out = np.zeros((*lum.shape, 4), dtype=np.uint8)
    out[..., 3] = alpha
    return alpha, out


def trim_crop(img, thr=40):
    """Crop to ink bbox (plain crop — NO transparent pad: RGBA->L reads
    transparent black as lum 0, which would ink every pad column)."""
    lum = np.asarray(img.convert('L')).astype(int)
    ink = lum < (255 - thr)
    cols, rows = ink.any(axis=0), ink.any(axis=1)
    x0, x1 = int(cols.argmax()), int(len(cols) - cols[::-1].argmax())
    y0, y1 = int(rows.argmax()), int(len(rows) - rows[::-1].argmax())
    return img.crop((x0, y0, x1, y1)), (x0, y0, x1, y1)


def pad_alpha(img, pad=4):
    """Transparent frame AFTER recoloring (RGBA paste carries alpha)."""
    out = Image.new('RGBA', (img.width + 2 * pad, img.height + 2 * pad),
                    (0, 0, 0, 0))
    out.paste(img, (pad, pad))
    return out


def find_pw_split(alpha, min_gap=3):
    """Zero-ink column gaps between first/last inked column.

    Letters D R O P W I R E -> 7 inter-letter gaps; the 4th (index 3) is P|W.
    Falls back to the gap nearest 50% width if kerning closes any gap.
    """
    has = (alpha > 52).any(axis=0)  # 52 == ink lum<195 (matches the verified
    # P|W gap probe); lower thresholds let AA residue bridge the kern gaps
    xs = np.where(has)[0]
    x0, x1 = int(xs[0]), int(xs[-1])
    gaps, s = [], None
    for x in range(x0, x1 + 1):
        if not has[x]:
            if s is None:
                s = x
        elif s is not None:
            if x - s >= min_gap:
                gaps.append((s, x))
            s = None
    print(f'ink span {x0}..{x1}, gaps found: {len(gaps)}')
    for i, g in enumerate(gaps):
        print(f'  gap{i}: {g[0]}..{g[1]} (w={g[1] - g[0]})')
    if len(gaps) >= 4:
        return (gaps[3][0] + gaps[3][1]) // 2, gaps
    target = (x0 + x1) / 2
    best = min(gaps, key=lambda g: abs((g[0] + g[1]) / 2 - target))
    print(f'  !! fewer than 4 gaps -> fallback nearest-50% gap {best}')
    return (best[0] + best[1]) // 2, gaps


def recolor(alpha, split):
    """alpha mask + wholesale RGB replacement: DROP white, WIRE baby blue."""
    h, w = alpha.shape
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., 3] = alpha
    xs = np.arange(w)[None, :].repeat(h, axis=0)
    out[xs < split, 0] = WHITE[0]
    out[xs < split, 1] = WHITE[1]
    out[xs < split, 2] = WHITE[2]
    out[xs >= split, 0] = BABY[0]
    out[xs >= split, 1] = BABY[1]
    out[xs >= split, 2] = BABY[2]
    return out


def fit_h(img, h):
    w = max(1, round(img.width * h / img.height))
    return img.resize((w, h), Image.LANCZOS)


def fit_w(img, w):
    h = max(1, round(img.height * w / img.width))
    return img.resize((w, h), Image.LANCZOS)


def tracked_caption(draw, cx, y, text, font, tracking):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=CAPTION_RGB)
        x += w + tracking


def main():
    src = Image.open(SRC).convert('RGB')
    print('source:', src.size, src.mode)

    crop_img, bbox = trim_crop(src)
    alpha_t, _ = ink_alpha(crop_img)
    split, gaps = find_pw_split(alpha_t)
    art = pad_alpha(Image.fromarray(recolor(alpha_t, split)))
    print('trimmed bbox:', bbox, 'art:', art.size,
          'aspect', round(art.width / art.height, 3), 'split@x=', split,
          f'({split / art.width:.1%} of width)')

    # ── header slots (v153 geometry) ───────────────────────────────────────
    header_dark = fit_h(art, 156)
    save(header_dark, 'viewer/propwire-logo-dropwire.png')

    art_s = fit_h(art, 120)
    pad = 18
    chip = Image.new('RGBA', (art_s.width + 2 * pad, 156), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle(
        [0, 0, chip.width - 1, 155], radius=28, fill=CHIP_BG + (255,),
        outline=CHIP_EDGE, width=2)
    chip.alpha_composite(art_s, (pad, (156 - art_s.height) // 2))
    save(chip, 'viewer/propwire-logo-dropwire-light.png')

    save(fit_h(art, 224), 'viewer/propwire-logo-full.png')

    # ── previews on realistic surfaces ─────────────────────────────────────
    prev = Image.new('RGB', (header_dark.width + 80, 256), BG_ICON)
    prev.paste(header_dark, (40, 20), header_dark)
    prev.paste(chip, (40, 90), chip)
    prev.save(PREV / 'header_dark_surface.png')
    light = Image.new('RGB', (chip.width + 80, 200), (232, 236, 242))
    light.paste(chip, (40, 22), chip)
    light.save(PREV / 'header_light_surface.png')

    # split QA: recolored art on mid-dark surface, 2x zoom of the boundary
    qa = Image.new('RGB', (fit_h(art, 220).width + 60, 260), (30, 34, 42))
    qa_art = fit_h(art, 220)
    qa.paste(qa_art, (30, 20), qa_art)
    bx = 30 + round(qa_art.width * split / art.width)
    ImageDraw.Draw(qa).line([(bx, 0), (bx, 259)], fill=(255, 90, 90), width=1)
    qa.save(PREV / 'split_qa.png')

    # ── og-image 1200x630 (recolored wordmark, height-capped fit) ──────────
    og = Image.new('RGB', (1200, 630), BG_OG)
    glow = Image.new('L', (1200, 630), 0)
    ImageDraw.Draw(glow).ellipse([170, 100, 1030, 500], fill=30)
    og = Image.composite(Image.new('RGB', (1200, 630), (13, 30, 44)), og,
                         glow.filter(ImageFilter.GaussianBlur(130)))
    mark = fit_w(art, 880)
    y_top = 150
    if mark.height > 340:
        mark = fit_h(art, 340)
        y_top = 140
    og_rgba = og.convert('RGBA')
    og_rgba.alpha_composite(mark, ((1200 - mark.width) // 2, y_top))
    draw = ImageDraw.Draw(og_rgba)
    font = ImageFont.truetype(
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 23)
    tracked_caption(draw, 600, 505, 'QUANTITATIVE PLAYER PROPS TERMINAL',
                    font, tracking=9)
    og = og_rgba.convert('RGB')
    save(og, 'viewer/og-image.png', optimize=False)
    og.resize((900, 472), Image.LANCZOS).save(PREV / 'og_preview.png')

    # ── legacy mirror ──────────────────────────────────────────────────────
    import shutil
    shutil.copyfile(REPO / 'viewer/propwire-logo-full.png',
                    REPO / 'public/propwire-logo-full.png')
    written.append('public/propwire-logo-full.png')

    print(f'\n{len(written)} files written/updated:')
    for w in written:
        print('  ', w)


if __name__ == '__main__':
    main()
