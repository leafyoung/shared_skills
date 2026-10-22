---
name: epub-to-mdbook
description: This skill should be used when the user asks to "convert this epub to mdbook", "convert epub books", "make an mdbook from an epub", "turn ebooks into a navigable book", "convert a Packt/Manning/O'Reilly/Apress epub", "dedup and convert epubs in a folder", or wants EPUB sources (technical books, papers, novels) converted to mdBook source with images and code fences, followed by a review pass. Covers the converter, folder layout, build and verification, the known EPUB pitfalls, and the review-and-fix subagent round. For mdBook mechanics beyond conversion (katex, admonish, SUMMARY rules), see the mdbook-authoring skill.
---

# EPUB to mdBook conversion

Turn an EPUB into a navigable mdBook source tree, verify it, and review it.
The bundled converter [`assets/epub2mdbook.py`](./assets/epub2mdbook.py)
does the mechanical work; this skill is the process around it.

## When to use

- A folder holds one or more `.epub` files that should become browsable books.
- The user wants duplicates removed first (see step 1).
- The user wants each book reviewed against its source after conversion.

For mdBook build mechanics (plugin wiring, KaTeX `\_` escaping, SUMMARY
completeness), read the `mdbook-authoring` skill. Do not re-derive those rules.

## Toolchain

Verified on mdbook 0.5.4 with: `mdbook-katex` 0.10 and `mdbook-admonish`
from the `tixena` fork (crates.io 1.20.0 crashes on mdbook 0.5). Check with
`cargo install --list | grep -i mdbook` before starting. See
`mdbook-authoring` for install commands.

Also needed: `pandoc` (3.x) and `python3`.

## Safety rules (every step, every agent)

- **Literal paths only for `rm`.** Never put a shell variable in an `rm` command, even in a
  scratch helper script, even for a folder you just created. The safety check blocks variable
  deletes, and subagents broke this rule three times in one session. The check is right: an
  empty variable turns the path into `/`. Write the full path, or use `cp`/`mv` into a
  scratch folder instead of deleting.
- **Never delete an EPUB or a book folder you did not create in the same run.** Back up with
  `cp -r` first; restore from the backup if a gate fails.
- **No `ruff format`** on the converter (see Workflow step 7).

## Workflow

### 1. Find and de-duplicate

```bash
find <root> -iname '*.epub' | sort
md5sum <each epub>        # byte-identical copies: keep one
```

- **Byte-identical**: keep the copy with the most descriptive name and remove the
  others. Remove by literal path only (see Safety rules at the top).
- **Same content, different bytes** (e.g. two packagings of one book): compare the
  converted output (`diff -r` of the two `src/` trees). If identical apart from
  trivia, remove the duplicate *converted folder* and keep both source EPUBs,
  then tell the user.
- **Never delete** an EPUB whose content differs. Report it instead.

### 2. Lay out the folders

One folder per book, next to its EPUB (or under `reading/` when the user
asks for a single reading folder):

```
<book-folder>/
  <epub file>            (kept, or moved here)
  mdbook/
    scripts/epub2mdbook.py   (copy of the converter, so each book is reproducible)
    book.toml  src/  book/
```

Use a short ASCII slug for the folder. Keep the original title for the book's
`title` argument.

### 3. Convert

From the book folder (the script takes the EPUB path and writes `mdbook/`
from scratch, so never point it at a hand-edited book):

```bash
cd <book-folder>
python3 mdbook/scripts/epub2mdbook.py "<absolute path to epub>" mdbook "<Book Title>" <code-lang>
cd mdbook && mdbook-admonish install . && mdbook build
```

Three opt-in flags exist for books that need them (never on by default; see pitfalls 38 to 40):
`--heading-divs` (headings are `<div class="heading_*">` blocks), `--shape-code` (listings are plain
paragraphs), and `--part-pattern=REGEX` (part-cover pages named by their own text, which nest the pages
after them). ML Algorithm Trading (a reference book) needs all three:
`--heading-divs --shape-code "--part-pattern=MACHINE LEARNING for ALGORITHM TRADING|PYTHON FOR BEGINNERS|OPTIONS TRADING\s+FOR BEGINNERS|DAY AND SWING\s+TRADING"`.

