"""Tile review stills into labelled contact sheets (output/sheets/sheet_N.png)."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

src = Path(sys.argv[1] if len(sys.argv) > 1 else "output/stills")
prefix = sys.argv[2] if len(sys.argv) > 2 else "BioTerm16x9"
cols, tw = 2, 960
files = sorted(src.glob(f"{prefix}_*.png"))
out = Path("output/sheets"); out.mkdir(parents=True, exist_ok=True)
per = 6 if prefix.endswith("16x9") else 6
for s in range(0, len(files), per):
    group = files[s : s + per]
    ims = [Image.open(f).convert("RGB") for f in group]
    th = int(ims[0].height * tw / ims[0].width)
    if prefix.endswith("9x16"):
        cols_, tw_ = 3, 420
        th_ = int(ims[0].height * tw_ / ims[0].width)
    else:
        cols_, tw_, th_ = cols, tw, th
    rows = (len(ims) + cols_ - 1) // cols_
    sheet = Image.new("RGB", (cols_ * tw_ + (cols_ + 1) * 8, rows * th_ + (rows + 1) * 8), (40, 40, 40))
    for i, (im, f) in enumerate(zip(ims, group)):
        x, y = 8 + (i % cols_) * (tw_ + 8), 8 + (i // cols_) * (th_ + 8)
        sheet.paste(im.resize((tw_, th_), Image.LANCZOS), (x, y))
        ImageDraw.Draw(sheet).text((x + 8, y + 6), f.stem.split("_")[-1] + "s", fill=(255, 220, 0))
    sheet.save(out / f"{prefix}_sheet_{s // per}.png")
    print(out / f"{prefix}_sheet_{s // per}.png")
