#!/usr/bin/env python3
"""OCR kept slide images into a time-tagged JSON + readable index.

Input: a directory of slide PNGs named `..._<MmSSs>.png` (the convention of
extract_slides.py and the slides/ index). Each file's capture timestamp is
parsed from the name; each slide's end time is the next slide's start (the
last slide runs to the video end, passed via --duration).

Output (next to the images unless --out given):
    slides_ocr.json   [{file, start_s, end_s, start "MmSSs", ocr}]
    slides_ocr.md     readable index: per slide, time range + OCR text

Requires tesseract on PATH. OCR quality on rendered slides is high (large
type, high contrast); treat the text as ground truth for technical terms,
formulas (linearized), and numbers when correcting a transcript.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

NAME_TS = re.compile(r"(?:(\d{1,2})h)?(\d{1,3})m(\d{2})s\.png$")


def mmss_to_s(ts: str) -> int:
    m = NAME_TS.search(ts)
    h = int(m.group(1)) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def preprocess(png: Path) -> Path:
    """Grayscale + 2x upscale + autocontrast: helps dark themes, dense code,
    and low-contrast renders. Returns a sidecar file (caller removes it)."""
    from PIL import Image, ImageOps
    img = Image.open(png).convert("L")
    w, h = img.size
    if max(w, h) < 2600:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    out = png.with_suffix(".ocr_ready.png")
    img.save(out)
    return out


def ocr(png: Path) -> str:
    src = preprocess(png)
    try:
        best = ""
        for psm in ("1", "6"):           # 1: auto layout; 6: uniform block fallback
            out = subprocess.run(["tesseract", str(src), "stdout", "--psm", psm],
                                 capture_output=True, text=True)
            if out.returncode != 0:
                print(f"warn: tesseract failed on {png.name} (psm {psm}): "
                      f"{out.stderr.strip()[:120]}", file=sys.stderr)
                continue
            text = "\n".join(ln.strip() for ln in out.stdout.splitlines() if ln.strip())
            if len(text) > len(best):
                best = text
            if len(best.split()) > 25:   # good yield already; skip the fallback
                break
        return best
    finally:
        Path(src).unlink(missing_ok=True)


def ocr_similarity(a: str, b: str) -> float:
    """Jaccard similarity of two OCR texts' word sets (0..1). Near-1 between
    *consecutive* slides means the same frame was captured twice — the deck
    advanced mid-window, so a slide between the two was likely missed."""
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slides_dir", help="dir of slide PNGs named ..._<MmSSs>.png")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="video duration in seconds (end time for the last slide)")
    ap.add_argument("--out", default="", help="output basename (default slides_ocr)")
    args = ap.parse_args()
    if shutil.which("tesseract") is None:
        sys.exit("tesseract not found on PATH (install: tesseract-ocr)")
    d = Path(args.slides_dir)
    named = [p for p in d.glob("*.png") if NAME_TS.search(p.name)]
    pngs = sorted(named, key=lambda p: mmss_to_s(p.name))
    if not pngs:
        sys.exit(f"no <..._MmSSs>.png slide images in {d}")
    dur = args.duration
    rows = []
    for i, p in enumerate(pngs):
        start_s = mmss_to_s(p.name)
        if i + 1 < len(pngs):
            end_s = mmss_to_s(pngs[i + 1].name)
        elif dur:
            end_s = int(dur)
        else:
            end_s = start_s + 600
            print("warn: --duration not given; last slide window set to +600s", file=sys.stderr)
        text = ocr(p)
        if len(text.split()) < 5:
            print(f"warn: {p.name} OCR yielded <5 words - check the slide image "
                  f"(dark theme, dense code, or a non-slide frame)", file=sys.stderr)
        rows.append({"file": p.name, "start_s": start_s, "end_s": end_s,
                     "start": f"{start_s // 60}m{start_s % 60:02d}s", "ocr": text})
        print(f"{p.name}: {len(text)} chars, {rows[-1]['start']}–{end_s // 60}m{end_s % 60:02d}s")
    base = args.out or "slides_ocr"
    (d / f"{base}.json").write_text(json.dumps(rows, indent=1))
    md = ["# Slide OCR index", "",
          "| Slide | On screen | OCR text |", "|---|---|---|"]
    for r in rows:
        first = " ".join(r["ocr"].split())[:400]
        md.append(f"| {r['file']} | {r['start']}–{r['end_s'] // 60}m{r['end_s'] % 60:02d}s | {first} |")
    dupes = [(rows[i], rows[i + 1]) for i in range(len(rows) - 1)
             if ocr_similarity(rows[i]["ocr"], rows[i + 1]["ocr"]) > 0.75]
    if dupes:
        lines = ["", "## Possible duplicate captures", "",
                 "Consecutive slides with near-identical OCR — the deck likely advanced "
                 "mid-window, so the first of each pair may be the *next* slide and a "
                 "slide in between was missed. Re-check the video around the earlier "
                 "capture timestamp and re-extract if needed (Read the PNGs to confirm).", ""]
        for a, b in dupes:
            lines.append(f"- `{a['file']}` ≈ `{b['file']}`")
            print(f"warn: possible duplicate capture: {a['file']} ≈ {b['file']} "
                  f"(a slide between them may be missing)", file=sys.stderr)
        md.extend(lines)
    (d / f"{base}.md").write_text("\n".join(md) + "\n")
    print(f"wrote {d}/{base}.json and {base}.md")


if __name__ == "__main__":
    main()
