#!/usr/bin/env python3
"""mdBook preprocessor: escape raw `_` and `*` in KaTeX-rendered HTML text nodes.

mdbook-katex injects KaTeX's HTML directly into the markdown source. Inside a
paragraph, the text between those injected tags is still parsed as markdown
inline content — and a raw `_` there (emitted for LaTeX like `\\text{a\\_b}`)
can pair with another raw `_` across span boundaries into `<em>`, producing
"unclosed <span>" build warnings and garbled math. This preprocessor walks
every `class="katex…"` chunk and backslash-escapes `_`/`*` in its text nodes
(`futures_level` -> `futures\\_level`), which pulldown-cmark renders back as
literal characters.

Usage: copy next to the book and wire in book.toml:

    [preprocessor.katex-text-fix]
    command = "python3 katex_text_fix.py"
    after = ["katex"]   # required — without it mdbook sorts preprocessors
                        # alphabetically and runs this BEFORE katex, a no-op

Must exit 0 on the `supports <renderer>` probe or mdbook silently skips it.

mdbook 0.5 preprocessor protocol (verified against mdbook 0.5.4):
- stdin:  2-element JSON array `[context, book]` where book is `{"items": [...]}`
  (mdbook 0.4 used `{"sections": [...]}` — accepted here too).
- stdout: **just the book object** — echoing `[context, book]` back fails with
  "invalid type: map, expected a sequence".
"""

from __future__ import annotations

import json
import re
import sys

# Opening tag of a KaTeX chunk: <span class="katex"> or <span class="katex-display"> …
KATEX_OPEN = re.compile(r'<span\b[^>]*class="katex[^"]*"[^>]*>')
SPAN_TAG = re.compile(r"</?span\b[^>]*>")


def escape_text_nodes(chunk_open_tag: str, rest: str) -> tuple[str, int]:
    """Return (fixed_html_from_open_tag, chars_consumed_after_open_tag)."""
    buf = [chunk_open_tag]
    j = 0
    depth = 1  # the open tag itself is already consumed
    while j < len(rest) and depth > 0:
        tag = SPAN_TAG.match(rest, j)
        if tag:
            buf.append(tag.group(0))
            depth += -1 if tag.group(0)[1] == "/" else 1
            j = tag.end()
        elif rest[j] == "<":
            # a non-span tag inside the chunk (e.g. MathML <math>…</math>) —
            # keep verbatim, advance past it (never re-examine the same '<')
            close = rest.find(">", j)
            nxt = close + 1 if close != -1 else len(rest)
            buf.append(rest[j:nxt])
            j = nxt
        else:
            nxt = rest.find("<", j)
            if nxt == -1:
                nxt = len(rest)
            seg = rest[j:nxt]
            if "_" in seg or "*" in seg:
                seg = seg.replace("_", "\\_").replace("*", "\\*")
            buf.append(seg)
            j = nxt
    return "".join(buf), j


def fix_content(content: str) -> str:
    if 'class="katex' not in content:
        return content
    out = []
    i = 0
    while True:
        m = KATEX_OPEN.search(content, i)
        if not m:
            out.append(content[i:])
            break
        out.append(content[i : m.start()])
        fixed, consumed = escape_text_nodes(m.group(0), content[m.end() :])
        out.append(fixed)
        i = m.end() + consumed
    return "".join(out)


def walk_items(items: list) -> None:
    for item in items:
        if "Chapter" in item:
            chapter = item["Chapter"]
            chapter["content"] = fix_content(chapter.get("content", ""))
            walk_items(chapter.get("sub_items", []))


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "supports":
        # mdbook probes: `<command> supports <renderer>` with no stdin.
        return 0 if sys.argv[2] in ("html", "markdown") else 1
    _context, book = json.load(sys.stdin)
    walk_items(book.get("items", book.get("sections", [])))
    # mdbook 0.5 protocol: preprocessor output is just the Book (not [context, book]).
    json.dump(book, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