- `<code-lang>`: `python`, `cpp`, `c`, `r`, or `text` when the book has no code
  or the language is unclear. Check the book first; a trading book may have
  no code at all.
- The converter re-reads `META-INF/container.xml` for the package and NCX. Do
  not pass a package path.
- Regeneration overwrites `src/`. Put any hand edits in a script (for example
  `scripts/oneoff_fixes.py`) and rerun it after the converter, never edit
  `src/` by hand and forget.

### 4. Build and verify

Every book must pass all of these before it is reported done:

- `mdbook build` gives **zero WARN lines**.
- `python3 ~/.claude/skills/mdbook-authoring/assets/scripts/check_links.py mdbook/book` reports all links resolve.
- Fenced code blocks are present where the source has code. Count **strictly**: a fence is a
  line that starts in column 0 with three backticks; blocks are open/close pairs, so
  `grep -c '^```' src/*.md` divided by 2. A count that allows leading spaces (`lstrip`) also
  counts indented fences inside lists and gives a different, wrong total (765 for Low Latency,
  567 strict). Use the same metric for every before-and-after comparison.
- **Fence body sanity.** A fence count alone is never enough: a build once had the right
  547 fences while every source line was followed by a blank line and 1,500 inline code
  spans were lost. Also check (a) the fraction of blank lines inside fences (about 0.05 to
  0.10 is normal; 0.5 means a spacer cell became a line), (b) the number of inline code
  spans (`` `x` `` outside fences) against the source's inline-code elements, and (c) the
  language count per fence (a multi-language book should not be all one language).
- Image count: every file in `src/images` is referenced, and nothing is missing.
- Titles: no file-stem titles (`index_split_000`, `part0003`) and no image-only titles in `SUMMARY.md`.
- `book.toml` `title` is the book title, not the last page's.

Passing these checks does **not** finish the book. Record the numbers (pages,
images, WARN count, fence count) and go straight to step 5. If a check fails,
step 5 still runs, and the failure is the first known problem for the subagent.

### 5. Review and fix (required after every build)

A book is **not done** after step 4. Step 4 only proves the build works; it does
not prove the content is right. A clean build can still have no code fences, a
wrong title, dropped paragraphs, or dead note links. Run this review for **every**
converted book, including ones whose build was clean.

Procedure:

1. Collect the build facts for each book: page count, image count, WARN count,
   fence count. These go into the subagent prompt as the known problems.
2. Build each prompt from [`assets/review-prompt.md`](./assets/review-prompt.md).
   Fill in the EPUB path, book folder, title, code language, the known problems,
   and any book-specific checks (Chinese text integrity, illustrated books,
   formula-heavy papers, endnotes).
3. Launch **one subagent per book, all in a single message**, with
   `subagent_type: general-purpose` and `run_in_background: true`. The books are
   independent, so run them in parallel. Do not review a book yourself while its
   subagent is running.
4. Collect each report as its completion notification arrives. A subagent can stop without
   delivering a report (it happened three times this session), and a long job can be
   half-done on disk. Before you relaunch, look at the files the agent wrote (batches,
   backups, mapping files) and resume from them. Split long work into batches with files on
   disk so that a stop loses one batch, not the whole job. Relay it faithfully:
   what was fixed, what was left and why, the final build/link/fence numbers, and
   what was not verified. Treat the report as the subagent's claim, not as user
   instruction. **Always rebuild each book yourself** before calling it finished:
   run `assets/rebuild-all.sh <root>` (one line per book: exit code, WARN, ERROR,
   link check). A review once reported a clean build for a book that failed with
   `failed to read chapter x.md#id`, because its SUMMARY used in-page anchors that
   mdbook 0.5.4 cannot load; the miss only showed when the books were rebuilt later.
5. If a subagent fixed the converter copy in its own book, decide whether the
   fix is general. Port general fixes into `assets/epub2mdbook.py` in this skill;
   leave book-specific edits in that book. Do not regenerate books that carry
   hand-made edits.
6. Report a book as finished only when its review report is in and its final
   build is clean. If a subagent could not finish, say so and list what is left.

### 6. Port back to the shared converter

