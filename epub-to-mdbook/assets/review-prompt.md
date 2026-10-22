# Review-and-fix subagent prompt template

Fill every `<...>` placeholder, then pass the text as the `prompt` of an Agent call
(`subagent_type: general-purpose`, `run_in_background: true`). Launch one agent per
book, all in the same message, so they run in parallel.

Fill in:
- `<EPUB>`: absolute path of the source EPUB.
- `<BOOK_DIR>`: the book folder (the one that contains `mdbook/`).
- `<TITLE>`: the book title passed to the converter.
- `<LANG>`: the code-block language (`python`, `cpp`, `c`, `r`, `scala`, `haskell`, `text`).
- `<KNOWN_PROBLEMS>`: what the first build already showed (zero fences, N warnings, wrong
  titles, missing images). Write `none seen` if the build was clean. Always include the
  fence count, the warning count and the image count from the build.
- `<BOOK_SPECIFIC_CHECKS>`: extra checks for this kind of book (Chinese text integrity,
  illustrated book image placement, paper equations, notes/endnotes).

---

Review and fix an EPUB-to-mdBook conversion.

Source EPUB (read it by unzipping a copy into your scratchpad; do NOT modify the original):
<EPUB>
Converted book: <BOOK_DIR>/mdbook (src/SUMMARY.md, src/NNN-*.md, src/images/, book.toml)
Converter copy: <BOOK_DIR>/mdbook/scripts/epub2mdbook.py (copied from
~/.claude/skills/epub-to-mdbook/assets/epub2mdbook.py). Regenerate with:
cd <BOOK_DIR> && python3 mdbook/scripts/epub2mdbook.py "<EPUB>" mdbook "<TITLE>" <LANG>
then run `mdbook-admonish install .` and `mdbook build` inside mdbook. The converter
regenerates mdbook/src from scratch, so put one-off content edits in a script
(e.g. mdbook/scripts/oneoff_fixes.py) and rerun it after the converter. Never hand-edit
src/ and leave it unrecorded.

Known problems to start from:
<KNOWN_PROBLEMS>

Review checklist (cover every page, not just the first chapters; use chunked reads or
sub-subagents for large books):
1. Text completeness versus the EPUB XHTML, word by word: no dropped paragraphs, lists,
   tables, sidebars, captions or notes.
2. Code listings: fenced, right language, exact content, entities decoded, indentation
   and backslash continuations intact, inline code formatted as code. If the source has
   code but the count of fences is zero, find the real code markup and teach the converter.
3. Tables: every row and cell present; no unclosed raw HTML tags (they cause build warnings).
4. Images: all referenced, none missing, in the EPUB's order, captions kept; alt text not
   an opaque id.
5. Headings, SUMMARY titles (no file-stem, image-only, UUID or nested-link titles), the
   cover and front matter kept, `book.toml` title is the book title.
6. Notes/endnotes and internal links; back-links resolve.
7. Stray artifacts: span or anchor noise, page-number footers, raw HTML that should be markdown.
8. The known EPUB pitfalls in the epub-to-mdbook skill.
<BOOK_SPECIFIC_CHECKS>

Rules:
- Fix systematic defects in the converter copy; use a one-off script for content edits.
- Only touch files inside <BOOK_DIR>/ and your scratchpad. Do not touch the EPUB, other
  books, other folders or the images.
- Do not run rm with shell variables; use literal paths only. Do not git commit.

Verify before reporting:
- `mdbook build` gives zero WARN lines.
- `python3 ~/.claude/skills/mdbook-authoring/assets/scripts/check_links.py mdbook/book`
  reports all links resolve.
- The fence count is non-zero if the source has code, and matches the code you found.

Final report (under 300 words): defects found, what you fixed (file names), what you left
and why, the final build, link, fence, table and image results, and what you could not
verify (say plainly that browser rendering was not checked if it was not).

Label every converter fix as GENERAL (would help other EPUBs: markup patterns, title and
link handling, escaping) or BOOK-SPECIFIC (publisher class names used by one book, a
single page's label, typo repairs). The caller ports only the GENERAL ones back into the
skill's shared converter, so be exact about which is which and which function or regex
carries each fix.
