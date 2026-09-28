#!/usr/bin/env python3
"""Dedup a raw Whisper/Groq SRT per the transcribe-video skill's srt-cleaning.md:
remove malformed entries (end < start), detect timestamp reversals at chunk
boundaries, drop the before-entries that word-overlap the after-entries, then
renumber. Also word-diffs the joined SRT text against the .txt and reports
dropped words (chunk-boundary word losses; recover them while writing the .md).

Usage (writes <out>.dedup.srt next to the input; run from any cwd):
    python3 dedup_srt.py RAW.srt [--out suffixed_copy_path]
"""
import argparse
import difflib
import re
import sys
from pathlib import Path


def ts_to_s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(path: Path):
    entries = []
    for block in path.read_text().strip().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        entries.append({"start": start, "end": end, "text": " ".join(lines[2:]).strip()})
    return entries


def words(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9']+", text.lower()))


def dedup(entries):
    kept = [e for e in entries if e["end"] >= e["start"] - 1e-9]
    removed_malformed = len(entries) - len(kept)
    removed_overlap = 0
    marked = set()
    for i in range(1, len(kept)):
        if kept[i]["start"] < kept[i - 1]["start"] - 0.5:  # reversal point
            for b in range(max(0, i - 5), i):
                for a in range(i, min(len(kept), i + 6)):
                    shared = words(kept[b]["text"]) & words(kept[a]["text"])
                    wa, wb = words(kept[b]["text"]), words(kept[a]["text"])
                    if len(shared) >= 3 and (len(shared) >= len(wa) * 0.5 or len(shared) >= len(wb) * 0.5):
                        marked.add(b)
                        break
                else:
                    continue
                break
    final = [e for j, e in enumerate(kept) if j not in marked]
    removed_overlap = len(kept) - len(final)
    for n, e in enumerate(final, 1):
        e["n"] = n
    return final, removed_malformed, removed_overlap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt", type=Path)
    ap.add_argument("--txt", type=Path, help="companion .txt for the word-drop diff")
    args = ap.parse_args()

    entries = parse_srt(args.srt)
    if not entries:
        sys.exit(f"no SRT entries parsed from {args.srt}")
    final, n_malformed, n_overlap = dedup(entries)
    out = args.srt.with_suffix(".dedup.srt")
    out.write_text("\n\n".join(
        f"{e['n']}\n{int(e['start']//3600):02d}:{int(e['start']%3600//60):02d}:{e['start']%60:06.3f}".replace(".", ",")
        + " --> "
        + f"{int(e['end']//3600):02d}:{int(e['end']%3600//60):02d}:{e['end']%60:06.3f}".replace(".", ",")
        + f"\n{e['text']}" for e in final) + "\n")
    print(f"{len(entries)} entries -> {len(final)} (malformed removed: {n_malformed}, overlap removed: {n_overlap})")
    print(f"wrote {out}")

    if args.txt and args.txt.is_file():
        srt_words = re.findall(r"[A-Za-z0-9']+", " ".join(e["text"] for e in final).lower())
        txt_words = re.findall(r"[A-Za-z0-9']+", args.txt.read_text().lower())
        sm = difflib.SequenceMatcher(None, srt_words, txt_words, autojunk=False)
        drops = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag in ("delete", "replace") and j2 > j1:
                dropped = txt_words[j1:j2]
                if len(dropped) <= 12:
                    ctx = " ".join(txt_words[max(0, j1 - 4):j1] + ["»"] + dropped + ["«"] + txt_words[j2:j2 + 4])
                    drops.append(ctx)
        print(f"\nwords in .txt missing from SRT ({len(drops)} spots) — add to correction list if meaning-bearing:")
        for d in drops[:40]:
            print(f"  - {d}")


if __name__ == "__main__":
    main()
