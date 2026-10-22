#!/usr/bin/env python3
"""Prove two parallel lesson trees agree — "sync is proven, not assumed".

Pairs files between two lesson trees (qmd→mdBook conversion checks, or the
English/Chinese mirror books of a translated course) and diffs them AFTER
stripping the known per-format differences, so format noise doesn't mask
real content drift. Exits 0 with "TREES AGREE" or 1 with unified diffs.

Normalized away (the known per-format differences):
- YAML front matter vs H1: front matter stripped, leading H1 stripped
- escaped dollars: `\\$` → `$` (quarto escapes literal dollars, the book may not)
- figure syntax: `![cap](p){attrs}` / `<img src="p" …>` → `![cap](basename)`
- language figure suffix: `name-zh.svg` pairs with `name.svg` (`--strip-suffix`)
- tag forms: `**ERRATA**` / `**修正**` (bare or bracketed) → `TAG`
- path depth: figure basenames only; trailing whitespace; 3+ blank lines → 1

Files pair by relative path with the suffix stripped from the stem
(`lessons/0001-x.md` ↔ `lessons/0001-x.md`; figures `f.svg` ↔ `f-zh.svg`).
Binary files (images, PDFs, fonts) must exist in both trees; content is
not compared.

Usage:
  python3 normalized_diff.py lessons_md/src/lessons lessons_md_zh/src/lessons
  python3 normalized_diff.py qmd_lessons mdbook/src/lessons --strip-suffix ""
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

TAG_RE = re.compile(r"(\*\*|\[)?(?:ERRATA|修正)(\*\*|\])?")
FRONT_MATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
H1_RE = re.compile(r"\A#\s+.+\n+")
IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)(\{[^}]*\})?")
IMG_HTML_RE = re.compile(r"<img\b[^>]*?\bsrc=\"([^\"]+)\"[^>]*?>")


def norm_text(text: str, strip_suffix: str, fig_exts: tuple[str, ...]) -> str:
    def md_img(m: re.Match) -> str:
        return f"![{m.group(1)}]({fig_base(m.group(2), strip_suffix, fig_exts)})"

    def html_img(m: re.Match) -> str:
        alt_m = re.search(r"alt=\"([^\"]*)\"", m.group(0))
        alt = alt_m.group(1) if alt_m else ""
        return f"![{alt}]({fig_base(m.group(1), strip_suffix, fig_exts)})"

    text = FRONT_MATTER_RE.sub("", text)
    text = H1_RE.sub("", text)
    text = text.replace("\\$", "$")
    text = IMG_HTML_RE.sub(html_img, text)
    text = IMG_MD_RE.sub(md_img, text)
    text = TAG_RE.sub("TAG", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        blanks = blanks + 1 if not ln else 0
        if blanks <= 1:
            out.append(ln)
    return "\n".join(out).strip()


def fig_base(path: str, strip_suffix: str, fig_exts: tuple[str, ...]) -> str:
    """Basename of a figure path with the language suffix stripped."""
    base = path.rsplit("/", 1)[-1]
    ext_alt = "|".join(re.escape(e) for e in fig_exts)
    m = re.match(rf"^(.+?)({re.escape(strip_suffix)})?\.({ext_alt})$", base)
    if m:
        return f"{m.group(1)}.{m.group(3)}"
    return base


def keyed(root: Path, strip_suffix: str) -> dict[tuple[str, ...], Path]:
    out: dict[tuple[str, ...], Path] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.stem.endswith(strip_suffix) and strip_suffix:
            rel = rel.with_name(rel.stem[: -len(strip_suffix)] + rel.suffix)
        out[rel.parts] = p
    return out


def digest(norm_lines: list[str]) -> list[str]:
    """Structural skeleton of a normalized page: heading levels, figures,
    tags, fences, display math, table rows, prose positions. Two TRANSLATED
    trees agree on this even though every word differs -- this is the
    lockstep proof for language mirrors. Full text diff (default mode) is
    for same-language conversions (qmd -> mdBook)."""
    out = []
    for ln in norm_lines:
        if not ln:
            continue
        if ln.startswith("#"):
            out.append("H" + str(len(ln) - len(ln.lstrip("#"))))
        elif ln.startswith("!["):
            out.append("FIG")
        elif ln.startswith("TAG"):
            out.append("TAG")
        elif ln.startswith("$$"):
            out.append("MATH")
        elif ln.startswith("|"):
            out.append("TBL")
        elif ln.startswith("```"):
            out.append("FENCE")
        else:
            out.append("TEXT")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir_a", type=Path)
    ap.add_argument("dir_b", type=Path)
    ap.add_argument("--strip-suffix", default="-zh",
                    help="filename suffix treated as the language variant (default: -zh)")
    ap.add_argument("--digest", action="store_true",
                    help="compare structural skeletons (heading levels, figures, "
                         "tags, fences, math, tables) instead of full text -- the "
                         "lockstep proof for translated mirrors; default mode diffs "
                         "full normalized text (same-language conversion checks)")
    ap.add_argument("--fig-exts", default="svg,png,jpg,jpeg,gif,webp",
                    help="comma-separated figure extensions (default: svg,png,jpg,jpeg,gif,webp)")
    args = ap.parse_args()
    fig_exts = tuple(e.strip().lstrip(".") for e in args.fig_exts.split(",") if e.strip())

    a_files, b_files = keyed(args.dir_a, args.strip_suffix), keyed(args.dir_b, args.strip_suffix)
    broken = False

    for missing in sorted(set(a_files) - set(b_files)):
        print(f"ONLY IN {args.dir_a}: {'/'.join(missing)}")
        broken = True
    for missing in sorted(set(b_files) - set(a_files)):
        print(f"ONLY IN {args.dir_b}: {'/'.join(missing)}")
        broken = True

    binary_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".woff", ".woff2"}
    for key in sorted(set(a_files) & set(b_files)):
        pa, pb = a_files[key], b_files[key]
        name = "/".join(key)
        if pa.suffix.lower() in binary_exts:
            continue  # existence check only
        a = norm_text(pa.read_text(encoding="utf-8"), args.strip_suffix, fig_exts).splitlines()
        b = norm_text(pb.read_text(encoding="utf-8"), args.strip_suffix, fig_exts).splitlines()
        if args.digest:
            a, b = digest(a), digest(b)
        if a != b:
            broken = True
            print(f"\n===== DIFF: {name} ({args.dir_a} vs {args.dir_b}) =====")
            for line in difflib.unified_diff(a, b, lineterm="", n=1):
                print(line)

    if not broken:
        print("TREES AGREE")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
