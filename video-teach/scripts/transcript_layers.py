"""Generate the verbal layer and fine-tune the clean transcript of one recording.

Division of labor (per the video-teach / post-lecture-slides-update skills):
- If a `.vtt`/`.srt` already exists, use it directly. If not, call the
  `transcribe-video` skill first: it produces the raw SRT **and** an
  LLM-cleaned `<name>.clean.md` of good quality.
- This script then (a) derives the deterministic **verbal layer**
  (`<stem>.verbal.md` — verbatim: fillers, repetitions, false starts preserved;
  [HH:MM:SS] stamps; only unambiguous ASR term casing via the glossary) from
  the vtt/srt, and (b) fine-tunes the existing `.clean.md` against slide OCR:
  correction brief -> LLM pass -> corrections.json -> `--fix-clean` applies the
  replacements in place and appends a time-stamped slide index.

Workflow (each step a separate invocation, so an agent can work between them):

  1. transcript_layers.py --vtt raw.transcript.vtt --out ep_stem
        -> ep_stem.verbal.md                       (deterministic)
  2. transcript_layers.py --vtt raw.transcript.vtt \
         --slides-ocr slides_ocr.json --emit-correction-brief
        -> correction_brief.md                     (slide OCR + cues per window)
  3. LLM pass writes corrections.json:
         {"replacements": [["garbled", "correct", "replace_all"], ...],
          "notes": "..."}
  4. transcript_layers.py --fix-clean <name>.clean.md \
         --apply-corrections corrections.json \
         --slides-ocr slides_ocr.json --assemble
        -> <name>.clean.md updated in place: term fixes applied, slide index
           appended. (.clean.md is never regenerated from the timing file.)
  5. transcript_layers.py --clean-srt <name>.clean.srt \
         --slides-ocr slides_ocr.json
        -> each SRT entry tagged [Slide K] by its start time (idempotent).

Both .vtt and .srt timing files are accepted (comma or dot milliseconds).
YouTube auto-caption .vtt files (rolling two-line cue format, inline tags,
stray blank-ish separator lines) are detected and normalized automatically:
the repeated leading lines are dropped so the verbal layer doesn't double
every phrase. `dedup_rolling_vtt()` is the standalone form of that
normalization, reused by fetch_raw_captions.py.
"""
import argparse
import json
import re
import sys
from pathlib import Path

TS = re.compile(r"(\d\d):(\d\d):(\d\d)[.,](\d{3})\s*-->\s*(\d\d):(\d\d):(\d\d)[.,](\d{3})")
SPEAKER = re.compile(r"^([A-Z][A-Za-z0-9 ._ '@+-]{0,38}):\s+")
TAG = re.compile(r"</?c>|<\d\d:\d\d:\d\d\.\d{3}>")  # YouTube auto-caption inline markup

GLOSSARY = [
    (r"\bKolesky\b", "Cholesky"), (r"\bSHARP256\b", "SHA-256"),
    (r"\bBachelor model\b", "Bachelier model"), (r"\bEugene Farmer\b", "Eugene Fama"),
    (r"\bQuandel\b", "Quandl"), (r"\bzealous algorithm\b", "Zeller algorithm"),
    (r"\bfour loop\b", "for loop"), (r"\bmonte carlo\b", "Monte Carlo"),
    (r"\bMonte carlo\b", "Monte Carlo"), (r"\bblack[- ]scholes\b", "Black-Scholes"),
]


def parse_cue_lines(path):
    """-> list of [start_s, end_s, [text lines]] from a .vtt or .srt file.

    Blank-ish separator lines (YouTube auto-caption VTT puts a stray " " line
    between the timestamp and its text) are skipped without flushing, so a
    cue keeps its own text; cue boundaries are the timestamp lines."""
    cues = []
    ts = None
    lines: list[str] = []

    def flush():
        nonlocal ts, lines
        if ts is not None and lines:
            cues.append([ts[0], ts[1], lines])
        ts, lines = None, []

    for raw in Path(path).read_text(errors="ignore").splitlines():
        m = TS.search(raw)
        if m:
            flush()
            g = [int(x) for x in m.groups()]
            ts = (g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                  g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000)
            continue
        s = raw.strip()
        if s == "WEBVTT" or s.isdigit() or s.startswith(("NOTE", "Kind:", "Language:")):
            flush()
            continue
        if not s:
            continue  # formatting noise; never a cue boundary (see docstring)
        if ts is not None:
            # strip YouTube auto-caption inline markup: word-timing anchors
            # (<00:00:01.500>) and cue-span tags (<c>, </c>); other formats'
            # text is untouched.
            lines.append(TAG.sub("", s))
    flush()
    return cues


