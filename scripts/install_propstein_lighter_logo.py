#!/usr/bin/env python3
"""
Install PropStein official wordmark logo with the new lighter ice-blue 'P' and crisp white 'ROPSTEIN' text.
Source: media_1793263842457_b4e036ae.jpg
Outputs:
- viewer/propwire-logo-full.png & public/
- viewer/propstein-logo.png & public/
- propwire-logo.svg & viewer/propwire-logo.svg
- viewer/propstein-logo.svg
- propwire-logo-dark.svg & viewer/propwire-logo-dark.svg
- viewer/propstein-logo-dark.svg
- viewer/propstein-logo-dark.png
- favicon.svg, favicon.png, favicon-32x32.png, favicon-16x16.png
- icon-192.png, icon-512.png
"""

import base64
from pathlib import Path
from PIL import Image
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
VIEWER_DIR = BASE_DIR / "viewer"
PUBLIC_DIR = BASE_DIR / "public"
SRC_LOGO = Path("/Users/nick/.gemini/antigravity/brain/2cad483e-0c68-4ee9-a3c5-cc9cf22b3aec/.user_uploaded/media_1793263842457_b4e036ae.jpg")


def create_svg_wrapper(png_path: Path, width: int, height: int) -> str:
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" fill="none">
  <image href="data:image/png;base64,{b64}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet"/>
