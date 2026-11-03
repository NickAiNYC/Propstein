#!/usr/bin/env python3
"""Build PropStein's favicon and install icons from the official blue P mark."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
PUBLIC = ROOT / "public"
LOGO = VIEWER / "propstein-logo.png"


def extract_p_mark() -> Image.Image:
    """Keep the ice-blue emblem, excluding the adjacent white wordmark."""
    source = Image.open(LOGO).convert("RGBA")
    pixels = np.asarray(source).astype(np.float32)
    red, green, blue, alpha = (pixels[:, :, channel] for channel in range(4))
    blue_strength = np.minimum(
        np.clip((blue - red - 8) / 24, 0, 1),
        np.clip((green - red - 5) / 20, 0, 1),
    )
    # The wordmark starts near x=250; its white pixels have no blue chroma.
    blue_strength[:, 300:] = 0
    pixels[:, :, 3] = alpha * blue_strength
    mark = Image.fromarray(pixels.astype(np.uint8))
    bounds = mark.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError(f"No blue P mark found in {LOGO}")
    return mark.crop(bounds)


def master_icon(mark: Image.Image, footprint: float, bloom_radius: int, rim: bool) -> Image.Image:
    size = 1024
    y, x = np.mgrid[:size, :size]
    vertical = y / (size - 1)
    background = np.empty((size, size, 4), dtype=np.uint8)
    # The app shell is graphite, so the icon tile uses neutral charcoal rather
    # than the old navy. The official ice-blue P remains the sole color accent.
    for channel, top, bottom in ((0, 38, 10), (1, 38, 10), (2, 42, 12)):
        background[:, :, channel] = (top * (1 - vertical) + bottom * vertical).astype(np.uint8)
    background[:, :, 3] = 255

    aura = np.exp(-((x - 512) ** 2 + (y - 390) ** 2) / (2 * (size * 0.38) ** 2))
    for channel, amount in enumerate((24, 24, 27)):
        background[:, :, channel] = np.clip(background[:, :, channel].astype(float) + aura * amount, 0, 255)
    canvas = Image.fromarray(background)

    height = round(size * footprint)
    width = round(mark.width * height / mark.height)
    glyph = mark.resize((width, height), Image.Resampling.LANCZOS)
    glyph_alpha = glyph.getchannel("A")
    position = ((size - width) // 2, (size - height) // 2)
    layer = Image.new("RGBA", (size, size))
    layer.paste(glyph, position)
    alpha_layer = Image.new("L", (size, size))
    alpha_layer.paste(glyph_alpha, position)

    glow = Image.new("RGBA", (size, size), (56, 189, 248, 0))
    glow.putalpha(alpha_layer.filter(ImageFilter.GaussianBlur(bloom_radius)).point(lambda v: round(v * 0.32)))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_alpha = Image.new("L", (size, size))
    shadow_alpha.paste(glyph_alpha, (position[0], position[1] + 12))
    shadow.putalpha(shadow_alpha.filter(ImageFilter.GaussianBlur(18)).point(lambda v: round(v * 0.7)))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, layer)

    if rim:
        rim_layer = Image.new("RGBA", (size, size))
        draw = ImageDraw.Draw(rim_layer)
        draw.rounded_rectangle((15, 15, 1008, 1008), radius=228, outline=(210, 218, 225, 48), width=4)
        draw.rounded_rectangle((21, 21, 1002, 1002), radius=222, outline=(125, 211, 252, 34), width=2)
        canvas = Image.alpha_composite(canvas, rim_layer)
    return canvas


def save_png(icon: Image.Image, size: int, names: list[str], destinations: tuple[Path, ...]) -> None:
    result = icon.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 32:
        result = ImageEnhance.Sharpness(result).enhance(1.4 if size == 32 else 1.55)
    for folder in destinations:
        for name in names:
            result.save(folder / name, format="PNG", optimize=True)


def save_svg(icon: Image.Image) -> None:
    preview = icon.resize((512, 512), Image.Resampling.LANCZOS)
    image_bytes = BytesIO()
    preview.save(image_bytes, format="PNG", optimize=True)
    payload = base64.b64encode(image_bytes.getvalue()).decode("ascii")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        '<defs><clipPath id="tile"><rect width="512" height="512" rx="112"/></clipPath></defs>'
        f'<image clip-path="url(#tile)" href="data:image/png;base64,{payload}" width="512" height="512"/>'
        '</svg>\n'
    )
    for folder in (VIEWER, PUBLIC, ROOT):
        (folder / "favicon.svg").write_text(svg, encoding="utf-8")


def main() -> None:
    mark = extract_p_mark()
    app = master_icon(mark, footprint=0.70, bloom_radius=24, rim=True)
    favicon = master_icon(mark, footprint=0.84, bloom_radius=12, rim=False)
    save_png(app, 512, ["icon-512.png"], (VIEWER, PUBLIC, ROOT))
    save_png(app, 192, ["icon-192.png"], (VIEWER, PUBLIC, ROOT))
    save_png(app, 180, [
        "apple-touch-icon.png", "apple-touch-icon-180x180.png",
        "apple-touch-icon-precomposed.png", "apple-touch-icon-180x180-precomposed.png",
    ], (VIEWER, PUBLIC))
    for size in (167, 152, 120):
        save_png(app, size, [f"apple-touch-icon-{size}x{size}.png"], (VIEWER, PUBLIC))
    save_png(favicon, 32, ["favicon-32x32.png", "favicon.png"], (VIEWER, PUBLIC))
    save_png(favicon, 32, ["favicon.png"], (ROOT,))
    save_png(favicon, 16, ["favicon-16x16.png"], (VIEWER, PUBLIC))
    save_svg(app)
    print(f"Generated PropStein icons from {LOGO} ({mark.width}x{mark.height} emblem)")


if __name__ == "__main__":
    main()
