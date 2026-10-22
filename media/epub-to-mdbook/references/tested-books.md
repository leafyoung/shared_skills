# Tested books (regression baseline)

Books converted and reviewed with this skill's converter and its per-book copies. Use
2 or 3 of them as a regression check after changing `assets/epub2mdbook.py`: convert the
EPUB into a scratch folder, build, and compare. Counts must stay at or above these
values with zero WARN lines and all links resolving.

All 14 books marked "measured" were converted on 2026-10-19 with the current shared converter
(scratch folders, `mdbook build`: 0 WARN lines, `check_links.py`: all links resolve) and carry exact
counts. The other rows come from the review reports of the session that built the skill, so treat
those as a floor, not an exact target. A fence is a line that opens with three backticks. "Link-check
pages" is the number the link checker printed; it includes `print.html` and the index pages, so it is
larger than the number of SUMMARY pages. "Exercises" names the converter feature the book is the
regression case for. Source EPUBs live next to each book folder; the paths are the author's machine,
so look the books up by title. The fence body numbers (blank-line fraction inside fences, inline code
spans) are in the Notes column for the code books: a fence count alone never proves a code book.

| Book (code language) | Kind | Link-check pages | Images | Code | Exercises / notes |
|---|---|---|---|---|---|
| Book A, author A (c) - measured | Manning, prose + C | 25 | 63 | 667 fences (607 c, 60 bash); blank fraction 0.097 | index and TOC need real links; FrameMaker `pgfId` table cells must keep bare numbers |
| Book B, author B (cpp) | Pearson, long, footnotes | 25 | 6 | ~4,200 fence lines | nine tables with merged cells stay raw HTML |
| Book C, author C (cpp) | Packt | 26 | 59 | 764 listings | admonish tip boxes; one H1 per page |
| Book D, 2nd ed. (python) - measured | Packt, notebooks, MathJax math | 374 | 300 | 655 fences | `In [ ]:` prompts, backslash continuations; MathJax spans: 261 found, 226 converted to TeX (7 merged into a neighbour), 35 kept as text (17 equation images, 9 assistive-only, 7 dollar signs, 1 three-part msubsup, 1 blank); 219 placeholders, 0 KaTeX errors in the build; 371 pages, 79,023 words (prose, fences removed) |
| Book E (python) | No Starch / Manning style | 46 | 133 | ~1,200 fence lines | equations as KaTeX, `<sub>` warnings |
| Book F (cpp) - measured | Pygments `<figure>` listings | 37 | 3 | 440 cpp fences; 3,759 lines; blank 0.056; 1,114 inline spans | archive bundles other books; use container.xml |
| C++ Templates, Chinese edition (cpp) - measured | Chinese, publisher class paragraphs | 21 | 20 | 786 cpp fences; 8,852 lines; blank 0.0 | `CODE_CLASS_ALT`; NCX has 312 entries, mostly in-page; SUMMARY stays page-level |
| Functional Programming Patterns in Scala and Clojure, part 1 and P2.0 (scala) - measured | Pragmatic tables | 52 (part 1), 53 (P2.0) | 25 | 547 fences (277 scala, 235 clojure, 35 java); 3,159 lines; blank 0.080; 1,711 inline spans | `processedcode` tables, `cf` inline spans, `_sniff_language`, praise and footnote tables; the old converter gave blank 0.496 and 244 spans |
| Parallel and Concurrent Programming in Haskell (haskell) - measured | O'Reilly | 30 | 49 | 633 fences (554 haskell, 79 bash); 3,226 lines; blank 0.065; 3,882 inline spans | the clean baseline |
| Book P (python) - measured | Leanpub, Pygments + notebooks | 56 | 71 | 900 fences (672 python, 13 cpp, 215 plain); 4,450 lines; blank 0.051 | LaTeX in equation `alt` becomes KaTeX; Jupyter prompts |
| Paper Q (text) - measured | Paper, one huge XHTML | 16 | 331 SVGs (327 formulas, 4 figures) | n/a | single-paper support: `INLINE_SVG_PAGE_MIN`, `extract_svgs`, `split_page`; 12 SUMMARY pages, 6,150 words (reviewed book 12 pages, 6,148) |
| Book N (python) | Translated articles | 48 | 208 | 110 fences (shape-detected) | no code markup in source |
| Book G (text) - measured | Prose | 27 | 71 | none | running footer "20" with `<a id="pN">` anchors (`BARE_NUMBER_P_RE`); 23 pages, 21 H1, 10 H2, 79,660 words (reviewed 79,660) |
| Book I (text) - measured | Prose, 1,000+ notes | 33 | 8 | none | note back-links; heading that is one link after `<a id/>` (`HEADING_LINK_RE`); 29 pages, 34 H1, 14 H2, 156,985 words (identical to reviewed) |
| Book H (text) - measured | Prose, notes | 29 | 3 | none | `HEADING_CLASS_LEVELS` (cn/ct/pn), `QUOTE_CLASSES` (24 quote lines), `_italic_marker` (57 `<em>`); 25 pages, 17 H1, 101,498 words (identical to reviewed); one-off fixes script (alt text, summary labels) |
| Book J (text) - measured | Illustrated, notes | 32 | 48 | none | `h1-0001` headings, ct + h1-0001 pair, `<br/>` in titles, 782 `<em>`; 28 pages, 23 H1, 111,713 words (reviewed 111,713) |
| Book K (Chinese fiction) (text) - measured | Chinese fiction | 48 | 20 | none | percent-encoded image names; 44 pages, 106 H1, 95,249 words (identical to reviewed) |