def _looks_rolling(cues):
    """True when the YouTube rolling pattern (each cue repeats the previous
    cue's last line as its first) dominates the file."""
    overlaps = pairs = 0
    for a, b in zip(cues, cues[1:]):
        pairs += 1
        if b[2][0] == a[2][-1]:
            overlaps += 1
    return pairs >= 5 and overlaps / pairs >= 0.5


def dedup_rolling(cues):
    """Drop each cue's leading lines that repeat the previous kept cue's tail
    (the rolling auto-caption overlap). cues: [start, end, [lines]]."""
    out, prev = [], []
    for start, end, ls in cues:
        k = 0
        for off in range(min(len(prev), len(ls)), 0, -1):
            if ls[:off] == prev[len(prev) - off:]:
                k = off
                break
        ls = ls[k:]
        if not ls:
            continue
        out.append([start, end, ls])
        prev = ls
    return out


def dedup_rolling_vtt(path):
    """Normalize a rolling YouTube auto-caption .vtt into plain one-line-per-cue
    WebVTT text (tags stripped, repeated leading lines dropped). Returns the
    text; write it wherever the pipeline's raw timing file belongs."""
    cues = [c for c in parse_cue_lines(path) if c[2]]
    if _looks_rolling(cues):
        cues = dedup_rolling(cues)
    out = ["WEBVTT", ""]

    def ts(sec):
        return (f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:"
                f"{sec % 60:06.3f}")

    for start, end, ls in cues:
        out.append(f"{ts(start)} --> {ts(end)}")
        out.append(" ".join(ls))
        out.append("")
    return "\n".join(out)


def parse_timing(path):
    """-> list of [start_s, end_s, text] from a .vtt or .srt file.

    Rolling YouTube auto-caption files are detected and deduped automatically
    (with a notice) — feeding one in raw would double every phrase in the
    verbal layer."""
    raw_cues = parse_cue_lines(path)
    if not raw_cues:
        print(f"warn: {Path(path).name} yielded 0 cues - is this a timing file?", file=sys.stderr)
        return []
    if _looks_rolling(raw_cues):
        n_before = len(raw_cues)
        raw_cues = dedup_rolling(raw_cues)
        print(f"note: {Path(path).name}: rolling YouTube auto-caption format detected - "
              f"repeated leading lines deduped ({n_before} -> {len(raw_cues)} cues)",
              file=sys.stderr)
    return [[s, e, " ".join(ls)] for s, e, ls in raw_cues if ls]


def split_speaker(text):
    m = SPEAKER.match(text)
    return (m.group(1), text[m.end():].strip()) if m else ("", text.strip())


def glossary(text):
    for pat, rep in GLOSSARY:
        text = re.sub(pat, rep, text)
    return text


def stamp(sec):
    return f"[{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}]"


def verbal_md(cues, title):
    out = [f"# {title} — verbal transcript\n\nProvenance: derived verbatim from the raw "
           "transcription. Fillers, repetitions, false starts, self-corrections and incomplete "
           "sentences are PRESERVED by design; only unambiguous ASR term casing is corrected "
           "(glossary). A separate term-fix pass may correct further names/terms — wording is "
           "never changed.\n"]
    for start, _end, text in cues:
        spk, body = split_speaker(text)
        body = glossary(body)
        if not body:
            continue
        label = f" **{spk}:**" if spk else ""
        out.append(f"{stamp(start)}{label} {body}")
    return "\n\n".join(out) + "\n"


def numbered_slides(slides):
    return [(i + 1, s) for i, s in enumerate(sorted(slides, key=lambda x: x["start_s"]))]