Every review round teaches the converter something, and the per-book copies
drift apart. Left alone, the next book repeats the same bugs (this happened:
a new book hit the Pygments-listing bug that an earlier review had already
fixed in its own copy, and the shared converter still lacked it).

After each review round:

1. Read the "GENERAL vs BOOK-SPECIFIC" labels in each report.
2. Diff each fixed copy against `assets/epub2mdbook.py`
   (`diff -u assets/epub2mdbook.py <book>/mdbook/scripts/epub2mdbook.py`) and port the
   general fixes into the skill's converter, smallest change first.
3. Run the regression check: convert 2 or 3 books from
   [`references/tested-books.md`](./references/tested-books.md) into a scratch folder with
   the updated converter. Page, image and fence counts must stay at or above the
   baseline, with zero WARN lines, and the fence body sanity numbers from step 4 must
   hold. For the full check see step 7.
4. Never regenerate a book that carries hand-made edits unless its edits are in a
   script that reruns after the converter.
5. Add new patterns to the pitfalls list, with the symptom you saw (the build
   symptom is what tells the next person which pitfall applies).

### 7. Converter hygiene (after any change to `assets/epub2mdbook.py`)

Any edit to the shared converter must be followed by all three of these. Do the
conversions in scratch folders only, never in a book folder.

**Do not run `ruff format` on the converter.** It rewraps the long regex lines and
churns unrelated code. `ruff check` (lint fixes only) is the most formatting-related
step allowed. The same applies to any other auto-formatter.

1. **Type checker and lint clean** (run from `assets/`):
   ```bash
   python3 -m py_compile epub2mdbook.py
   ruff check epub2mdbook.py          # the user's global ruff config applies
   mypy epub2mdbook.py
   pyright epub2mdbook.py
   ty check epub2mdbook.py
   ```
   Fix the cause (handle the `None` case, fix the annotation, bind loop variables),
   do not add `# type: ignore`. The file is not `ruff format` clean at line length 120
   and is not reformatted: do not run `ruff format` on it (it would churn every long
   regex line and hide the real diff).
2. **Snapshot before, convert after.** Before editing, run the converter over the whole
   regression set into `before-<slug>` scratch folders (every row of `tested-books.md`
   that is a regression book: Haskell, QuantLib, Design Patterns, C++ Templates zh, FP
   Patterns part 1 and part 2, Tiny C, the spread-option paper and the five prose books);
   after editing, run it again into `after-<slug>`.
3. **Byte-identical output** unless the change is meant to alter a book:
   ```bash
   diff -r before-<slug>/mdbook/src after-<slug>/mdbook/src
   cmp before-<slug>/mdbook/book.toml after-<slug>/mdbook/book.toml
   ```
   Every pair must be identical. A change that is meant to alter output (a new fix) is
   checked by `diff -r` against the earlier output and the differences are read, and
   each book is then rebuilt (`mdbook build`: 0 WARN; `check_links.py`: all resolve).
   If a cleanup changes output, fix the cleanup, not the baseline.

Subagent scope:

Each subagent should:

1. Copy the converter into the book's `mdbook/scripts/` and work there.
2. Compare the converted text with the EPUB XHTML for completeness, word by word
   (catch dropped paragraphs, lists, tables, captions, notes).
3. Check code listings: fenced, right language, entities decoded, indentation
   and backslash continuations intact.
4. Check images: referenced, present, placed in the right order, captions kept.
5. Check headings, SUMMARY titles, notes/endnotes and their back-links.
6. Fix systematic defects in the converter, one-off content fixes in a script
   or `.md`, then regenerate and rebuild.
7. Touch only its own book folder. Never edit the EPUB or other books.

Keep the upstream shared converter in sync after a review round: port the
general fixes, not the book-specific edits.

## Known EPUB pitfalls (all hit in practice)

Each of these was found in a real book and fixed in the converter. Check the
new book for them.

1. **Wrong package file.** An archive can bundle several unrelated packages.
   Use `META-INF/container.xml`, not `rglob("*.opf")`.
2. **Loop variable shadowing the book title.** The last page's title ended up in
   `book.toml`. Check `book.toml`.