Remaining differences from the reviewed prose books are book-specific: hand-written image alt
texts (Book H, Book K, Book J cover), SUMMARY labels chosen by hand (Book G "Titlepage" and
"About this eBook",  Book K "Book K", Book H "Dedication"/"Epigraph", Book S "Copyright"),
the Book H's `#int_1` style fragments that the one-off script removed, and the older
reviewed converter copies putting NCX labels before headings in SUMMARY titles.

MathJax change (2026-10-19): Tiny C and Haskell have no MathJax, and their `src/` trees are identical
before and after the change (`diff -r`, 85 and 76 files). Only the Book D row moved.

Regression round (2026-10-19, fixes R1 to R4: titles, table numbers, em/sub/sup formulas, opt-in heading and
code layouts). Each row is a scratch conversion with the fixed converter, built with `mdbook build`, then
checked with `check_links.py`. "fences" are code blocks (fence lines divided by two), "$ lines" is the count
of lines containing `$`, "pairs" the `$...$` pairs, "sub/sup" the raw `<sub>`/`<sup>` left in the output.
Every row: 0 WARN, 0 ERROR, 0 KaTeX errors, links resolve. The Modeling and Simulation row is the first
final run; the later `)<sup>digit` fix gives 257 pairs and 0 sub/sup (the reviewed book's values).
The paper and Book D rows were converted into scratch folders only (read-only EPUBs).

| Book (code language) | Link-check pages | SUMMARY pages | Images | Fences | $ lines | Pairs | sub/sup | First SUMMARY title |
|---|---|---|---|---|---|---|---|---|
| Book G (text) | 27 | 23 | 71 | 0 | 225 | 153 | 127 | Cover |
| Book H (text) | 29 | 25 | 3 | 0 | 10 | 3 | 32 | Cover |
| Book N (python) | 48 | 44 | 208 | 110 | 46 | 32 | 0 | Image page 1 |
| Book N (python) | 34 | 30 | 712 | 661 | 40 | 16 | 234 | Cover |
| Book E (python) | 46 | 42 | 133 | 611 | 184 | 257 | 0 | Cover Page |
| Book B (cpp) | 25 | 21 | 6 | 2130 | 47 | 23 | 1022 | Cover Page |
| Book C (cpp) | 26 | 22 | 59 | 567 | 23 | 0 | 0 | Cover |
| Book A (c) | 25 | 21 | 63 | 667 | 97 | 10 | 9 | Titlepage |
| Book L (python) | 18 | 14 | 38 | 948 | 332 | 589 | 28 | Cover |
| Book O (python) | 425 | 421 | 485 | 3249 | 77 | 19 | 202 | Cover |
| Book F (cpp) | 37 | 33 | 3 | 440 | 5 | 0 | 27 | Title Page |
| Book M (r) | 74 | 70 | 198 | 221 | 96 | 26 | 36 | Cover |
| Book J (text) | 32 | 28 | 48 | 0 | 0 | 0 | 0 | Cover page |
| Book I (text) | 33 | 29 | 8 | 0 | 281 | 210 | 14 | Cover |
| Book K (text) | 48 | 44 | 20 | 0 | 0 | 0 | 0 | 封面 |
| C++ Templates, Chinese edition (cpp) | 21 | 17 | 20 | 786 | 2 | 2 | 0 | C++Templates中文版 |
| Paper Q (text, read-only) | 16 | 12 | 331 | 1 | 0 | 0 | 0 | Paper Q Problem |
| Book D (python, read-only) | 374 | 370 | 300 | 655 | 173 | 313 | 8 | Cover |
| Book P (python) | 56 | 52 | 71 | 900 | 130 | 210 | 0 | Title Page |
| Parallel and Concurrent Programming in Haskell (haskell) | 30 | 26 | 49 | 625 | 274 | 12 | 143 | Cover |
| Book S part 1 (scala) | 52 | 48 | 25 | 547 | 8 | 1 | 0 | Title Page |
| Book S P2.0 (scala) | 53 | 49 | 25 | 547 | 8 | 1 | 7 | Title Page |

Corrections to the older rows, from this round: Haskell measures 625 code blocks (1250 fence lines) with
the converter before and after this round, and the old 633 figure does not reproduce (the restored
backup also has 1250 lines). Modeling and Simulation measured 595 code blocks until 2026-10-22; the
`ex-programs` exercise listings (G1 below) were prose, and the count is now 611, the reviewed value.
Remaining title findings: "int", "list", "ndarray", "pandas" (FP-style index pages in Book O) keep
their lowercase, because they are code names from the book's own headings.

Regression round (2026-10-22, fixes G1 and G2). The block count is strict: a fence is a line that starts
with three backticks in column 0, and blocks are counted as open/close pairs. Each regression row is the
original converter (before) and the fixed converter (after), converted into scratch folders and built with
`mdbook build`. The source trees are identical before and after (`diff -r`: 0 files differ, `book.toml` same).
Formulas are `$...$` pairs; sub/sup is the raw `<sub>`/`<sup>` count in `src/`.

| Book (code language) | Blocks before / after | Formula pairs | sub/sup | `$` lines | WARN / ERROR | Links |
|---|---|---|---|---|---|---|
| Book A (c) | 667 / 667 | 10 / 10 | 9 / 9 | 97 / 97 | 0 / 0 | 25 pages |
| Parallel and Concurrent Programming in Haskell (haskell) | 625 / 625 | 12 / 12 | 143 / 143 | 274 / 274 | 0 / 0 | 30 pages |
| Book F (cpp) | 440 / 440 | 0 / 0 | 27 / 27 | 5 / 5 | 0 / 0 | 37 pages |
| Book H (text) | 0 / 0 | 3 / 3 | 32 / 32 | 10 / 10 | 0 / 0 | 29 pages |

Regenerated books (same method, gated on the reviewed counts):

| Book | Reviewed blocks | Regenerated blocks | Formula pairs | sub/sup | WARN / ERROR | Links |
|---|---|---|---|---|---|---|
| Book E | 611 | 611 | 257 (reviewed 257) | 0 | 0 / 0 | 46 pages |
| Book C | 567 | 567 (566 before G2, plus the tip box) | n/a | n/a | 0 / 0 | 26 pages |

G1 (Modeling, 16 blocks): the exercise listings use the class `ex-programs`, which `CODE_CLASS_ALT` did not list,
so they stayed prose. G2 (Low Latency, 1 block): the Packt callout is a `callout-heading` paragraph followed by
`callout` paragraphs, with no div, so no admonish rule matched; it now becomes a `tip` admonish block titled
with the heading text. G1 also joins a raw line wrap inside a code paragraph (Modeling ch12, a
`results.s.plot(style=` line split by the EPUB source); `_code_paragraph_lines` handles that. Functions:
`CODE_CLASS_ALT`, `_code_paragraph_block`, `CALLOUT_RE`, `_callout_box`, `_admonish_fence`.

## Smallest quick checks

- **Clean baseline:** the Haskell book. If it stops building cleanly, the converter regressed.
- **Code stress:** QuantLib (Pygments + notebooks), then Design Patterns (cpp).
- **Structure stress:** C++ Templates (NCX with hundreds of entries), Book I (note anchors).
- **Non-English:** the Chinese fiction book.
