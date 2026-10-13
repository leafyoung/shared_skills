"""Tests for the SRT slide-tagging rework in transcript_layers.tag_srt_text
(header-tag fallback bug, no-cue-start anchoring, provenance strip) plus an
integration pass over a real course workspace's episode SRTs.

Run:  python3 -m pytest <this-dir>/test_srt_tagging.py -q

Integration cases are skipped when STUDY_COURSE_WS (a video-teach course
workspace with epN_<slug>/{transcript,slides}) is not present.
"""
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


layers = load("transcript_layers")

COURSE_WS = Path(os.environ.get(
    "STUDY_COURSE_WS",
    "/var/home/yangye/devv/study/study-cmu-agents",
))


def make_srt(blocks):
    """blocks: list of (start, end, text) -> SRT text (1-based indices)."""
    out = []
    for i, (a, b, text) in enumerate(blocks, 1):
        out.append(f"{i}\n{a} --> {b}\n{text}\n")
    return "\n".join(out)


def tagged_blocks(srt_text):
    """[(start, [slide tags], text)] in file order."""
    res = []
    for b in re.split(r"\n\s*\n", srt_text.strip()):
        lines = b.splitlines()
        m = layers.TS.search(lines[1])
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        tags = [int(t) for t in re.findall(r"\[Slide (\d+)\]", lines[2])]
        res.append((start, end, tags,
                    re.sub(r"(?:\[Slide \d+\]\s*)+", "", lines[2])))
    return res


def ts(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},000"


def slides_of(*windows):
    return [{"file": f"s{i:02d}.png", "start_s": a, "end_s": b}
            for i, (a, b) in enumerate(windows, 1)]


class TestHeaderFallbackBug:
    def test_cue_before_first_window_gets_no_tag(self):
        """The old fallback tagged cues before the first slide window with
        the LAST slide's number - the bogus header artifact on old episodes.
        (A URL header block is stripped entirely - see TestProvenanceStrip.)"""
        srt = make_srt([(ts(0), ts(3), "Pre-lecture chatter while people settle."),
                   (ts(130), ts(140), "first content cue")])
        out = layers.tag_srt_text(srt, slides_of((130, 300), (300, 600)))
        blocks = tagged_blocks(out)
        assert blocks[0][2] == []                      # header: untagged
        assert blocks[1][2] == [1]                     # first content cue: Slide 1

    def test_last_slide_stays_up_after_its_window(self):
        srt = make_srt([(ts(10), ts(20), "in slide 1"),
                   (ts(700), ts(720), "closing remarks past the last window")])
        out = layers.tag_srt_text(srt, slides_of((0, 300), (300, 600)))
        blocks = tagged_blocks(out)
        assert [b[2] for b in blocks] == [[1], [2]]

    def test_idempotent(self):
        srt = make_srt([(ts(0), ts(3), "https://youtu.be/x"),
                   (ts(130), ts(140), "content")])
        slides = slides_of((130, 300), (300, 600))
        once = layers.tag_srt_text(srt, slides)
        assert layers.tag_srt_text(once, slides) == once


class TestNoCueStartAnchoring:
    def test_slide_without_cue_start_anchored_by_overlap(self):
        """Slide 2's window (300-340) contains no cue START (cues at 290 and
        350); the 290-cue is still playing at 300 - stack [Slide 2] there."""
        srt = make_srt([(ts(0), ts(3), "https://youtu.be/x"),
                   (ts(290), ts(310), "speech spanning the flip"),
                   (ts(350), ts(370), "speech in slide 3")])
        out = layers.tag_srt_text(srt, slides_of((0, 300), (300, 340), (340, 600)))
        blocks = tagged_blocks(out)
        assert blocks[0][2] == [1, 2]                  # stacked, ascending
        assert blocks[1][2] == [3]

    def test_pure_gap_slide_stays_untagged(self):
        """A slide shown entirely inside a silent gap (no overlapping cue)
        legitimately stays untagged."""
        srt = make_srt([(ts(0), ts(100), "before the gap"),
                   (ts(500), ts(520), "after the gap")])
        out = layers.tag_srt_text(srt, slides_of((0, 300), (300, 400), (400, 600)))
        blocks = tagged_blocks(out)
        assert [b[2] for b in blocks] == [[1], [3]]    # slide 2 untaggable

    def test_tags_stay_ascending_with_stacking(self):
        srt = make_srt([(ts(0), ts(3), "https://youtu.be/x"),
                   (ts(100), ts(130), "spans flips 1->2->3"),
                   (ts(400), ts(420), "in slide 3 tail")])
        out = layers.tag_srt_text(srt, slides_of((0, 110), (110, 120), (120, 600)))
        blocks = tagged_blocks(out)
        all_tags = [t for b in blocks for t in b[2]]
        assert all_tags == sorted(all_tags)
        assert all_tags == [1, 2, 3]


