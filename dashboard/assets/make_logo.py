"""Build BioTerm's logo SVGs (logo.svg = mark + wordmark, mark.svg = favicon/tile).

The wordmark is Inter (SIL Open Font License 1.1) converted to glyph outlines, so it
renders identically inside an <img> - st.logo can't load web fonts. Inter comes from
the video package's @fontsource/inter.

    cd video && npm install          # once, for the font files
    uv run --with fonttools --with brotli python dashboard/assets/make_logo.py dashboard/assets
"""
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FILES = Path(__file__).resolve().parents[2] / "video/node_modules/@fontsource/inter/files"
OUT = Path(sys.argv[1])


def word(text, weight, x0, baseline, size, tracking=-0.02):
    f = TTFont(FILES / f"inter-latin-{weight}-normal.woff2")
    upm = f["head"].unitsPerEm
    gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    s = size / upm
    parts, x = [], x0
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x, baseline)))
        parts.append(pen.getCommands())
        x += hmtx[g][0] * s + tracking * size
    return " ".join(parts), x


# --- mark: 32x32 tile; hexagon (a benzene ring - chemistry) cut by a rising
# price pulse that exits the ring (a signal breaking out)
MARK = """
  <defs>
    <linearGradient id="btg" x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#3D84FA"/><stop offset="1" stop-color="#5B4CE6"/>
    </linearGradient>
  </defs>
  <rect width="32" height="32" rx="8" fill="url(#btg)"/>
  <rect x=".5" y=".5" width="31" height="31" rx="7.5" fill="none" stroke="#FFFFFF" stroke-opacity=".14"/>
  <path d="M16 6.6 24.1 11.3V20.7L16 25.4 7.9 20.7V11.3Z" fill="none" stroke="#FFFFFF"
        stroke-opacity=".5" stroke-width="1.7" stroke-linejoin="round"/>
  <path d="M5.2 19.4H10.4L12.9 14.9 16.2 21.2 19.1 13.6 22.2 10.9" fill="none" stroke="#FFFFFF"
        stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="24.6" cy="8.8" r="2.1" fill="#FFFFFF"/>
"""

bio, x = word("Bio", 700, 42, 22.6, 19)
term, x = word("Term", 500, x - 0.9, 22.6, 19)
width = int(x + 3)

(OUT / "mark.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32" '
    f'role="img" aria-label="BioTerm">{MARK}</svg>\n')
(OUT / "logo.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 32" width="{width}" '
    f'height="32" role="img" aria-label="BioTerm">{MARK}'
    f'  <path d="{bio}" fill="#E6EAF2"/>\n  <path d="{term}" fill="#8FB4FF"/>\n</svg>\n')
print("width", width)