def correction_brief(cues, slides, title):
    out = [f"# Correction brief — {title}\n\n",
           "This is a TECHNICAL lecture: ASR fails precisely on the material that matters - ",
           "technical terms, linearized formulas, code identifiers, numbers, tickers. The slide ",
           "OCR below is the ground truth for all of those. For each slide: its OCR text and ",
           "the transcript cues spoken during its on-screen window. Fix ASR-garbled technical ",
           "terms against the OCR; verify formulas number-by-number in linearized form; leave ",
           "unverifiable wording alone. ",
           "Emit corrections.json = {\"replacements\": [[\"wrong\", \"right\", \"replace_all\"|count], ...], \"notes\": \"...\"}.\n"]
    used = set()
    for i, s in enumerate(slides):
        cues_in = [c for c in cues if s["start_s"] <= c[0] < s["end_s"]]
        used.update(id(c) for c in cues_in)
        out.append(f"\n## Slide {i + 1} — {s['file']} ({s['start']}–{s['end_s'] // 60}m{s['end_s'] % 60:02d}s)\n")
        out.append("OCR:\n" + (s["ocr"] or "(none)"))
        out.append("Transcript cues in window:")
        for c in cues_in:
            out.append(f"- {stamp(c[0])} {c[2]}")
    orphans = [c for c in cues if id(c) not in used]
    out.append(f"\n## No slide on screen ({len(orphans)} cues — live demo / browser / board)\n")
    for c in orphans:
        out.append(f"- {stamp(c[0])} {c[2]}")
    return "\n".join(out) + "\n"


def load_corrections(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get("replacements"), list):
        sys.exit(f"{path}: expected {{\"replacements\": [[wrong, right, count?], ...]}}")
    reps = []
    for i, rep in enumerate(data["replacements"]):
        if not isinstance(rep, (list, tuple)) or len(rep) < 2 or not all(isinstance(x, str) for x in rep[:2]):
            sys.exit(f"{path}: replacement #{i} must be [wrong, right] or [wrong, right, count|'replace_all']")
        if len(rep) >= 3 and rep[2] != "replace_all":
            try:
                n = int(rep[2])
            except ValueError:
                sys.exit(f"{path}: replacement #{i} count must be an integer or 'replace_all'")
            reps.append((rep[0], rep[1], n))
        else:
            reps.append((rep[0], rep[1], -1))
    return reps, data.get("notes", "")


def apply_corrections(text, reps):
    """reps: iterable of (wrong, right) or (wrong, right, count|-1 for all)."""
    applied, missed = [], []
    for rep in reps:
        wrong, right = rep[0], rep[1]
        count = rep[2] if len(rep) > 2 else -1
        found = text.count(wrong)
        if found == 0:
            missed.append(wrong)
            continue
        text = text.replace(wrong, right) if count == -1 else text.replace(wrong, right, count)
        applied.append((wrong, min(found, count) if count != -1 else found))
    return text, applied, missed