class TestProvenanceStrip:
    def test_leading_provenance_blocks_stripped(self):
        srt = make_srt([(ts(0), ts(3), "https://youtu.be/x"),
                   (ts(3), ts(6), "Speaker: Someone"),
                   (ts(6), ts(9), "Transcription cleaned from Whisper/Groq output."),
                   (ts(10), ts(20), "Real speech starts here.")])
        out = layers.strip_leading_provenance(srt)
        blocks = tagged_blocks(out) if False else [
            (b.splitlines()[2],) for b in re.split(r"\n\s*\n", out.strip())]
        assert len(blocks) == 1
        assert "Real speech" in blocks[0][0]

    def test_stops_at_first_speech(self):
        srt = make_srt([(ts(0), ts(3), "https://youtu.be/x"),
                   (ts(5), ts(9), "Okay, real speech."),
                   (ts(20), ts(30), "The recording cuts off mid-sentence.")])
        # the THIRD block merely starts with "The recording" but is real speech
        # in the middle of a file - only LEADING provenance is stripped
        out = layers.strip_leading_provenance(srt)
        assert len(re.split(r"\n\s*\n", out.strip())) == 2

    def test_speech_never_stripped(self):
        srt = make_srt([(ts(5), ts(9), "Okay, let's go to https://example.com today.")])
        assert layers.strip_leading_provenance(srt) == srt


class TestMultiTagIdempotency:
    def test_stacked_tags_stripped_wholesale(self):
        srt = make_srt([(ts(0), ts(3), "[Slide 2][Slide 3] already stacked"),
                   (ts(10), ts(20), "plain")])
        out = layers.tag_srt_text(srt, slides_of((0, 300)))
        blocks = tagged_blocks(out)
        assert blocks[0][3] == "already stacked"       # old stack removed
        assert blocks[0][2] == [1]                     # re-derived from windows


# --- integration over a real course workspace -------------------------------

def episodes(ws):
    eps = []
    for readme in sorted(ws.glob("ep*_*/slides/README.md")):
        ep_dir = readme.parent.parent
        srt = ep_dir / "transcript"
        srt_files = list(srt.glob("*.clean.srt"))
        ocr = ep_dir / "slides" / "slides_ocr.json"
        if srt_files and ocr.exists():
            eps.append((ep_dir.name, srt_files[0], ocr))
    return eps


@pytest.mark.skipif(not COURSE_WS.exists(), reason="course workspace not present")
class TestCourseWorkspaceIntegration:
    @pytest.mark.parametrize("name,srt_path,ocr_path", episodes(COURSE_WS),
                             ids=[e[0] for e in episodes(COURSE_WS)])
    def test_tagged_srt_invariants(self, name, srt_path, ocr_path):
        slides = json.loads(ocr_path.read_text())
        raw = srt_path.read_text()
        out = layers.tag_srt_text(raw, slides)
        blocks = tagged_blocks(out)

        n_slides = len(slides)
        anchored = {t for _, _, tags, _ in blocks for t in tags}
        # 1. tags strictly ascending across the file
        flat = [t for _, _, tags, _ in blocks for t in tags]
        assert flat == sorted(flat)
        # 2. no duplicate (cue, tag) pairs after re-derivation
        assert len(flat) == len(set(flat))
        # 3. every slide whose window overlaps some cue is anchored
        starts = [(b[0], b[1]) for b in blocks]
        for i, s in enumerate(slides, 1):
            overlaps = any(st < s["end_s"] and en > s["start_s"]
                           for st, en in starts)
            if overlaps:
                assert i in anchored, f"{name}: slide {i} overlaps a cue but untagged"
        # 4. the first block (provenance/URL header) carries no tag unless it
        #    genuinely starts inside slide 1's window
        if blocks and blocks[0][0] < slides[0]["start_s"]:
            assert blocks[0][2] == [], f"{name}: header cue tagged {blocks[0][2]}"
        # 5. cue starts stay monotonic (tagging must not reorder)
        starts_only = [b[0] for b in blocks]
        assert starts_only == sorted(starts_only)
