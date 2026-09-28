"""Tiny shared helpers for hand-composed teaching-lesson SVG figures.

Not a charting library — just enough string-building to keep the 8 figure
scripts in this directory free of raw XML boilerplate and float-repr noise
(e.g. "126.90000000000001"). Each figure script still lays out its own
geometry; this only formats tags.
"""

from __future__ import annotations

# Confirmed resolvable by `typst fonts` on this workstation. Use FONT_ZH (in
# place of the usual "Helvetica, Arial, sans-serif" literal) for every text()
# call in a script's Chinese-label variant.
FONT_EN = "Helvetica, Arial, sans-serif"
FONT_ZH = "Heiti SC, PingFang SC, Noto Sans CJK SC, sans-serif"


def lang_from_argv(default="en"):
    """`python3 scriptname.py zh` selects the Chinese label variant; no arg
    (or 'en') keeps the original English output filename and labels."""
    import sys
    return sys.argv[1] if len(sys.argv) > 1 else default


def n(x: float) -> str:
    """Format a coordinate: integers print bare, others to 2 decimal places."""
    r = round(x, 2)
    return str(int(r)) if r == int(r) else f"{r:.2f}"


def svg_open(width: int, height: int, aria_label: str) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{aria_label}">'
    )


SVG_CLOSE = "</svg>"


def line(x1, y1, x2, y2, stroke, width=1.4, dash=None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{n(x1)}" y1="{n(y1)}" x2="{n(x2)}" y2="{n(y2)}" '
        f'stroke="{stroke}" stroke-width="{width}"{d}/>'
    )


def rect(x, y, w, h, fill, opacity=1.0, stroke=None, stroke_width=1.4, rx=0) -> str:
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
    r = f' rx="{n(rx)}"' if rx else ""
    return (
        f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"{r} '
        f'fill="{fill}" opacity="{opacity}"{s}/>'
    )


def circle(cx, cy, r, fill, stroke=None, stroke_width=1) -> str:
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
    return f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}" fill="{fill}"{s}/>'


def text(x, y, s, size=12, fill="#16181c", anchor="start", weight=None, family="sans-serif", transform=None) -> str:
    anchor = anchor or "start"  # guard against an accidental None slipping through
    w = f' font-weight="{weight}"' if weight else ""
    t = f' transform="{transform}"' if transform else ""
    return (
        f'<text x="{n(x)}" y="{n(y)}" font-family="{family}" font-size="{size}" '
        f'fill="{fill}" text-anchor="{anchor}"{w}{t}>{s}</text>'
    )


def polyline(points, stroke, width=3, fill="none", linecap="round", linejoin="round") -> str:
    pts = " ".join(f"{n(x)},{n(y)}" for x, y in points)
    return (
        f'<polyline points="{pts}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{width}" stroke-linecap="{linecap}" stroke-linejoin="{linejoin}"/>'
    )


def polygon(points, fill, opacity=1.0, stroke="none") -> str:
    pts = " ".join(f"{n(x)},{n(y)}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" opacity="{opacity}" stroke="{stroke}"/>'


def write_svg(path, body_lines, width, height, aria_label):
    """Assemble and write a complete SVG file from a list of element strings."""
    from pathlib import Path

    content = "\n".join([svg_open(width, height, aria_label), *body_lines, SVG_CLOSE]) + "\n"
    Path(path).write_text(content)
    print(f"wrote {path}")
