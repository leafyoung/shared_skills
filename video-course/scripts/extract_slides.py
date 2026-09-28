#!/usr/bin/env python3
"""Extract slide candidate frames from a lecture video.

One-pass ffmpeg scan picks scene cuts plus a uniform sample grid, perceptual
hashes (dHash) the small frames, groups near-identical consecutive frames into
"slide windows", and captures one full-resolution frame per window, late in the
window (the convention: a slide is captured near the end of its on-screen run so
incremental builds have completed). Speaker cutaways and transition frames show
up as extra groups — the agent reviews contact_sheet.jpg and keeps/drops.

Usage — cd into the episode directory first; the script reads VIDEO from argv
and writes only into the fixed relative folder `slides_raw/`:

    cd epN_<slug>
    python3 extract_slides.py /path/to/video.mp4 \
        [--scene-threshold 0.25] [--sample-interval 20] \
        [--hash-distance 8] [--min-slide-seconds 15] [--backoff 5]

Requires ffmpeg/ffprobe on PATH and Pillow. Outputs in ./slides_raw/:
    chosen/sNN_<MmSSs>.png   full-res candidate, one per slide window
    contact_sheet.jpg        labeled grid of candidates for review
    candidates.tsv           per-group report (times, sample count, kept/rejected)
"""
import argparse
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

TS_RE = re.compile(r"pts_time:([0-9.]+)")
FPS_RE = re.compile(r"([0-9]+)/([0-9]+)")

OUT = "slides_raw"


def ffprobe_duration_fps(video: Path) -> tuple[float, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration,r_frame_rate",
         "-of", "default=noprint_wrappers=1", str(video)],
        check=True, capture_output=True, text=True, shell=False).stdout
    dur = float(re.search(r"duration=([0-9.]+)", out).group(1))
    num, den = FPS_RE.search(re.search(r"r_frame_rate=([0-9/]+)", out).group(1)).groups()
    return dur, float(num) / float(den)


def ffmpeg_scan(video: Path, fps: float, args) -> list[tuple[float, Path]]:
    """One ffmpeg pass: scene cuts + uniform grid, downscaled, with showinfo times."""
    os.makedirs(f"{OUT}/small", exist_ok=True)
    step = max(1, round(fps * args.sample_interval))
    vf = (f"select='gt(scene,{args.scene_threshold})+eq(n,0)"
          f"+eq(mod(n,{step}),0)',showinfo,scale=320:-2")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-vf", vf, "-fps_mode", "vfr", f"{OUT}/small/f%05d.png"],
        capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg scan failed:\n{proc.stderr[-2000:]}")
    times = [float(m.group(1)) for m in TS_RE.finditer(proc.stderr)]
    frames = sorted(Path(OUT, "small").glob("f*.png"))
    if len(times) != len(frames):
        # showinfo order == output order; pair by index, tolerate ffmpeg skips
        n = min(len(times), len(frames))
        sys.stderr.write(f"warning: {len(times)} showinfo times vs {len(frames)} files\n")
        times, frames = times[:n], frames[:n]
    return list(zip(times, frames))


def dhash(img: Image.Image, hash_size: int = 8) -> list[int]:
    g = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = list(g.getdata())
    bits = []
    for y in range(hash_size):
        row = px[y * (hash_size + 1):(y + 1) * (hash_size + 1)]
        bits.extend(1 if a > b else 0 for a, b in zip(row, row[1:]))
    return bits


def hamming(a: list[int], b: list[int]) -> int:
    return sum(x != y for x, y in zip(a, b))


def fmt_ts(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}m{s:02d}s"


def group_frames(samples, max_dist: int, min_seconds: float):
    """Chain frames into windows compared against each window's first frame;
    merge windows shorter than min_seconds into their predecessor."""
    groups = []  # each: {"hash", "samples": [(t, path)]}
    for t, path in samples:
        h = dhash(Image.open(path))
        if groups and hamming(groups[-1]["hash"], h) <= max_dist:
            groups[-1]["samples"].append((t, path))
        else:
            groups.append({"hash": h, "samples": [(t, path)]})
    merged = []
    for g in groups:
        span = g["samples"][-1][0] - g["samples"][0][0]
        if span < min_seconds and merged:
            merged[-1]["samples"].extend(g["samples"])
        else:
            merged.append(g)
    return merged


def capture_full_res(video: Path, t: float, name: str):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
         "-i", str(video), "-frames:v", "1", "-q:v", "2", f"{OUT}/chosen/{name}"],
        check=True, capture_output=True, text=True, shell=False)


def contact_sheet(chosen, cols: int = 4, w: int = 320):
    thumbs = []
    for label, path in chosen:
        im = Image.open(path)
        im.thumbnail((w, w))
        canvas = Image.new("RGB", (w, im.height + 18), "white")
        canvas.paste(im, (0, 18))
        ImageDraw.Draw(canvas).text((4, 3), label, fill="black")
        thumbs.append(canvas)
    rows = math.ceil(len(thumbs) / cols)
    rh = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * w, rows * rh), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * w, (i // cols) * rh))
    sheet.save(f"{OUT}/contact_sheet.jpg", quality=82)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path, help="lecture video file (read-only)")
    ap.add_argument("--scene-threshold", type=float, default=0.25)
    ap.add_argument("--sample-interval", type=float, default=20.0)
    ap.add_argument("--hash-distance", type=int, default=8)
    ap.add_argument("--min-slide-seconds", type=float, default=15.0)
    ap.add_argument("--backoff", type=float, default=5.0)
    args = ap.parse_args()

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow required: uv add pillow / pip install pillow")
    if not args.video.is_file():
        sys.exit(f"no such video: {args.video}")

    os.makedirs(f"{OUT}/chosen", exist_ok=True)
    duration, fps = ffprobe_duration_fps(args.video)
    print(f"video: {duration/60:.1f} min @ {fps:.2f} fps — scanning…")
    samples = ffmpeg_scan(args.video, fps, args)
    print(f"{len(samples)} sample frames (scene cuts + every {args.sample_interval:g}s)")

    groups = group_frames(samples, args.hash_distance, args.min_slide_seconds)

    rows, keepers = [], []
    for i, g in enumerate(groups):
        first, last = g["samples"][0][0], g["samples"][-1][0]
        grab = min(max(first + args.min_slide_seconds, last - args.backoff), last)
        grab = max(0.0, grab)
        name = f"s{i:02d}_{fmt_ts(grab)}.png"
        capture_full_res(args.video, grab, name)
        keepers.append((f"{name} [{fmt_ts(first)}–{fmt_ts(last)}]",
                        Path(OUT, "chosen", name)))
        rows.append([i, fmt_ts(first), fmt_ts(last), name, len(g["samples"]), "kept"])
    if len(keepers) > 60:
        sys.stderr.write("warning: >60 windows — scene threshold likely too low\n")

    tsv = ["group\tfirst\tlast\tfile\tn_samples\tstatus"]
    tsv += ["\t".join(map(str, r)) for r in rows]
    Path(OUT, "candidates.tsv").write_text("\n".join(tsv) + "\n")
    contact_sheet(keepers)
    print(f"{len(keepers)} slide candidates in {OUT}/chosen\n"
          f"review: {OUT}/contact_sheet.jpg + {OUT}/candidates.tsv\n"
          f"next: drop non-slides, move keepers to slides/ as "
          f"slideK_<slug>_<MmSSs>.png, write slides/README.md")


if __name__ == "__main__":
    main()
