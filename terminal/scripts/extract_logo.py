#!/usr/bin/env python3
"""Extract the PropStein logo from the uploaded brand image.

The source is a 1024x1024 PNG: 'PROPSTEIN' wordmark (oversized lightning-P
in blue gradient + chrome 'ROPSTEIN') on a dark charcoal gradient.
Output: transparent-background assets for the app.
  public/brand/lockup.png   full wordmark, tight crop, alpha from luminance
  public/brand/mark.png     the lightning-P alone
  public/brand/icon-*.png   icon sizes composited on graphite rounded square
  public/brand/og.png       1200x630 social card
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os

SRC = "/home/z/my-project/upload/pasted_image_1793761041509.png"
OUT = "/home/z/my-project/public/brand"
os.makedirs(OUT, exist_ok=True)

im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()

# --- background level estimate: sample corners ---
corners = []
for (x, y) in [(8, 8), (W - 9, 8), (8, H - 9), (W - 9, H - 9), (W // 2, 6), (6, H // 2)]:
    r, g, b = px[x, y]
    corners.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
BG = max(corners)  # conservative: use brightest corner as bg reference
CUT = min(BG + 18, 70)  # cutoff: anything above this is logo or glow

# --- build alpha channel from luminance ---
lum = im.convert("L")
lp = lum.load()

minx, miny, maxx, maxy = W, H, 0, 0
alpha_pix = Image.new("L", (W, H), 0)
ap = alpha_pix.load()
for y in range(H):
    for x in range(W):
        v = lp[x, y]
        if v > CUT:
            a = min(255, int((v - CUT) * 255 / 70))
            ap[x, y] = a
            if x < minx: minx = x
            if x > maxx: maxx = x
            if y < miny: miny = y
            if y > maxy: maxy = y

print(f"BG={BG:.1f} CUT={CUT} bbox=({minx},{miny})-({maxx},{maxy})")

M = 6
box = (max(0, minx - M), max(0, miny - M), min(W, maxx + M + 1), min(H, maxy + M + 1))
rgba = im.convert("RGBA")
rgba.putalpha(alpha_pix)
lockup = rgba.crop(box)

a = lockup.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.6))
lockup.putalpha(a)
lockup.save(f"{OUT}/lockup.png")
print("lockup:", lockup.size)

# --- split the P from the rest via blue-dominance segmentation ---
# The P is a blue gradient (B-R > 35); 'ROPSTEIN' is silver (B-R <= 25).
lw, lh = lockup.size
lrgb = lockup.convert("RGBA").load()
minbx, maxbx = lw, 0
for y in range(lh):
    for x in range(lw):
        r, g, b, al = lrgb[x, y]
        if al > 40 and (b - r) > 35:
            if x < minbx: minbx = x
            if x > maxbx: maxbx = x
print("blue-dominant cols:", minbx, maxbx)

mark = lockup.crop((max(0, minbx - 5), 0, maxbx + 1, lh))
# erase any non-blue stray pixels at the right boundary (R's left edge)
mp = mark.load()
for y in range(mark.height):
    for x in range(mark.width):
        r, g, b, al = mp[x, y]
        if al > 0 and not (b - r) > 20:
            mp[x, y] = (r, g, b, 0)
ma = mark.getchannel("A")
mb = ma.getbbox()
mark = mark.crop((max(0, mb[0] - 2), max(0, mb[1] - 2), min(mark.width, mb[2] + 3), min(mark.height, mb[3] + 3)))
mark.save(f"{OUT}/mark.png")
print("mark:", mark.size)

# --- icon: mark composited on graphite rounded square ---
def make_icon(size, radius_ratio=0.22, pad_ratio=0.16, bg1=(11, 13, 17), bg2=(26, 33, 42)):
    s = size
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    bg = Image.new("RGB", (s, s))
    dr = ImageDraw.Draw(bg)
    for y in range(s):
        t = y / max(1, s - 1)
        c = tuple(int(bg1[i] + (bg2[i] - bg1[i]) * t) for i in range(3))
        dr.line([(0, y), (s, y)], fill=c)
    mask = Image.new("L", (s, s), 0)
    d2 = ImageDraw.Draw(mask)
    r = int(s * radius_ratio)
    d2.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=255)
    icon.paste(bg, (0, 0), mask)
    pad = int(s * pad_ratio)
    mw = s - 2 * pad
    ratio = mw / mark.width
    mh = int(mark.height * ratio)
    if mh > s - 2 * pad:
        mh = s - 2 * pad
        ratio = mh / mark.height
        mw = int(mark.width * ratio)
    m2 = mark.resize((mw, mh), Image.LANCZOS)
    icon.alpha_composite(m2, ((s - mw) // 2, (s - mh) // 2))
    return icon

for size, name in [(32, "icon-32.png"), (180, "apple-touch-icon.png"), (512, "icon-512.png"), (192, "icon-192.png")]:
    make_icon(size).save(f"{OUT}/{name}")
    print("icon", name)

# --- OG image 1200x630 ---
og = Image.new("RGB", (1200, 630))
og1, og2 = (9, 11, 15), (21, 28, 38)
dr = ImageDraw.Draw(og)
for y in range(630):
    t = y / 629
    c = tuple(int(og1[i] + (og2[i] - og1[i]) * t) for i in range(3))
    dr.line([(0, y), (1199, y)], fill=c)

glow = Image.new("L", (1200, 630), 0)
gd = ImageDraw.Draw(glow)
gd.ellipse([280, 60, 980, 460], fill=36)
glow = glow.filter(ImageFilter.GaussianBlur(120))
accent = Image.new("RGB", (1200, 630), (56, 189, 248))
og.paste(Image.composite(accent, og, glow), (0, 0), glow)

target_w = 660
ratio = target_w / lockup.width
lh2 = int(lockup.height * ratio)
big = lockup.resize((target_w, lh2), Image.LANCZOS)
og.paste(big, ((1200 - target_w) // 2, 150), big)

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf", 30)
    mono = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 24)
except Exception:
    font = ImageFont.load_default()
    mono = font

def center_text(y, text, f, fill):
    w = dr.textlength(text, font=f)
    dr.text(((1200 - w) // 2, y), text, font=f, fill=fill)

center_text(150 + lh2 + 44, "Distributional player-prop research terminal", font, (163, 173, 188))
center_text(150 + lh2 + 92, "fair lines  ·  full distributions  ·  public audit", mono, (110, 120, 134))
og.save(f"{OUT}/og.png", quality=92)
print("og saved")

# --- verification report sheet ---
report = Image.new("RGB", (1400, 760), (11, 13, 17))
report.paste(lockup, (20, 20), lockup)
report.paste(mark, (20, 380), mark)
og_small = og.resize((660, 346), Image.LANCZOS)
report.paste(og_small, (700, 20))
icon512 = make_icon(300)
report.paste(icon512, (700, 400), icon512)
report.save("/tmp/logo-report.png")
print("report saved")