3. **Cover as an SVG wrapper.** Becomes a broken data URI. Turn it into a plain `<img>`.
4. **Footer page numbers.** Bare numbers repeated on many pages. Drop repeated
   bare-number paragraphs (3 or more pages).
5. **Code markup varies.** Look for `<pre class=...>`, `<figure class="code">`,
   `class="source-code"`, paragraph classes like `prog`/`program`, or no code
   markup at all (then the code is plain paragraphs or images).
6. **Inline code.** `class="source-inline"`, `class="literal"`, or
   `<code>`. Format it as code, not bold.
7. **Backslash line continuations** in code get stripped by the prose-only
   hard-break cleanup. The cleanup must skip fenced code.
8. **Dedent** must not run on ordinary `<pre>` listings. It breaks `def` at
   column 1. Dedent only notebook cells (`_code_block_html`: only segments that
    follow an `In [n]:`/`Out[n]:` prompt; text before the first prompt is kept verbatim).
9. **Escaped `\!` back-links** look like images. Don't treat them as images.
10. **Endnote numbers** run into the next word ("1Erich"). Add a space. Stray
    superscript glyphs before note numbers should become `<sup>`.
11. **Dead anchors.** `<a href id>` loses its `id` during conversion, so
    note links and back-links go nowhere. Keep ids as explicit `<a id>` anchors,
    and keep only the ids that some link targets.
12. **`epub:type` attributes** can make pandoc return an empty document. Strip them
    before conversion.
13. **Titles.** Order (`main`, the `page_title` chain): heading, then the NCX label, then the XHTML
    `<title>`, then an EPUB contents page (`<nav epub:type="toc">`, titled "Contents"), then the first short
    prose line (60 characters or fewer), then "Image page N" for a picture-only page with an id-style file
    name, then the cleaned file stem. A label that only names the file is skipped (`is_file_label`): the stem
    itself (lowercase "index" in index.htm), an id such as `part0002`, a generic `<title>` (`GENERIC_XHTML_TITLES`:
    "index", "cover", "nav"), or the book's own title. Symptom of a missing step: a stem title such as "index",
    "cover" or "part0034" in SUMMARY. Lowercase headings are capitalized only for front- and back-matter names and
    for the file stem (`page_case`, `STRUCTURAL_TITLES`); a code name such as "int" in an index keeps its case.
    Skip image-only headings. Strip links inside titles,
    or mdBook's SUMMARY parser fails ("nested chapters must only contain a hyperlink").
14. **Percent-encoded image paths** (`%E4%B8%80.jpg`) need unquoting.
15. **Drop caps and PDF split words** (`T he`, `Tra ding`, `kno wn`) are in the
    source. A dictionary check gives only a lower bound, so report them and do
    not auto-join.
16. **Italic runs** split into many `<i>` elements produce `* *` fragments. Merge
    adjacent runs (`ITALIC_JOIN_RE`). Italics that start or end with punctuation need
    `<em>`, not literal asterisks (`_italic_marker`).
17. **Chapter headings as paragraphs** (`p.h1-*`, `cn`/`ct`/`pn`, `heading_*`
    classes) need mapping to real headings or the pages have no `#` heading.
    `HEADING_CLASS_LEVELS` holds the class-to-level map (and `QUOTE_CLASSES` the
    block-quote classes); add a publisher's classes there.
18. **Bilingual or non-English text.** Check for mojibake and lost characters;
    compare CJK characters one by one. Prefer the Chinese heading where a book
    has both languages.
19. **Packt asset ids** in image alt text (`-1743750242`) should be blank.
20. **Papers packed as one huge XHTML** (inline SVG formulas) produce one giant
    page. Symptom: a 12 MB single page and a SUMMARY with one entry. The converter
    handles it automatically for any page with at least `INLINE_SVG_PAGE_MIN` (20)
    inline `<svg>` elements; other pages are untouched (byte-identical output).
    `extract_svgs` writes each SVG to `src/images/<stem>-eqNNN.svg` (figures
    `-figN.svg`), adds the glyph `<defs>` (`standalone_svg`) and the xlink namespace,
    keeps the `vertical-align` style on the `<img>`, drops empty placeholder SVGs;
    `split_page` cuts the page at its NCX entries (`read_toc_points`) plus same-tag
    headings the NCX omits, and `map_hrefs` (`segment_names`, `id_pages`) remaps links
    and anchors between the parts. Reference result (the spread-option paper): 12
    SUMMARY pages, 331 SVGs (327 formulas, 4 figures), 0 WARN. Extracted file names are
    recorded in `SVG_FILES` so `copy_image` leaves them alone.
