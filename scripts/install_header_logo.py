#!/usr/bin/env python3
"""
Install the new header logo from user uploaded graphic:
media_1793164447905.png
"""
import base64
import os
import numpy as np
from PIL import Image

SRC_PATH = "/Users/nick/.gemini/antigravity-ide/brain/e6a06847-5d35-427f-8387-bb239bf470ec/.user_uploaded/media_1793164447905.png"
VIEWER_DIR = "/Users/nick/Desktop/PropWire/viewer"

def process_logo():
    print(f"Loading source logo from: {SRC_PATH}")
    img = Image.open(SRC_PATH).convert("RGBA")
    arr = np.array(img).astype(float)

    # 1. Bounding box coordinates of the graphic
    # Y from 123 to 351, X from 15 to 788
    x0, y0, x1, y1 = 15, 123, 788, 351

    # Add 10px breathing room
    pad_y = 10
    pad_x = 12
    y0_pad = max(0, y0 - pad_y)
    y1_pad = min(arr.shape[0], y1 + pad_y)
    x0_pad = max(0, x0 - pad_x)
    x1_pad = min(arr.shape[1], x1 + pad_x)

    crop = arr[y0_pad:y1_pad, x0_pad:x1_pad]
    rgb = crop[:, :, :3]
    max_rgb = np.max(rgb, axis=2)

    # Threshold background noise (measured ~7-9)
    bg_thresh = 10.0
    alpha = np.clip((max_rgb - bg_thresh) / (255.0 - bg_thresh), 0.0, 1.0)

    # Unmultiply RGB for crisp anti-aliased edge
    clean_rgb = np.zeros_like(rgb)
    mask = alpha > 0.005
    for c in range(3):
        clean_rgb[mask, c] = np.clip((rgb[mask, c] - bg_thresh) / (alpha[mask] * (255.0 - bg_thresh) / 255.0), 0, 255)

    clean_rgba = np.dstack([clean_rgb.astype(np.uint8), (alpha * 255).astype(np.uint8)])
    logo_img = Image.fromarray(clean_rgba, "RGBA")
    w, h = logo_img.size
    print(f"Clean logo size: {w}x{h}")

    # Save PNG
    png_path = os.path.join(VIEWER_DIR, "propwire-logo-full.png")
    logo_img.save(png_path, format="PNG")
    print(f"Saved: {png_path}")

    # Generate base64 data URL for SVG
    with open(png_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("utf-8")

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" fill="none">
  <image href="data:image/png;base64,{b64_data}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet"/>
</svg>"""

    for svg_name in ["propwire-logo.svg", "propwire-logo-dark.svg"]:
        svg_path = os.path.join(VIEWER_DIR, svg_name)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_content)
        print(f"Saved: {svg_path}")

    # 2. Extract standalone stylized lightning "P" emblem
    # "P" ends around x = 234 relative to crop
    p_arr = clean_rgba[:, :234, :]
    p_alpha = p_arr[:, :, 3] > 20
    coords = np.argwhere(p_alpha)
    py0, px0 = coords.min(axis=0)
    py1, px1 = coords.max(axis=0) + 1
    p_emblem = Image.fromarray(p_arr[py0:py1, px0:px1], "RGBA")
    pw, ph = p_emblem.size
    print(f"P emblem bounding size: {pw}x{ph}")

    # Generate icon suite on dark obsidian #070709 canvas
    icon_sizes = [
        ("apple-touch-icon.png", 180),
        ("apple-touch-icon-180x180.png", 180),
        ("apple-touch-icon-167x167.png", 167),
        ("apple-touch-icon-152x152.png", 152),
        ("apple-touch-icon-120x120.png", 120),
        ("apple-touch-icon-precomposed.png", 180),
        ("apple-touch-icon-180x180-precomposed.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("favicon-32x32.png", 32),
        ("favicon-16x16.png", 16),
        ("favicon.png", 32),
    ]

    for filename, size in icon_sizes:
        icon_bg = Image.new("RGBA", (size, size), (7, 7, 9, 255))
        # Inner padding ~18%
        target_size = int(size * 0.68)
        scale = target_size / max(pw, ph)
        new_w, new_h = max(1, int(pw * scale)), max(1, int(ph * scale))
        scaled_p = p_emblem.resize((new_w, new_h), Image.Resampling.LANCZOS)
        offset_x = (size - new_w) // 2
        offset_y = (size - new_h) // 2
        icon_bg.alpha_composite(scaled_p, (offset_x, offset_y))

        out_path = os.path.join(VIEWER_DIR, filename)
        icon_bg.save(out_path, format="PNG")
        print(f"Generated icon: {filename} ({size}x{size})")

    # Favicon SVG
    with open(os.path.join(VIEWER_DIR, "icon-192.png"), "rb") as f:
        icon_b64 = base64.b64encode(f.read()).decode("utf-8")
    fav_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192">
  <image href="data:image/png;base64,{icon_b64}" width="192" height="192"/>
</svg>"""
    with open(os.path.join(VIEWER_DIR, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(fav_svg)
    with open(os.path.join(VIEWER_DIR, "propwire-icon.svg"), "w", encoding="utf-8") as f:
        f.write(fav_svg)
    print("Generated favicon.svg & propwire-icon.svg")

if __name__ == "__main__":
    process_logo()