</svg>"""


def main():
    print(f"Processing lighter PropStein logo from: {SRC_LOGO}")
    img = Image.open(SRC_LOGO).convert("RGB")
    arr = np.array(img).astype(float)

    # 1. Dark navy background color from corners
    c1 = arr[:25, :25, :3].mean(axis=(0, 1))
    c2 = arr[:25, -25:, :3].mean(axis=(0, 1))
    c3 = arr[-25:, :25, :3].mean(axis=(0, 1))
    c4 = arr[-25:, -25:, :3].mean(axis=(0, 1))
    bg = (c1 + c2 + c3 + c4) / 4.0
    print(f"Measured background RGB: {bg}")

    # 2. Color difference matting
    diff = np.sqrt(np.sum((arr[:, :, :3] - bg) ** 2, axis=2))
    t_low = 8.0
    t_high = 65.0
    alpha = np.clip((diff - t_low) / (t_high - t_low), 0.0, 1.0)

    # 3. Unmultiply RGB to restore pure vibrant foreground
    fg_rgb = np.zeros_like(arr[:, :, :3])
    mask = alpha > 0.01
    for c in range(3):
        fg_rgb[mask, c] = np.clip((arr[mask, c] - (1.0 - alpha[mask]) * bg[c]) / alpha[mask], 0, 255)
    fg_rgb[~mask] = 0

    # Clean the white ROPSTEIN text: wherever R, G, B are neutral and bright (x > 240)
    x_indices = np.arange(arr.shape[1])[None, :]
    text_zone = (x_indices > 240) & (alpha > 0.1)
    is_neutral_white = (
        text_zone
        & (fg_rgb[:, :, 0] > 170)
        & (fg_rgb[:, :, 1] > 170)
        & (fg_rgb[:, :, 2] > 170)
        & (np.abs(fg_rgb[:, :, 0] - fg_rgb[:, :, 1]) < 35)
        & (np.abs(fg_rgb[:, :, 1] - fg_rgb[:, :, 2]) < 35)
    )
    # Snap white text to pure white
    fg_rgb[is_neutral_white] = 255.0

    rgba = np.dstack([fg_rgb.astype(np.uint8), (alpha * 255).astype(np.uint8)])

    # Crop with 12px padding
    y_idx, x_idx = np.where(alpha > 0.05)
    pad = 12
    y0 = max(0, y_idx.min() - pad)
    y1 = min(arr.shape[0], y_idx.max() + pad)
    x0 = max(0, x_idx.min() - pad)
    x1 = min(arr.shape[1], x_idx.max() + pad)

    cropped_rgba = rgba[y0:y1, x0:x1]
    logo_img = Image.fromarray(cropped_rgba, "RGBA")
    w, h = logo_img.size
    print(f"Full lighter logo size: {w}x{h}")

    # Save transparent PNGs (Dark Theme)
    png_paths = [
        VIEWER_DIR / "propwire-logo-full.png",
        PUBLIC_DIR / "propwire-logo-full.png",
        VIEWER_DIR / "propstein-logo.png",
        PUBLIC_DIR / "propstein-logo.png",
    ]
    for p in png_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        logo_img.save(p, format="PNG")
        print(f"Saved: {p}")

    # Save SVGs (dark theme)
    svg_dark_bg = create_svg_wrapper(png_paths[0], w, h)
    for p in [BASE_DIR / "propwire-logo.svg", VIEWER_DIR / "propwire-logo.svg", VIEWER_DIR / "propstein-logo.svg"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(svg_dark_bg)
        print(f"Saved: {p}")

    # 4. Light theme version:
    # Convert white ROPSTEIN text to deep obsidian #0b0e14, keeping the lighter sky-blue P
    light_rgba = np.copy(cropped_rgba)
    r, g, b, a = light_rgba[:, :, 0], light_rgba[:, :, 1], light_rgba[:, :, 2], light_rgba[:, :, 3]
    crop_x_indices = np.arange(w)[None, :]
    is_white_crop = (r > 150) & (g > 150) & (b > 150) & (a > 25) & (crop_x_indices > int(w * 0.24))

    # Darken white text to dark obsidian (#0b0e14)
    light_rgba[is_white_crop, 0] = 11
    light_rgba[is_white_crop, 1] = 14
    light_rgba[is_white_crop, 2] = 20

    light_img = Image.fromarray(light_rgba, "RGBA")
    light_png_path = VIEWER_DIR / "propstein-logo-dark.png"
    light_img.save(light_png_path, format="PNG")
    print(f"Saved: {light_png_path}")

    svg_light = create_svg_wrapper(light_png_path, w, h)
    for p in [BASE_DIR / "propwire-logo-dark.svg", VIEWER_DIR / "propwire-logo-dark.svg", VIEWER_DIR / "propstein-logo-dark.svg"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(svg_light)
        print(f"Saved: {p}")

    # 5. Favicon and App Icons:
    # Crop the lighter ice-blue lightning 'P' emblem
    p_crop_raw = cropped_rgba[:, :int(w * 0.31)]
    p_alpha = p_crop_raw[:, :, 3]
    py_idx, px_idx = np.where(p_alpha > 15)
    p_trimmed = p_crop_raw[py_idx.min():py_idx.max() + 1, px_idx.min():px_idx.max() + 1]
    p_img = Image.fromarray(p_trimmed, "RGBA")

    # 512x512 Canvas: Obsidian dark (#060A12) with centered lighter ice-blue lightning P
    canvas_size = 512
    icon_canvas = Image.new("RGBA", (canvas_size, canvas_size), (6, 10, 18, 255))
    target_dim = int(canvas_size * 0.74)
    pw, ph = p_img.size
    scale = target_dim / max(pw, ph)
    new_pw, new_ph = int(pw * scale), int(ph * scale)
    p_resized = p_img.resize((new_pw, new_ph), Image.Resampling.LANCZOS)

    paste_x = (canvas_size - new_pw) // 2
    paste_y = (canvas_size - new_ph) // 2
    icon_canvas.paste(p_resized, (paste_x, paste_y), p_resized)

    # Save 512, 192, 32, 16
    for p in [BASE_DIR / "icon-512.png", VIEWER_DIR / "icon-512.png", PUBLIC_DIR / "icon-512.png"]:
        icon_canvas.save(p, format="PNG")
        print(f"Saved: {p}")

    icon_192 = icon_canvas.resize((192, 192), Image.Resampling.LANCZOS)
    for p in [BASE_DIR / "icon-192.png", VIEWER_DIR / "icon-192.png", PUBLIC_DIR / "icon-192.png"]:
        icon_192.save(p, format="PNG")
        print(f"Saved: {p}")

    icon_32 = icon_canvas.resize((32, 32), Image.Resampling.LANCZOS)
    for p in [VIEWER_DIR / "favicon-32x32.png", PUBLIC_DIR / "favicon-32x32.png", VIEWER_DIR / "favicon.png", PUBLIC_DIR / "favicon.png", BASE_DIR / "favicon.png"]:
        icon_32.save(p, format="PNG")
        print(f"Saved: {p}")

    icon_16 = icon_canvas.resize((16, 16), Image.Resampling.LANCZOS)
    for p in [VIEWER_DIR / "favicon-16x16.png", PUBLIC_DIR / "favicon-16x16.png"]:
        icon_16.save(p, format="PNG")
        print(f"Saved: {p}")

    # Favicon SVG (transparent background with lighter ice-blue P)
    fav_canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    scale_fav = 228 / max(pw, ph)
    fpw, fph = int(pw * scale_fav), int(ph * scale_fav)
    p_fav = p_img.resize((fpw, fph), Image.Resampling.LANCZOS)
    fav_canvas.paste(p_fav, ((256 - fpw) // 2, (256 - fph) // 2), p_fav)
    temp_fav_png = VIEWER_DIR / "temp_favicon.png"
    fav_canvas.save(temp_fav_png, format="PNG")

    svg_fav = create_svg_wrapper(temp_fav_png, 256, 256)
    for p in [BASE_DIR / "favicon.svg", VIEWER_DIR / "favicon.svg"]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(svg_fav)
        print(f"Saved: {p}")

    if temp_fav_png.exists():
        temp_fav_png.unlink()

    print("🎉 Official PropStein lighter logo and icon suite installed successfully!")


if __name__ == "__main__":
    main()