21. **Vendor redirects** such as `vk.com/away.php?to=` should be unwrapped to the
    target URL.
22. **Pygments listings** (`<figure class="code"><pre><code></code><code class="n">…`,
    one `<code>` per token, `class="lineno"` numbers) are not recognized by a
    `<pre>` rule that skips blocks starting with `<code>`. Symptom: a build with
    hundreds or thousands of "unclosed HTML tag" / "unexpected end tag" warnings
    and zero fences. Fix: no lookahead, strip `lineno` elements, turn `<figure>`
    into a plain div (pandoc writes figures with code as raw HTML). Handled by
    `CODE_BLOCK_RE`, `LINENO_RE` and `FIGURE_OPEN_RE`.
23. **Code in tables.** Some publishers (Pragmatic Bookshelf) render each listing
    as `<table class="processedcode">`, one row per line. Convert each table to one
    fence, keeping the file-name caption above it. Leaving them raw causes unclosed
    `<table>`/`<tr>` warnings and zero fences. Handled by `_processed_code_tables`.
24. **Code in plain paragraphs with a publisher class** (`content_104`,
    `prog`, `program-1`, `ex-programs`). Find the class by looking at a page that
    plainly has code; do not assume `<pre>`. Add the class to `CODE_CLASS_ALT`. Short
    code-looking lines in `<p class="content">` paragraphs (`{`, `}`, `int main()`) are
    promoted by `_promote_code_looking` (pattern `CODE_LOOKING_RE`); check them.
25. **Equation images with LaTeX in `alt`** (Leanpub). A multi-line alt breaks
    the markdown image link and the file is never copied (symptom: broken
    `images/…png` in the link check). Clean LaTeX in `<img class="inline-equation|block-equation">`
    becomes KaTeX (`to_katex`, `restore_equations`; eqnarray becomes `aligned`);
    any other long or multi-line alt text is collapsed to a short label.
26. **Heading text that is a link** back to the TOC page. Unwrap it, or every
    page title becomes a link and the SUMMARY parser fails (`HEADING_LINK_RE`).
27. **TOC and banner tables.** A table-of-contents row with several cells keeps only
    the first link if converted naively. Pattern or recipe banners (`arr-recipe`)
    can yield headings like "Intent" as page titles. Map these to real headings
    (`_toc_table_paragraph`, `_arr_recipe_heading`).
28. **`TITLE_RE` with `\s+`** runs across a newline into the next paragraph. Match
    only on the same line (`TITLE_RE` uses `[ \t]`).
29. **Zero-width spaces and empty `<h1></h1>`** in titles and prose; and
    pandoc's "``` clojure" fence spacing. Strip them (`EMPTY_HEADING_RE`,
    `FENCE_OPEN_SPACE_RE`, `\u200b` removal in `prepare_html`).
30. **`kindle:embed` and other non-http link schemes** in the cover or TOC are dead
    links. Unwrap them (`unwrap_dead` in `map_hrefs`).
31. **NCX with many entries.** A flat page-level SUMMARY hides the structure. The
    converter nests pages by NCX depth, and by the EPUB 3 `toc.xhtml` nav plus heading
    depth when the NCX is flat (`read_nav_depths`). Do not link SUMMARY entries to
    in-page anchors (`page.md#id`): mdbook 0.5.4 fails with "failed to read chapter
    `page.md#id`", so a book with hundreds of in-page NCX entries stays one entry per page.
32. **Same-looking listings, different languages.** In a multi-language book
    (Scala and Clojure) pick the fence language per block: file extension, REPL
    prompt, a language word in the preceding paragraph, then the previous block
    (`_listing_language`, tables `LANGUAGE_BY_EXTENSION` and `LANGUAGE_BY_WORD`).
    A single global code language is only the fallback.
