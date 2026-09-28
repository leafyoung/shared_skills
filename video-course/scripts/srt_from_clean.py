#!/usr/bin/env python3
"""Rebuild a cleaned SRT from a finished .clean.md, timestamped by ONE global
difflib.SequenceMatcher alignment between the clean token stream and the deduped
raw SRT token stream (the approach the transcribe-video skill pinned in 0.19.0:
never per-sentence sliding windows — they cascade). Each markdown sentence gets
the time span of the matching blocks that overlap its token range; unmatched
(corrected/dropped) tokens interpolate between their matched neighbors.

Usage:
    python3 srt_from_clean.py CLEAN.md DEDUP.srt OUT.clean.srt

Conventions: headings and blockquote/citation lines are skipped; a sentence is
a line fragment ending in . ! ? — paragraphs are split on blank lines and
headings; table lines are skipped.
"""
import difflib
import re
import sys
from pathlib import Path


def srt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: Path):
    out = []
    for block in path.read_text().strip().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        m = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", lines[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        out.append({
            "start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
            "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
            "text": " ".join(lines[2:]),
        })
    return out


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def sentences_from_md(path: Path):
    sents = []  # (sentence_text, heading_stack_copy)
    heading = ""
    buf = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line)
            continue
        if line.startswith((">|", "|", "```", "---", "![")):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)   # links -> text
        line = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", line)        # bold/italics
        line = re.sub(r"`([^`]+)`", r"\1", line)                # code spans
        line = re.sub(r"\s+", " ", line)
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(“\"])", line):
            s = s.strip()
            if s:
                sents.append((s, heading))
    return sents


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    clean_md, dedup_srt, out_path = (Path(p) for p in sys.argv[1:4])

    sents = sentences_from_md(clean_md)
    raw = parse_srt(dedup_srt)
    raw_times = [(e["start"], e["end"]) for e in raw]
    raw_tokens: list[str] = []
    raw_tok_idx = []  # entry index per token
    for i, e in enumerate(raw):
        toks = tokenize(e["text"])
        raw_tokens.extend(toks)
        raw_tok_idx.extend([i] * len(toks))

    clean_tokens: list[str] = []
    sent_spans = []  # (start_tok, end_tok) into clean_tokens
    for s, _ in sents:
        toks = tokenize(s)
        sent_spans.append((len(clean_tokens), len(clean_tokens) + len(toks)))
        clean_tokens.extend(toks)

    sm = difflib.SequenceMatcher(None, raw_tokens, clean_tokens, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]

    def time_for_span(a_start: int, a_end: int) -> tuple[float, float]:
        # a_start/a_end are CLEAN-token coords; matching blocks carry both sides
        # (b.a = raw pos, b.b = clean pos). Overlap must be tested in CLEAN
        # coords; times always come from the RAW side.
        best_lo = best_hi = None
        for b in blocks:
            c_lo, c_hi = b.b, b.b + b.size  # clean token range of this block
            r_lo, r_hi = b.a, b.a + b.size  # raw token range of this block
            if c_hi <= a_start or c_lo >= a_end:
                if c_lo >= a_end and best_hi is None:
                    best_hi = (r_lo, r_hi)
                if c_hi <= a_start:
                    best_lo = (r_lo, r_hi)
                continue
            if best_lo is None:
                best_lo = (r_lo, r_hi)
            best_hi = (r_lo, r_hi)

        def entry_of(tok_i):
            return raw_tok_idx[min(tok_i, len(raw_tok_idx) - 1)]

        starts, ends = [], []
        if best_lo:
            starts.append(raw_times[entry_of(best_lo[0])][0])
        if best_hi:
            ends.append(raw_times[entry_of(best_hi[1] - 1)][1])
        if not starts or not ends:  # isolated unmatched sentence: interpolate later
            return (None, None)
        return (min(starts), max(ends))

    entries = []
    unresolved = []
    for (s_text, heading), (t0, t1) in zip(sents, sent_spans):
        st, en = time_for_span(t0, t1)
        entries.append([st, en, s_text, heading])
        if st is None:
            unresolved.append(len(entries) - 1)

    # interpolate unresolved spans between resolved neighbors
    resolved_times = [e[0] for e in entries if e[0] is not None]
    if resolved_times:
        for i in unresolved:
            prev_r = next((j for j in range(i - 1, -1, -1) if entries[j][0] is not None), None)
            next_r = next((j for j in range(i + 1, len(entries)) if entries[j][0] is not None), None)
            lo = entries[prev_r][1] if prev_r is not None else (resolved_times[0] if resolved_times else 0.0)
            hi = entries[next_r][0] if next_r is not None else lo + 4.0
            n = len([k for k in unresolved if (prev_r or -1) < k < (next_r or len(entries))]) or 1
            step = (hi - lo) / (n + 1)
            k = sum(1 for x in unresolved if prev_r is not None and x < i) % (n + 1) or 1
            entries[i][0] = lo + step * (k - 1 if k else 0)
            entries[i][1] = entries[i][0] + 3.0

    out = []
    prev_start = 0.0
    for n, (st, en, text, heading) in enumerate(entries, 1):
        st = st if st is not None else prev_start
        st = max(st, prev_start)  # enforce monotonic starts (metadata lines cluster at 0)
        en = max(en if en is not None else st + 3.0, st + 0.2)
        prev_start = st
        out.append(f"{n}\n{srt_ts(st)} --> {srt_ts(en)}\n{text}")
    out_path.write_text("\n\n".join(out) + "\n")
    print(f"{len(entries)} sentences -> {out_path}; unresolved spans: {len(unresolved)}")


if __name__ == "__main__":
    main()