def tag_srt_text(srt_text, slides):
    """Prepend [Slide K] to an SRT entry's first text line when the entry's
    start falls in slide K's window (tag shown only on slide change).
    Entries already carrying a tag are re-tagged in place — idempotent."""
    slides = sorted(slides, key=lambda x: x["start_s"])

    def slide_at(t):
        k = None
        for i, s in enumerate(slides, 1):
            if s["start_s"] <= t < s["end_s"]:
                k = i
                break
        # times outside every window (demo gaps) keep the last seen slide;
        # flip-backs to an earlier slide cannot be derived from timing alone -
        # the slides/README.md notes callbacks (skill convention).
        return k if k is not None else (len(slides) if slides else None)

    out, last = [], None
    for b in re.split(r"\n\s*\n", srt_text.strip()):
        lines = b.splitlines()
        if len(lines) >= 3 and re.match(r"\s*\[Slide \d+\]\s*", lines[2]):
            lines[2] = re.sub(r"^\s*\[Slide \d+\]\s*", "", lines[2])
        m = TS.search(lines[1]) if len(lines) >= 2 else None
        if m is None:
            out.append("\n".join(lines))
            continue
        g = [int(x) for x in m.groups()]
        t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        k = slide_at(t0)
        if k is not None and k != last:
            lines[2] = f"[Slide {k}] " + lines[2]
            last = k
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtt", default="", help="raw .vtt OR .srt timing file (drives verbal.md + brief)")
    ap.add_argument("--out", default="", help="stem for verbal.md output (default: timing-file stem)")
    ap.add_argument("--title", default="", help="transcript title (default: timing-file stem)")
    ap.add_argument("--slides-ocr", default="", help="slides_ocr.json from slide_ocr.py")
    ap.add_argument("--emit-correction-brief", action="store_true")
    ap.add_argument("--fix-clean", default="",
                    help="existing .clean.md to fine-tune in place with --apply-corrections")
    ap.add_argument("--clean-srt", default="",
                    help="existing .clean.srt to tag in place with [Slide K] markers (--slides-ocr required)")
    ap.add_argument("--apply-corrections", default="", help="corrections.json from the LLM pass")
    ap.add_argument("--assemble", action="store_true",
                    help="append the time-stamped slide index to the clean file")
    ap.add_argument("--zh-index", default="",
                    help="with --assemble + --fix-clean on a .clean.zh.md mirror: append this "
                         "file's translated bullets under '## 幻灯片索引' instead of the English index")
    a = ap.parse_args()
    if not any([a.vtt, a.clean_srt, a.fix_clean, a.zh_index]):
        sys.exit("nothing to do: pass --vtt (verbal/brief), --fix-clean "
                 "[--apply-corrections] [--assemble], and/or --clean-srt + --slides-ocr")
    if a.fix_clean and a.assemble and not a.slides_ocr and not a.zh_index:
        sys.exit("--assemble requires --slides-ocr")
    if a.zh_index and not (a.fix_clean and a.assemble):
        sys.exit("--zh-index requires --fix-clean + --assemble")
    if a.fix_clean and not Path(a.fix_clean).exists():
        sys.exit(f"--fix-clean file not found: {a.fix_clean}")
    if a.clean_srt:
        if not a.slides_ocr:
            sys.exit("--clean-srt requires --slides-ocr")
        slides = json.loads(Path(a.slides_ocr).read_text())
        f = Path(a.clean_srt)
        f.write_text(tag_srt_text(f.read_text(), slides))
        print(f"{f}: slide tags written")

    # (a) verbal layer + correction brief from the timing file
    if a.vtt:
        title = a.title or Path(a.vtt).stem
        cues = parse_timing(a.vtt)
        stem = Path(a.out) if a.out else Path(a.vtt).with_suffix("")
        stem.with_suffix(".verbal.md").write_text(verbal_md(cues, title))
        print(f"{len(cues)} cues -> {stem}.verbal.md")
        if a.emit_correction_brief:
            if not a.slides_ocr:
                sys.exit("--emit-correction-brief requires --slides-ocr")
            slides = json.loads(Path(a.slides_ocr).read_text())
            Path(stem.parent / "correction_brief.md").write_text(
                correction_brief(cues, slides, title))
            print(f"correction_brief.md written")

    # (b) fine-tune the existing clean transcript in place
    if a.fix_clean and (a.apply_corrections or a.assemble or a.zh_index):
        reps, notes, applied, missed = [], "", [], []
        if a.apply_corrections:
            reps, notes = load_corrections(a.apply_corrections)
        f = Path(a.fix_clean)
        clean = f.read_text()
        if reps:
            clean, applied, missed = apply_corrections(clean, reps)
        if a.assemble and a.slides_ocr and "## Slide index" not in clean:
            slides = json.loads(Path(a.slides_ocr).read_text())
            idx = ["## Slide index", ""]
            for k, s in numbered_slides(slides):
                idx.append(f"- Slide {k} @ {s['start']}: "
                           + " ".join(s.get("ocr", "").split())[:90])
            clean = clean.rstrip() + "\n\n" + "\n".join(idx) + "\n"
        if a.assemble and a.zh_index and "## 幻灯片索引" not in clean:
            clean = clean.rstrip() + "\n\n## 幻灯片索引\n\n" + Path(a.zh_index).read_text().rstrip() + "\n"
        f.write_text(clean)
        print(f"{f}: corrections applied {len(applied)}"
              + (f" (examples: {applied[:3]})" if applied else ""))
        if missed:
            print(f"replacements NOT found in text ({len(missed)}): {missed}")
        if notes:
            print(f"notes: {notes}")


if __name__ == "__main__":
    main()