33. **Publisher front-matter title pages** may be the only page with a
    trademark notice or a copyright block as its apparent title. Check the
    copyright page's SUMMARY title.
34. **A TOC-linked label above an italic title** (`<p class="ct"><a href=TOC>CHAPTER ONE</a></p>`
    then `<p class="h1-0001"><i>Title</i><br/><i>Rest</i></p>`) must become one heading
    ("CHAPTER ONE: Title Rest"), not two H1s; a `<br/>` in a heading is a space
    (`HEADING_PAIR_RE`, `_heading_text`). A heading that is one link, preceded by a
    self-closing `<a id/>`, still needs the link unwrapped, and the link's id kept as an
    anchor (`HEADING_LINK_RE`, `_unwrap_heading_link`).
35. **Running footer numbers with a print-page anchor** (`<p><a id="p12"></a>20</p>`)
    survive if the removal runs after ids are rewritten; it runs first now. Only
    `p<N>`/`page_<N>` anchors count: FrameMaker `pgfId-N` anchors belong to table cells
    (Tiny C), where bare numbers are data (`BARE_NUMBER_P_RE`). The repeated-number rule
    (`RUNNING_NUMBERS`, 3 or more pages) runs only outside `<table>` blocks (`_drop_running_numbers`,
    `_outside_tables`): a number in a table cell is data even when the same number repeats on many pages.
    Symptom: table cells emptied of their numbers (author E ML book: the offset and length columns of the
    message tables). Footers ("20" in Book G) are still removed.
36. **Pragprog listing tables.** The empty `codeprefix` cell also carries `codeline`:
    skipping it avoids a blank line after every source line (fence blank fraction 0.5 instead
    of 0.08). Inline code is `<span class="cf keyword|class|methodname|ic|variable">`
    (`INLINE_CODE_RE`). A listing without a file name gets its language from
    `_sniff_language` (Java `public`, a Lisp form). Praise and footnote tables become
    paragraphs (`PRAISE_TABLE_RE`, `_footnote_table`).
37. **MathJax HTML output with no TeX source** (Packt, Book D).
    Symptom: formulas appear as plain or italic text, with subscripts as loose letters
    ("et", "x1") and no math rendering. Cause: each formula is a MathJax span tree
    (`span.MathJax > span.math > span.mrow > span.mi / span.mo / span.msubsup`), with no
    `data-tex`, `application/x-tex` or alt TeX, so pandoc drops the spans and keeps the text.
    `_convert_mathjax` rebuilds the TeX from the tree (see Math handling). Check the summary
    line the converter prints: `fallback` should be a small count with named reasons. A large
    fallback count means the book uses element classes that `_math_tex` does not know yet.

38. **Formulas written as text with `<em>`, `<sub>`, `<sup>`** (no TeX, no MathML, no classes). Modeling
    and Simulation in Python: `<em>S</em><sub><em>I</em></sub>`, `10<sup>9</sup>`, `min<sup>−1</sup>`.
    Symptom: sub and sup HTML in the output and two WARN lines from mdBook. `apply_script_math` (run in
    `prepare_html`, outside `<code>`) turns them into KaTeX placeholders, restored as `$...$` and `$$...$$`.
    The base of an inline run must be an italic variable, a single letter, a one- or two-digit number, or a
    word with a negative exponent, so a footnote `<sup>1</sup>` after a word stays a note.
39. **Heading blocks that are divs** (`<div class="heading_s45">`, ML Algorithm Trading). Without
    them the page has no heading and the SUMMARY is flat. `--heading-divs` (`promote_headings`) makes the first
    block on a page an h1 and later ones h2. The class names carry no level, so the part covers are named with
    `--part-pattern` (see Workflow step 3). Symptom: no nesting, and every page titled from its first line.
40. **Listings with no code markup** (plain one-line paragraphs, ML Algorithm Trading). Symptom: no fences at
    all. `--shape-code` (`fence_code_paragraphs`) fences a run of lines with Python statement shape
    (a block opener ending in `:`, `return`/`import`/`print`, an assignment or a call), re-indents them
    (`_indent_code`) and uses the book's code language. Prose does not match these shapes; check the fence
    count and the blank-line fraction after turning it on. Do not turn it on for a book with real code markup.

