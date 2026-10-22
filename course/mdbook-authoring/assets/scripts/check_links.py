#!/usr/bin/env python3
"""Link-check a built mdBook: walk every .html, resolve each href/src.

Part of the verification bar in MDBOOK.md ("every internal link/image
resolves"). Checks every `href`/`src` in every built page:

- external schemes (http, https, mailto, data, javascript) and pure
  `#fragment` links are skipped
- local targets are resolved against the page's real location on disk,
  query strings are dropped, `%XX` escapes are decoded
- a target ending in `/` must contain an `index.html`
- a local target with a `#fragment` must contain `id="fragment"` in the
  target file (catches renamed heading anchors)
- `--allow GLOB` whitelists raw hrefs whose targets are fetch-time
  artifacts (e.g. `--allow 'paper/*.pdf'` restored by a download script)

Usage:
  python3 check_links.py mdbook/book
  python3 check_links.py mdbook/book --allow 'paper/*.pdf' --allow '*/downloads/*'

Exits 0 when every link resolves, 1 otherwise (printing each broken link
once, with the pages that reference it).
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

SKIP_SCHEMES = ("http:", "https:", "mailto:", "data:", "javascript:")


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        for key in ("href", "src"):
            v = d.get(key)
            if v:
                self.urls.append(v)
        i = d.get("id")
        if i:
            self.ids.add(i)


def page_ids(html_path: Path) -> set[str]:
    c = Collector()
    c.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    return c.ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book_dir", type=Path, help="the built book/ directory")
    ap.add_argument("--allow", action="append", default=[],
                    help="glob pattern of raw hrefs to whitelist (repeatable)")
    args = ap.parse_args()
    book = args.book_dir.resolve()
    pages = sorted(book.rglob("*.html"))
    if not pages:
        print(f"no .html files under {book}", file=sys.stderr)
        return 1

    id_cache: dict[Path, set[str]] = {}
    broken: dict[str, set[str]] = defaultdict(set)  # raw href -> referencing pages

    for page in pages:
        c = Collector()
        c.feed(page.read_text(encoding="utf-8", errors="replace"))
        for raw in c.urls:
            parsed = urlparse(raw)
            if parsed.scheme and f"{parsed.scheme}:" in SKIP_SCHEMES:
                continue
            if any(fnmatch.fnmatch(raw, pat) for pat in args.allow):
                continue
            if not parsed.path:
                continue  # pure in-page fragment
            target = unquote(parsed.path)
            if target.startswith("/"):
                resolved = (book / target.lstrip("/")).resolve()  # site-root-absolute
            else:
                resolved = (page.parent / target).resolve()
            if resolved.is_dir():
                resolved = resolved / "index.html"
            if not resolved.exists():
                broken[raw].add(str(page.relative_to(book)))
                continue
            if parsed.fragment:
                if resolved.suffix == ".html":
                    if resolved not in id_cache:
                        id_cache[resolved] = page_ids(resolved)
                    if parsed.fragment not in id_cache[resolved]:
                        broken[raw].add(str(page.relative_to(book)))

    if broken:
        for raw in sorted(broken):
            where = ", ".join(sorted(broken[raw]))
            print(f"BROKEN: {raw}   (referenced from {where})")
        return 1
    print(f"all links resolve ({len(pages)} pages checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
