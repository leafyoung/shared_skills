#!/usr/bin/env python3
"""Extract per-page PNGs + per-page text from a PDF (slide deck or document).

One pdftoppm pass renders every page at --dpi; one pdftotext pass dumps the
text layer, split per page on form feeds. Static sources need no scene-cut
detection — every page is a page; the agent reviews contact_sheet.jpg, drops
covers/dividers/boilerplate, and indexes the rest (slides-teach SKILL.md
Step 2).

Usage — cd into the unit directory first; the script reads the PDF from argv
and writes only into the fixed relative folder `pages_raw/`:

    cd unit1_intro
    python3 ~/.agents/skills/slides-teach/scripts/extract_pages.py source/deck.pdf \
        [--dpi 150]

Requires pdftoppm + pdftotext (poppler) on PATH and Pillow. Outputs in ./pages_raw/:
    p-NNN.png             full page render (NNN = 1-based source page number)
    text/page-NNN.txt     per-page text layer (-layout)
    contact_sheet.jpg     labeled grid of pages for review
    index.tsv             page, image, title guess (first text line), text chars
"""
import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

OUT = "pages_raw"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, shell=False, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=Path, help="source PDF (read-only)")
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow required: uv add pillow / pip install pillow")
    for tool in ("pdftoppm", "pdftotext"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} not found on PATH (install poppler)")
    if not args.pdf.is_file():
        sys.exit(f"no such PDF: {args.pdf}")

    (Path(OUT) / "text").mkdir(parents=True, exist_ok=True)

    proc = run(["pdftoppm", "-png", "-r", str(args.dpi), str(args.pdf), f"{OUT}/p"])
    if proc.returncode != 0:
        sys.exit(f"pdftoppm failed:\n{proc.stderr[-2000:]}")
    images = sorted(Path(OUT).glob("p-*.png"))
    if not images:
        sys.exit("pdftoppm produced no pages")
    # normalize poppler's variable-width numbering to p-NNN (3-digit, 1-based)
    for img in images:
        n = int(re.search(r"p-(\d+)\.png$", img.name).group(1))
        img = img.rename(Path(OUT, f"p-{n:03d}.png"))

    proc = run(["pdftotext", "-layout", str(args.pdf), "-"])
    if proc.returncode != 0:
        sys.exit(f"pdftotext failed:\n{proc.stderr[-2000:]}")
    texts = proc.stdout.split("\f")
    if len(texts) < len(images):
        sys.stderr.write(f"warning: {len(texts)} text pages vs {len(images)} images\n")

    rows, keepers = [], []
    for n in range(1, len(images) + 1):
        text = texts[n - 1] if n <= len(texts) else ""
        (Path(OUT) / "text" / f"page-{n:03d}.txt").write_text(text, encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = (lines[0] if lines else "(no text layer)")[:60]
        img = Path(OUT, f"p-{n:03d}.png")
        rows.append([n, img.name, title.replace("\t", " "), len(text)])
        label = f"p{n}: {title}"
        keepers.append((label, img))

    tsv = ["page\timage\ttitle_guess\ttext_chars"]
    tsv += ["\t".join(map(str, r)) for r in rows]
    Path(OUT, "index.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")

    from PIL import Image, ImageDraw

    cols, w = 4, 320
    thumbs = []
    for label, path in keepers:
        im = Image.open(path)
        im.thumbnail((w, w))
        canvas = Image.new("RGB", (w, im.height + 18), "white")
        canvas.paste(im, (0, 18))
        ImageDraw.Draw(canvas).text((4, 3), label, fill="black")
        thumbs.append(canvas)
    rows_n = math.ceil(len(thumbs) / cols)
    rh = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * w, rows_n * rh), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * w, (i // cols) * rh))
    sheet.save(f"{OUT}/contact_sheet.jpg", quality=82)

    print(f"{len(keepers)} pages in {OUT} (text layer in {OUT}/text)\n"
          f"review: {OUT}/contact_sheet.jpg + {OUT}/index.tsv\n"
          f"next: drop covers/dividers, move keepers to pages/ as "
          f"pageK_<slug>_pNNN.png, write pages/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