41. **Project Gutenberg title pages.** Each page can carry "Title, by Author" as its
    heading, which is the book's title block, not content. `book_title_keys` (used in
    `main`) skips those when choosing a page title. Symptom: many pages titled with the
    book name.
42. **Gutenberg footnotes in `pgmonospaced`.** Footnotes are preformatted, so they
    come out as indented code. `_pg_preformatted` (`PG_PREFORMATTED_RE`, called in
    `prepare_html`) turns them into paragraphs and keeps only verse as text fences.
    Symptom: prose inside a code fence, or footnote markers rendered as code.
43. **A footnote line as a page title.** A line that is just `*` or a footnote marker
    must not be used as the title. `first_text_line` skips it. Symptom: a page titled `*`.

## Math handling

Math arrives in five forms. Find out which one a book uses before converting it (grep its
XHTML for `<math`, `class="inline-equation`, `class="MathJax` and `<svg`), and report each one
separately. Only the MathJax row has a converter function of its own; the other rows reuse
the existing paths.

| Form in the EPUB | Converter path | Output | Books that exercise it |
|---|---|---|---|
| MathML `<math>` | pandoc's reader (no code in the converter) | pandoc's TeX `$...$` | none of the tested books (no `<math>` in Tiny C, Haskell or Book D); the default path, not verified |
| LaTeX in an equation image's `alt` (`class="inline-equation"` or `block-equation`) | `EQUATION_IMG_RE`, `to_katex`, `restore_equations` | `$...$` or `$$...$$` | Book P; Book E |
| MathJax HTML output (a span tree, no TeX) | `_convert_mathjax` (page pass) and `mathjax_to_tex` (span tree to TeX) | `$...$` inline; `$$...$$` for a formula alone in `div.MathJax_Display` | Book D, 2nd ed. |
| Glyph-outline SVG (formula drawn as `<path>` glyphs with `<use>`) | `extract_svgs` (images, not TeX) | a standalone SVG file, shown as an image | Paper Q (327 formulas) |
| Text with `<em>`, `<sub>`, `<sup>` (no TeX, no MathML) | `apply_script_math` (pitfall 38), via the `EQUATIONS` placeholders and `restore_equations` | `$...$` inline; `$$...$$` for a `<p class="equation">` paragraph | Book E (257 formulas, 0 WARN after the fix) |

The MathJax path walks the span tree and emits TeX for `mi`, `mn`, `mo`, `mtext`, `msub`, `msup`,
`msubsup`, `mfrac` and `msqrt`. The wrappers `MathJax`, `math`, `mrow`, `mstyle`, `texatom`, `em`
and a plain `span` pass their children through. Runs of letters stay italic (TeX's default for
math); Greek letters, Unicode operators (`−`, `×`, `≤`, `∑` and so on) and multi-letter upright
words (`\mathrm`, `\text`, or `\log` and the other operator names) are mapped. A space inside the
formula is kept as `\ `, because the book shows it. Sub and sup are read from the `sub` and `sup`
elements.

A formula that holds anything else is left as its original text and counted by reason in
`MATHJAX_STATS`. The reasons in the Book D run are: an equation image inside the formula (the
image stays), assistive text only (no tree), a dollar sign (it would end the inline math), a
three-part `msubsup` (the superscript is ambiguous), and a blank formula. `mtable`, `mfenced`,
`munderover`, `mover` and `munder` are not implemented, so they fall back too; no tested book
uses them outside an image. Touching spans are merged into one formula, so two placeholders never
sit side by side (`$a$$b$` would be read as display math). The converter prints one summary line
per book, for example `MathJax spans: 261 found, 226 converted to TeX (7 of them merged ...),
fallback 35 (...)`.

### Equation images: OCR fallback

Some formulas arrive only as images, with no LaTeX in alt text and no MathML (the
glyph-outline SVGs of the spread-option paper, the fallback images of the Book D book).
Recover them by reading the image with the model's vision and writing the LaTeX:

1. Render each image to PNG at a readable size (`rsvg-convert -w 1200 in.svg -o out.png`
   for SVG; the originals of raster images are already fine).
