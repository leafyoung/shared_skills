#!/usr/bin/env python3
"""Normalize a downloaded YouTube auto-caption VTT into a raw timing layer (retrofit Step 1).

For episodes whose raw `.vtt`/`.srt` was never kept (courses that predate the
pipeline), YouTube's auto-generated captions are a serviceable fallback raw
layer: good enough to drive the verbatim `.verbal.md` and the correction
briefs, a notch below a fresh Whisper/Groq pass (punctuation-less, coarser
stamps — don't expect cue-level alignment against an older clean.md).

Two steps (keep the fetch under the caller's own execution permissions):

  1. Download the caption track only (subtitles are KBs, no video):
       yt-dlp --skip-download --write-auto-subs --sub-langs en --sub-format vtt \
             -o transcript/<slug>.raw https://www.youtube.com/watch?v=<id>
     YouTube rate-limits the caption endpoint (HTTP 429) after a burst of
     ~8-10 rapid fetches — when batching episodes, retry the 429s minutes
     apart rather than immediately.

  2. Normalize the rolling format into the plain raw timing file:
       python3 fetch_raw_captions.py transcript/<slug>.raw.en.vtt \
              --out transcript/<slug>.raw.vtt

The downloaded VTT is in YouTube's *rolling* two-line cue format (each cue
repeats the previous cue's last line, with inline <tag> markup and stray
blank-ish separator lines); this script strips the tags and drops the
repeated leading lines (via transcript_layers.dedup_rolling_vtt) — feeding
a rolling file raw would double every phrase in the verbal layer.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcript_layers import dedup_rolling_vtt  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="downloaded YouTube caption file, e.g. transcript/<slug>.raw.en.vtt")
    ap.add_argument("--out", default="",
                    help="raw timing file to write (default: source without the .en.vtt lang tag)")
    a = ap.parse_args()
    src = Path(a.source)
    if not src.is_file():
        sys.exit(f"not found: {src}")
    if a.out:
        out = Path(a.out)
    elif src.name.endswith(".en.vtt"):
        out = src.with_name(src.name[:-len(".en.vtt")] + ".vtt")
    else:
        out = src.with_suffix(".raw.vtt")
    text = dedup_rolling_vtt(src)
    out.write_text(text)
    n_cues = sum(1 for ln in text.splitlines() if "-->" in ln)
    print(f"{n_cues} cues -> {out} (rolling format normalized from {src.name})")


if __name__ == "__main__":
    main()
