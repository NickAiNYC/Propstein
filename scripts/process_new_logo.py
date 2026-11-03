"""
Process user-uploaded PropWire logo lockup:
1. Convert black text/mark to pure white #FFFFFF with clean anti-aliasing.
2. Keep electric cyan #28C4FA / #00D2FF on 'WIRE' and the lightning bolt accent.
3. Clean up alpha edges and export crisp header lockups (propwire-logo.svg, propwire-logo-full.png).
4. Extract standalone 'P' lightning bolt mark and render Apple touch icons & favicons.
"""

from __future__ import annotations
import base64
import io
import math
import numpy as np
from PIL import Image, ImageFilter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VIEWER_DIR = BASE_DIR / "viewer"
UPLOAD_FILE = Path("/Users/nick/.gemini/antigravity-ide/brain/e6a06847-5d35-427f-8387-bb239bf470ec/.user_uploaded/media_1793162727705.png")

def main():
    if not UPLOAD_FILE.exists():
        raise FileNotFoundError(f"Upload not found: {UPLOAD_FILE}")

    src_img = Image.open(UPLOAD_FILE).convert("RGBA")
    arr = np.array(src_img)

    # 1. Bounding box crop
    alpha = arr[:, :, 3]
    y_idx, x_idx = np.where(alpha > 15)
    ymin, ymax = y_idx.min(), y_idx.max()
    xmin, xmax = x_idx.min(), x_idx.max()

    cropped = arr[ymin:ymax+1, xmin:xmax+1].copy()

    # 2. Clean separation: Cyan vs Black
    r = cropped[:, :, 0].astype(float)
    g = cropped[:, :, 1].astype(float)
    b = cropped[:, :, 2].astype(float)
    a = cropped[:, :, 3].astype(float)

    # Cyan criteria: blue is high and significantly higher than red
    # In uploaded image, cyan is around RGB(40, 196, 250)
    is_cyan = (b > 110) & (b > r + 35) & (g > 100)

    # Colorize:
    # Black parts -> White #FFFFFF (255, 255, 255)
    # Cyan parts -> Vibrant Electric Sky #00D2FF (0, 210, 255)
    white_logo = cropped.copy()
    
    # Where black/dark and visible: convert to pure white, retaining alpha
    mask_white = (~is_cyan) & (a > 10)
    white_logo[mask_white, 0] = 255
    white_logo[mask_white, 1] = 255
    white_logo[mask_white, 2] = 255

    # Enhance cyan vibrancy
    mask_cyan = is_cyan & (a > 10)
    white_logo[mask_cyan, 0] = np.clip(white_logo[mask_cyan, 0] * 0.8, 0, 40).astype(np.uint8)
    white_logo[mask_cyan, 1] = np.clip(white_logo[mask_cyan, 1] * 1.05, 190, 220).astype(np.uint8)
    white_logo[mask_cyan, 2] = 255

    img_white_full = Image.fromarray(white_logo)

    # Add 4:1 padding so lockup sits perfectly in 208x52 / 176x44 / 136x34 header brand box
    w, h = img_white_full.size
    target_aspect = 4.0
    if w / h < target_aspect:
        # Add horizontal padding
        new_w = int(h * target_aspect)
        pad_x = (new_w - w) // 2
        padded = Image.new("RGBA", (new_w, h), (0, 0, 0, 0))
        padded.paste(img_white_full, (pad_x, 0))
        img_white_header = padded
    else:
        # Add vertical padding
        new_h = int(w / target_aspect)
        pad_y = (new_h - h) // 2
        padded = Image.new("RGBA", (w, new_h), (0, 0, 0, 0))
        padded.paste(img_white_full, (0, pad_y))
        img_white_header = padded

    # Save header full png
    out_png = VIEWER_DIR / "propwire-logo-full.png"
    img_white_header.save(out_png, "PNG")
    print(f"Saved {out_png} ({img_white_header.size})")

    # Embed as high-DPI base64 in propwire-logo.svg
    buffered = io.BytesIO()
    img_white_header.save(buffered, format="PNG")
    b64_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    hw, hh = img_white_header.size
    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {hw} {hh}" width="{hw}" height="{hh}" fill="none">
  <image href="data:image/png;base64,{b64_str}" width="{hw}" height="{hh}" />