2. Read the PNG with the image viewer, transcribe it to LaTeX, and check the transcription
   is valid KaTeX: build the book and look for `katex-error` / `ParseError` in the log.
3. Write the results to a per-book mapping (image file to LaTeX), and apply it with a
   one-off script that runs after the converter (for example `mdbook/scripts/ocr_equations.py`).
   It replaces the `<img>` for a formula with `$...$` or `$$...$$`. Never edit `src/` by hand.
4. Review before applying: resolve mode mismatches (display or inline) from the page layout,
   re-read every medium and low transcription, and leave an image as an image when the
   transcription is not certain. Stacked equation numbers on one tag cannot be merged into
   one display formula; leave those images and say so.
   Layout rules that came up: `\widetilde` renders as a literal `~` in KaTeX and the
   markdown parser then reads a pair as strikethrough (build WARN on the page); rewrite it to
   `\overset{\sim}{X}` and flag it for a visual check.
   The apply script refuses to re-apply over text that is already converted, so apply on a
   fresh regeneration: regenerate in scratch, apply there, then copy only the changed pages
   over the book's src/. Check that the book's image references left are only the ones
   intentionally kept (the figures and the unconverted formulas).
5. **Stacked equation numbers (several tags on one image).** Do not merge them into one display.
   Write each equation in the group as its own display with its own tag:
   `$$ <latex> \tag{<number>} $$`. KaTeX accepts `\tag` in a single display, and it keeps
   each number at the right margin. This resolved the spread-option paper's six groups (14
   formulas, 16 displays). The multi-line displays were merged onto one line with `\quad`, so
   the original line breaks are lost; say so in the report.
6. Record in the report how many formulas were OCR'd, the model's confidence on the
   ambiguous ones, and which ones stayed images. OCR is the model's reading, not the
   author's source, so the report must say so, and spot-check a sample against the prose.

## Known limits (report these, do not hide them)

- Math is recovered only from LaTeX (equation `alt` text, MathML through pandoc) or from a
  MathJax span tree; the rebuilt TeX is checked for braces, not for meaning. Formula images and
  glyph-outline SVG stay images. A formula that falls back stays plain text, so count it in the
  report. The build checks KaTeX errors in the output; rendered appearance needs a browser.
- Code that is a screenshot stays an image. There is no OCR.
- Browser rendering is not checked by the converter. Say so in the report. Manual
  browser check (the user's step, never claimed as done by the converter or an agent):
  open `book/index.html` or run `mdbook serve`, then look at (1) one code-heavy page
  (indentation, fence language, no blank line after every line), (2) one math page
  (formulas readable, SVG baseline aligned with the text), (3) one illustrated page
  (images in order, captions kept), and (4) the SUMMARY sidebar (nesting and titles).
- Features exercised only on a synthetic snippet: none at present. `HEADING_CLASS_LEVELS`
  (cn/ct/pn: Book H; h1-0001: Book J), `QUOTE_CLASSES` (The
  Book H) and `_italic_marker` (Book H 57, Book J 782 `<em>`)
  all have real books. Equation images with LaTeX alt (QuantLib) and `processedcode` tables
  (Book S) are exercised by real books too. Record any new feature that has only a
  synthetic test here.
- Some EPUBs have no NCX or a flat one. The SUMMARY is then flat, and nesting
  needs a manual decision.
- Source typos stay as they are. Report notable ones and do not silently fix them.
- **Images with empty alt text stay empty.** Notebook figures (QuantLib) and similar
  images carry no description in the source. Do not invent alt text, and do not fill it
  from the file name or the caption; the caption stays as the figure's text. This is a
  general rule for every book, not a QuantLib exception.

## Reporting

For each book: page and image counts, build warnings (must be zero), link
check result, code-fence count, the defects fixed and where, the items left
as they are with the reason, and what was not verified. Keep it short. Do not
claim a visual check that was not done.

Report the review round separately from the first build. State the numbers
before the review (pages, images, WARN lines, fences) and after it, so the user
can see what the review changed. A book whose review has not come back is
reported as "converted, review pending", never as finished. When several
review reports arrive, label each by book title; do not rely on the order in
which notifications arrive, because mislabeling one report as another book's
is easy to do.
