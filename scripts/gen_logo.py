"""
Generate logo.png for Streamlit sidebar.

Streamlit st.logo(size="large") renders at ~60px tall.
We render at 2x (120px tall) for retina sharpness — no extreme downscale.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "assets" / "logo.png"

# ── Canvas: 2× retina of actual sidebar display size ─────────────────────────
H      = 120          # 2× of ~60px Streamlit display height
BG     = (10, 12, 20)
RADIUS = 8

# ── Fonts: sized for 120px tall canvas ───────────────────────────────────────
try:
    font_big = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 44)
    font_sub = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 26)
except OSError:
    font_big = ImageFont.load_default()
    font_sub = ImageFont.load_default()

# ── Measure text to compute exact canvas width ───────────────────────────────
_probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
w_big  = _probe.textbbox((0, 0), "Market",          font=font_big)[2]
w_sub  = _probe.textbbox((0, 0), "Sector Analysis", font=font_sub)[2]

PAD    = 10
bar_w  = 18
gap    = 8
n_bars = 3
icon_w = PAD + n_bars * bar_w + (n_bars - 1) * gap
tx     = icon_w + PAD + 8
W      = tx + max(w_big, w_sub) + PAD

# ── Draw ─────────────────────────────────────────────────────────────────────
img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS, fill=BG)

bars = [
    (PAD,                        28, H - 14, "#C62828"),
    (PAD + bar_w + gap,          14, H - 28, "#1565C0"),
    (PAD + (bar_w + gap) * 2,   34, H - 14, "#2E7D32"),
]
for x, y_top, y_bot, color in bars:
    draw.rectangle([x, y_top, x + bar_w, y_bot], fill=color)

for x, y_top, y_bot, _ in bars:
    cx = x + bar_w // 2
    draw.line([(cx, y_top - 8), (cx, y_top)],    fill="white", width=2)
    draw.line([(cx, y_bot),     (cx, y_bot + 8)], fill="white", width=2)

pts = [(b[0] + bar_w // 2, b[1]) for b in bars]
draw.line(pts, fill="#FFD600", width=3)
for px, py in pts:
    draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill="#FFD600")

draw.text((tx, 10), "Market",          font=font_big, fill="white")
draw.text((tx, 64), "Sector Analysis", font=font_sub, fill="white")

img.save(OUT, "PNG")
print(f"Saved: {OUT}  ({W}×{H})")