</svg>'''
    
    out_svg = VIEWER_DIR / "propwire-logo.svg"
    out_svg.write_text(svg_content, encoding="utf-8")
    print(f"Saved {out_svg}")

    # Also dark theme version (for light mode: black text + cyan WIRE)
    dark_logo = cropped.copy()
    mask_dark = (~is_cyan) & (a > 10)
    dark_logo[mask_dark, 0] = 11
    dark_logo[mask_dark, 1] = 14
    dark_logo[mask_dark, 2] = 20
    img_dark_full = Image.fromarray(dark_logo)
    
    if w / h < target_aspect:
        padded_dark = Image.new("RGBA", (int(h * target_aspect), h), (0, 0, 0, 0))
        padded_dark.paste(img_dark_full, ((int(h * target_aspect) - w) // 2, 0))
    else:
        padded_dark = Image.new("RGBA", (w, int(w / target_aspect)), (0, 0, 0, 0))
        padded_dark.paste(img_dark_full, (0, (int(w / target_aspect) - h) // 2))
        
    buf_dark = io.BytesIO()
    padded_dark.save(buf_dark, format="PNG")
    b64_dark = base64.b64encode(buf_dark.getvalue()).decode("utf-8")
    svg_dark = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {hw} {hh}" width="{hw}" height="{hh}" fill="none">
  <image href="data:image/png;base64,{b64_dark}" width="{hw}" height="{hh}" />
</svg>'''
    (VIEWER_DIR / "propwire-logo-dark.svg").write_text(svg_dark, encoding="utf-8")
    print("Saved propwire-logo-dark.svg")

    # 3. Extract the standalone 'P' lightning bolt mark for iOS & Favicons
    # In white_logo, the 'P' extends from x=0 to approx x=280
    # Let's cleanly isolate the mark
    p_mark_arr = white_logo[:, :280].copy()
    
    # Clean any pixels from the 'R' that tuck under the P overhang
    # The 'R' only exists below y > 110 for x > 250
    for y in range(p_mark_arr.shape[0]):
        for x in range(240, 280):
            # If x > 250 and y in lower half, check if it's connected to R
            if y > 115 and x > 250:
                p_mark_arr[y, x, 3] = 0

    # Crop to P mark bounding box
    p_alpha = p_mark_arr[:, :, 3]
    py_idx, px_idx = np.where(p_alpha > 20)
    p_cropped = p_mark_arr[py_idx.min():py_idx.max()+1, px_idx.min():px_idx.max()+1]
    p_img = Image.fromarray(p_cropped)
    
    # Save standalone icon SVG
    buf_p = io.BytesIO()
    p_img.save(buf_p, format="PNG")
    b64_p = base64.b64encode(buf_p.getvalue()).decode("utf-8")
    pw, ph = p_img.size
    p_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {pw} {ph}" width="{pw}" height="{ph}" fill="none">
  <image href="data:image/png;base64,{b64_p}" width="{pw}" height="{ph}" />
</svg>'''
    (VIEWER_DIR / "propwire-icon.svg").write_text(p_svg, encoding="utf-8")
    print(f"Saved propwire-icon.svg ({p_img.size})")

    # Render square app icons on obsidian canvas #070708
    CANVAS_COLOR = (7, 7, 8, 255)
    
    def make_square_icon(size: int, frac: float = 0.62) -> Image.Image:
        icon = Image.new("RGBA", (size, size), CANVAS_COLOR)
        target_h = int(size * frac)
        scale = target_h / p_img.height
        target_w = int(p_img.width * scale)
        
        resized = p_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # Center horizontally and vertically
        ox = (size - target_w) // 2
        oy = (size - target_h) // 2
        icon.paste(resized, (ox, oy), resized)
        return icon

    # Generate all iOS and PWA targets
    icon_180 = make_square_icon(180, 0.64)
    for name in [
        "apple-touch-icon.png",
        "apple-touch-icon-precomposed.png",
        "apple-touch-icon-180x180.png",
        "apple-touch-icon-180x180-precomposed.png",
    ]:
        icon_180.save(VIEWER_DIR / name, "PNG")
        print(f"Saved {name}")

    make_square_icon(120, 0.64).save(VIEWER_DIR / "apple-touch-icon-120x120.png", "PNG")
    make_square_icon(152, 0.64).save(VIEWER_DIR / "apple-touch-icon-152x152.png", "PNG")
    make_square_icon(167, 0.64).save(VIEWER_DIR / "apple-touch-icon-167x167.png", "PNG")
    make_square_icon(192, 0.58).save(VIEWER_DIR / "icon-192.png", "PNG")
    make_square_icon(512, 0.58).save(VIEWER_DIR / "icon-512.png", "PNG")
    make_square_icon(32, 0.72).save(VIEWER_DIR / "favicon-32x32.png", "PNG")
    make_square_icon(16, 0.72).save(VIEWER_DIR / "favicon-16x16.png", "PNG")
    make_square_icon(32, 0.72).save(VIEWER_DIR / "favicon.png", "PNG")

    # Favicon SVG
    fav_180 = make_square_icon(180, 0.64)
    buf_fav = io.BytesIO()
    fav_180.save(buf_fav, format="PNG")
    b64_fav = base64.b64encode(buf_fav.getvalue()).decode("utf-8")
    favicon_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180" width="180" height="180" fill="none">
  <rect width="180" height="180" fill="#070708"/>
  <image href="data:image/png;base64,{b64_fav}" width="180" height="180" />
</svg>'''
    (VIEWER_DIR / "favicon.svg").write_text(favicon_svg, encoding="utf-8")
    print("Saved favicon.svg")

if __name__ == "__main__":
    main()
