"""Convert an EPUB into an mdBook source tree.

Usage: python3 epub2mdbook.py <epub> <book-dir> <title> [code-language] [--heading-divs] [--shape-code]
                                  [--part-pattern=REGEX]

--heading-divs, --shape-code and --part-pattern are opt-in layouts (see the Opt-in layouts section): for books
whose headings are heading_* divs, whose listings are plain paragraphs, and whose part covers are named by
their text. Other books run without them.

Reads the spine from the OPF, runs pandoc on each XHTML page (spans and divs
stripped), copies images into src/images/, rewrites intra-book links to the
new .md names, and writes src/SUMMARY.md. Output is only the book source; the
build step (mdbook build) and the link check are run separately.

A page that holds many inline SVGs (a journal article packed into one XHTML file,
every formula an <svg>) gets two extra steps, see INLINE_SVG_PAGE_MIN: each SVG is
written to src/images/ as a standalone file, and the page is split into several
output pages at its NCX entries (plus same-tag headings the NCX omits). Every other
page goes through the normal one-page path, with unchanged output.
"""

import html as htmllib
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import zipfile
from collections import Counter
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree as ET

OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
NCX_NS = "{http://www.daisy.org/z3986/2005/ncx/}"
CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
NCX_MEDIA_TYPE = "application/x-dtbncx+xml"
TITLE_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)  # [ \t] not \s: "\s+" would run into the next paragraph of an empty heading
EMPTY_HEADING_RE = re.compile(r"^#{1,6}[ \t]*\n", re.MULTILINE)  # an EPUB <h1></h1> with no text
IMG_RE = re.compile(r"(?<!\\)!\[([^\]]*)\]\(([^)\s]+)\)")  # "\![" is an escaped bang before a link, not an image
RAW_SRC_RE = re.compile(r'src="([^"]+)"')
LINK_RE = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")
CODE_LANGUAGE = "cpp"  # set from the command line; the code-block language of the book
CODE_BLOCK_RE = re.compile(r'<pre(?:\s[^>]*)?>(.*?)</pre>', re.DOTALL)
# Pygments listings put an empty <code></code> first and a <code class="lineno"> number before each line.
LINENO_RE = re.compile(r'<(span|code) class="lineno">.*?</\1>', re.DOTALL)
FIGURE_OPEN_RE = re.compile(r"<figure\b[^>]*>")
FIGCAPTION_RE = re.compile(r"<figcaption>(.*?)</figcaption>", re.DOTALL)
BOX_TAG_RE = re.compile(r"<(/?)div\b([^>]*)>")
# A Jupyter prompt starts a line: "In [3]:" or "Out[3]:", with the cell's first line either after it
# (Leanpub/Pygments style "In [3]: code") or on the following lines (Packt style).
JUPYTER_PROMPT_RE = re.compile(r"^\s*(In|Out)\s*\[[^\]]*\]\s*:(?: |$)")
# Unprompted text in a Python book that shows C++ (an #include, a std:: name, a const declaration, a ; line end).
CPP_HINT_RE = re.compile(r"#include|\bconst\b|\w::\w|;\s*$", re.MULTILINE)
BOX_CLASSES = {"packt_tip": "tip", "packt_infobox": "info"}
ADMONISH_MARK_RE = re.compile(r"^ADMONISHOPEN(TIP|INFO)(?: ([^\n]*))?$|^ADMONISHCLOSE$", re.MULTILINE)  # group 2: title
# Packt's callout boxes are two plain paragraphs with no div: a heading paragraph, then the body paragraph(s).
CALLOUT_RE = re.compile(r'<p class="callout-heading">(.*?)</p>\s*((?:<p class="callout">.*?</p>\s*)+)', re.DOTALL)
INLINE_CODE_RE = re.compile(r'<([A-Za-z]+) class="(?:source-inline|literal|cf [a-z]+)">(.*?)</\1>', re.DOTALL)  # "cf *": Pragprog's inline code spans
# Runs of consecutive code paragraphs become one block. CODE_CLASS_ALT lists the paragraph classes that hold code:
# Manning-style "prog"/"program" plus publisher classes (the Chinese C++ Templates edition's "content_104".."content_123")
# and "ex-programs" (exercise listings in Book E). Add another publisher's code class here.
CODE_CLASS_ALT = r"prog|(?:ex-)?programs?|program-\d+|content_(?:10[4-9]|11\d|12[0-3])"
CODE_PARAGRAPH_RUN_RE = re.compile(rf'(?:<p class="(?:{CODE_CLASS_ALT})"[^>]*>.*?</p>\s*)+', re.DOTALL)
CODE_PARAGRAPH_RE = re.compile(rf'<p class="(?:{CODE_CLASS_ALT})"[^>]*>(.*?)</p>', re.DOTALL)
# Some EPUBs mark code lines as plain prose paragraphs (class "content"). Lines that look like code by structure
# (braces, preprocessor directives, declarations ending in ; or {, comment-aligned statements) are promoted to the code class.
PROSE_CODE_PARAGRAPH_RE = re.compile(r'<p class="content"([^>]*)>(.*?)</p>', re.DOTALL)
CODE_LOOKING_RE = re.compile(
    r"^\s*(?:[{}]|#\s*(?:include|define|ifdef|ifndef|endif|if|else|pragma)\b.*|template\s*<.*"
    r"|(?:class|struct|union|enum)\s+\w.*[{;]\s*|(?:int|void|char|bool|double|float|long|unsigned|extern|static"
    r"|const|typedef|using|namespace|return|typename)\b.*[;{]\s*|int\s+main\s*\(.*|.*(?:\u3000|\s){2,}//.*)$"
)
# A heading that is one link (a Packt/Chinese-edition TOC back-link, possibly after an empty or self-closing id anchor)
# keeps only its text; the link's own id stays as an anchor, since note links may target it.
HEADING_LINK_RE = re.compile(
    r'(<h[1-6]\b[^>]*>\s*(?:<a\s[^>]*(?:/>|></a>)\s*)?)<a\s+href="[^"]*"([^>]*)>(.*?)</a>\s*(</h[1-6]>)', re.DOTALL
)
# Publisher paragraph classes that stand for headings (cn = chapter number, ct = chapter title, pn = part label,
# h1-0001/h2-0001 = Packt titles) and for block quotes. Add another publisher's classes here.
HEADING_CLASS_LEVELS = {"pn": 1, "cn": 1, "ct": 2, "h1-0001": 1, "h2-0001": 2}
QUOTE_CLASSES = ("quotet", "iquotet", "quoteind")
# A label paragraph and the title paragraph after it become one heading: cn + ct ("ONE: Dragon"), or ct + h1-0001
# (a linked "CHAPTER ONE" label above an italic title).
HEADING_PAIR_RE = re.compile(
    r'<p class="(?:cn|ct)"[^>]*>(.*?)</p>\s*(?:<p class="line"\s*/>\s*)*<p class="(?:ct|h1-0001)"[^>]*>(.*?)</p>', re.DOTALL
)
_HEADING_ALT = "|".join(HEADING_CLASS_LEVELS)
_QUOTE_ALT = "|".join(QUOTE_CLASSES)
HEADING_PARAGRAPH_RE = re.compile(rf'<p class="({_HEADING_ALT})"[^>]*>(.*?)</p>', re.DOTALL)
QUOTE_RUN_RE = re.compile(rf'(?:<p class="(?:{_QUOTE_ALT})"[^>]*>.*?</p>\s*)+', re.DOTALL)
QUOTE_PARAGRAPH_RE = re.compile(rf'<p class="(?:{_QUOTE_ALT})"[^>]*>(.*?)</p>', re.DOTALL)
# An <i> whose text starts or ends with punctuation (or a space) cannot be a Markdown *emphasis* run (CommonMark
# flanking rules leave the asterisks literal), so it is marked here and turned into <em> after pandoc.
ITALIC_RE = re.compile(r"<i>([^<]*)</i>")
ITALIC_OPEN, ITALIC_CLOSE = "ZQEMOPENZQ", "ZQEMCLOSEZQ"
# Packt/Pragprog listing tables (one row per source line) and the Pragprog pattern banner and TOC tables.
PROCESSED_CODE_RE = re.compile(r'<table class="processedcode"[^>]*>(.*?)</table>', re.DOTALL)
LISTING_FILE_RE = re.compile(r'<tr class="livecodelozenge">\s*<td[^>]*>\s*<a [^>]*>(.*?)</a>', re.DOTALL)  # first row: source file name
CODELINE_CELL_RE = re.compile(r'<td[^>]*class="codeline"[^>]*>(.*?)</td>', re.DOTALL)
LANGUAGE_BY_EXTENSION = {"scala": "scala", "clj": "clojure", "cljs": "clojure", "java": "java"}  # add a book's languages here
LANGUAGE_BY_WORD = {"scala": "scala", "clojure": "clojure", "java": "java"}  # language word in the paragraph before a listing
_LISTING_WORD_ALT = "|".join(w.capitalize() for w in LANGUAGE_BY_WORD)
PRE_LISTING_RE = re.compile(rf"(?:^|\s)({_LISTING_WORD_ALT})(?=\s|[.,;:)]|$)")
REPL_PROMPT_RE = re.compile(r"^\s*(?:scala>|user=>|=>)", re.MULTILINE)
ARR_RECIPE_RE = re.compile(
    r'<table class="arr-recipe"[^>]*>\s*(<a id="[^"]*"></a>)?\s*<tr>\s*<td class="arr-recipe-number">(.*?)</td>\s*'
    r'<td class="arr-recipe-name[^"]*">(.*?)</td>\s*</tr>\s*</table>',
    re.DOTALL,
)  # pattern banner: "Pattern 5" | "Replacing Iterator"
TOC_TABLE_RE = re.compile(r'<table class="table-of-contents2"[^>]*>(.*?)</table>', re.DOTALL)
FENCE_OPEN_SPACE_RE = re.compile(r"^(\s*)``` +(\S+)\s*$", re.MULTILINE)
# Leanpub exports equations as <img class="inline-equation|block-equation" alt="LaTeX source">.
EQUATION_IMG_RE = re.compile(r'<img\b(?=[^>]*\sclass="(inline|block)-equation")[^>]*>')
EQUATION_PLACEHOLDER_RE = re.compile(r"EQUATIONPLACEHOLDER(INLINE|BLOCK)(\d+)X")
EQUATIONS: list[str] = []  # KaTeX sources, indexed by placeholder number; filled while pages are prepared
# Formulas written as text with <em>, <sub> and <sup> (no TeX, no MathML): S<sub>I</sub>, m/s<sup>2</sup>. The base of an
# inline run is an italic variable or a single letter, so a footnote <sup>1</sup> after a word is not a formula.
SCRIPT_EQUATION_P_RE = re.compile(r'<p class="equation1?"[^>]*>(.*?)</p>', re.DOTALL)
SCRIPT_EM_RE = re.compile(r"<em>([^<]+?)<(sub|sup)>(.*?)</\2></em>", re.DOTALL)  # <em>T<sub>env</sub></em>: italic base
SCRIPT_RUN_RE = re.compile(
    r"(<em>[^<]+</em>|(?<![A-Za-z])[A-Za-z](?![A-Za-z])|(?<![A-Za-z])[A-Za-z]+(?=<sup>[−-])|(?<![\w.])\d{1,2}(?=<(?:sub|sup)>)"
    r"|\)(?=<sup>\d))"
    r"((?:<(?:sub|sup)>.*?</(?:sub|sup)>)+)",
    re.DOTALL,
)  # min<sup>−1</sup> (a unit with a negative exponent), 10<sup>9</sup> (a short number) and (x)<sup>2</sup> are formulas
SCRIPT_PIECE_RE = re.compile(r"<em>(.*?)</em>|<sub>(.*?)</sub>|<sup>(.*?)</sup>|<[^>]+>|([^<]+)", re.DOTALL)
SCRIPT_SYMBOLS = {"–": "-", "−": "-", "×": r"\times ", "·": r"\cdot ", " ": " ", " ": " ", "’": "'", "%": r"\%", "&": r"\&", "#": r"\#"}
# MathJax HTML output (Packt, Apress): a formula is a span tree with no TeX source, rebuilt by _convert_mathjax.
# A display formula is the span inside a div.MathJax_Display; the other MathJax_Display elements are prose paragraphs.
MATHJAX_START_RE = re.compile(r'(<div class="MathJax_Display[^"]*">\s*)?<span class="MathJax">')
MATHJAX_SPAN_TAG_RE = re.compile(r"<span\b[^>]*>|</span>")
MATHJAX_CLOSE_DIV_RE = re.compile(r"\s*</div>")
EM_AROUND_EQUATION_RE = re.compile(r"<em>\s*(EQUATIONPLACEHOLDERINLINE\d+X)\s*</em>")  # the math is italic already
MATHJAX_STATS: Counter[str] = Counter()  # "found", "converted", and "fallback: <reason>" per formula; printed by main()
INDEX_LINK_RE = re.compile(r'<a [^>]*class="index"[^>]*>(.*?)</a>', re.DOTALL)
HREF_RE = re.compile(r'href="([^"]+)"')
ID_ELEMENT_RE = re.compile(r'<([A-Za-z][A-Za-z0-9]*)\b[^>]*?\sid="([^"]+)"[^>]*>')
REFERENCED_IDS: set[str] = set()  # ids that some intra-book link points at; filled in main()
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IMG_TAG_RE = re.compile(r"<img [^>]*>")
SRC_ATTR_RE = re.compile(r'src="([^"]*)"')
ALT_ATTR_RE = re.compile(r'alt="([^"]*)"')
KEPT_ANCHOR_RE = re.compile(r'<span id="([^"]+)"></span>')
SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.DOTALL)
EMPTY_SPAN_RE = re.compile(r"<span[^>]*/>")
SLUG_RE = re.compile(r"[^a-z0-9]+")
SVG_IMAGE_RE = re.compile(r'<svg\b(?:(?!</svg>).)*?<image\b[^>]*?href="([^"]+)"[^>]*>(?:(?!</svg>).)*</svg>', re.DOTALL)  # cover SVG wrapping one bitmap
EPUB_TYPE_ATTR_RE = re.compile(r'\sepub:type="[^"]*"')  # pandoc returns an empty document when these are present
ITALIC_JOIN_RE = re.compile(r"</i>(\s*)<i>")  # EPUB splits one italic run into many <i> elements
NUMERIC_ALT_RE = re.compile(r"-?\d+")  # image alt text that is only an asset id, not a description
# A bare number paragraph, optionally after an empty PDF print-page anchor (id "p12"/"page_12"; other anchors such as
# FrameMaker "pgfId-N" belong to table cells and real numbers, not to footers).
BARE_NUMBER_P_RE = re.compile(r'<p\b[^>]*>\s*(?:<a\s+id="(?:p|page[-_]?)\d+"\s*(?:/>|>\s*</a>)\s*)?(\d{1,4})\s*</p>')
RUNNING_MIN_PAGES = 3  # a bare number paragraph on at least this many pages is a running footer
RUNNING_NUMBERS: set[str] = set()  # filled in main()
TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table>", re.DOTALL)  # table cells hold data: a bare number there is not a footer


def _outside_tables(text: str) -> str:
    """Return the page text with every table removed, so a number in a table cell is never a running footer."""
    return TABLE_BLOCK_RE.sub(" ", text)


def _drop_running_numbers(text: str) -> str:
    """Remove the bare-number footer paragraphs (RUNNING_NUMBERS) outside tables; tables are copied unchanged.

    Args:
        text: Page HTML.

    Returns:
        The HTML without running-footer number paragraphs.
    """
    def drop(match: re.Match[str]) -> str:
        """Empty a footer paragraph; keep any other match."""
        return "" if match.group(1) in RUNNING_NUMBERS else match.group(0)

    out: list[str] = []
    position = 0
    for table in TABLE_BLOCK_RE.finditer(text):
        out.append(BARE_NUMBER_P_RE.sub(drop, text[position:table.start()]))
        out.append(table.group(0))
        position = table.end()
    out.append(BARE_NUMBER_P_RE.sub(drop, text[position:]))
    return "".join(out)
# PDF-derived EPUBs print endnote markers as Unicode superscript glyphs followed by the note number.
ENDNOTE_MARK_RE = re.compile(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+(\d{2,3})(?!\d)")
ENDNOTE_NUMBER_RE = re.compile(r'<span class="endnote-number">([^<]*)</span>')  # "1</span>Erich" would read "1Erich"
TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
DC_TITLE_TAG = "{http://purl.org/dc/elements/1.1/}title"
# Project Gutenberg preformatted block: footnotes (first line starts with "*") or verse (see _pg_preformatted)
PG_PREFORMATTED_RE = re.compile(r'<div\b[^>]*\bclass="pgmonospaced"[^>]*>(.*?)</div>', re.DOTALL)
# Page titles (see main): an XHTML <title> that only names the file ("index", "cover", "nav") is not a title, an id-like
# label ("part0002", "bm01") is not a title, a first prose line longer than TITLE_MAX_CHARS is a paragraph.
GENERIC_XHTML_TITLES = {"cover", "index", "nav", "untitled", "titlepage", "title", "html"}
# Front- and back-matter names (folded: no spaces or punctuation). A lowercase heading with one of these names is capitalized.
STRUCTURAL_TITLES = {
    "contents", "tableofcontents", "frontmatter", "backmatter", "index", "cover", "titlepage", "preface",
    "foreword", "introduction", "acknowledgments", "acknowledgements", "notes", "colophon", "dedication", "glossary",
    "bibliography", "appendix", "copyright", "aboutthebook", "abouttheauthor", "epigraph",
}
ID_LIKE_RE = re.compile(r"[a-z]+\d+[a-z0-9]*")  # a file-style id, e.g. part0002 or b19434 (after _fold)
TOC_NAV_RE = re.compile(r'<nav\b[^>]*epub:type="toc"')  # the EPUB 3 contents page; titled "Contents"
TITLE_MAX_CHARS = 60
IMAGE_ONLY_TITLE = "Image page"  # a page with a picture and no words, no label and no heading
# Single-paper support: a page with at least this many inline <svg> elements (the reference paper has 331 on one page;
# a cover or an occasional figure has 1 to 3) has its SVGs written to files and is split at its NCX entries.
INLINE_SVG_PAGE_MIN = 20
BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL)
# Inline SVG: a block is either self-closing (an empty placeholder) or has content up to </svg>; SVGs do not nest.
SVG_BLOCK_RE = re.compile(r"<svg\b[^>]*/>|<svg\b[^>]*>.*?</svg>", re.DOTALL)
# Glyph outlines that SVG <use> elements point at (self-closing <path> elements with an id).
GLYPH_DEF_RE = re.compile(r'<path\b[^>]*?\sid="([^"]+)"[^>]*?/>')
SVG_REF_RE = re.compile(r'xlink:href="#([^"]+)"')
ID_ATTR_RE = re.compile(r'\sid="([^"]+)"')
STYLE_ATTR_RE = re.compile(r'\sstyle="([^"]*)"')
TAG_NAME_RE = re.compile(r"<([A-Za-z][A-Za-z0-9]*)")
FIGURE_ID_RE = re.compile(r'id="(fig(\d+))"')
SVG_FILES: set[str] = set()  # "images/<name>" paths written by extract_svgs; already in place, so copy_image keeps them


def find_package(unpacked: Path) -> Path:
    """Locate the package document that META-INF/container.xml declares.

    An EPUB may carry several .opf files (for example a stale copy next to
    the real one); the container is the only authoritative pointer.

    Args:
        unpacked: Directory the EPUB was extracted into.

    Returns:
        Path to the package document (.opf).

    Raises:
        ValueError: When the container declares no rootfile.
    """
    container = ET.parse(unpacked / "META-INF" / "container.xml").getroot()
    rootfile = container.find(".//c:rootfile", CONTAINER_NS)
    full_path = rootfile.get("full-path") if rootfile is not None else None
    if not full_path:
        raise ValueError("META-INF/container.xml does not declare a rootfile")
    return unpacked / full_path


def find_ncx(opf_path: Path) -> Path | None:
    """Locate the NCX table of contents that the package document refers to.

    Uses the spine's toc attribute when present, else the NCX media type in the manifest.

    Args:
        opf_path: Path to the package document.

    Returns:
        Path to the NCX file, or None when the package has none.
    """
    root = ET.parse(opf_path).getroot()
    spine = root.find("opf:spine", OPF_NS)
    toc_id = spine.get("toc") if spine is not None else None
    for item in root.findall("opf:manifest/opf:item", OPF_NS):
        href = item.get("href")
        if href and (item.get("id") == toc_id or item.get("media-type") == NCX_MEDIA_TYPE):
            return opf_path.parent / href
    return None


def read_toc_labels(ncx_path: Path | None) -> dict[str, str]:
    """Map each EPUB page to its table-of-contents label.

    Args:
        ncx_path: Path to the NCX table of contents, or None when the book has none.

    Returns:
        Dict from page path (relative to the NCX directory, no fragment) to label.
    """
    if ncx_path is None:
        return {}
    ncx = ET.parse(ncx_path).getroot()
    labels: dict[str, str] = {}
    for point in ncx.iter("{http://www.daisy.org/z3986/2005/ncx/}navPoint"):
        label = point.findtext("{http://www.daisy.org/z3986/2005/ncx/}navLabel/{http://www.daisy.org/z3986/2005/ncx/}text")
        content = point.find("{http://www.daisy.org/z3986/2005/ncx/}content")
        src = content.get("src") if content is not None else None
        if label and src:
            page = posixpath.normpath(src.partition("#")[0])
            labels.setdefault(page, label.strip())
    return labels


def read_spine(opf_path: Path) -> list[tuple[str, str]]:
    """Return (manifest href, media type) for each spine item, in reading order.

    Args:
        opf_path: Path to the package document (content.opf).

    Returns:
        List of (href relative to the OPF directory, id) tuples.
    """
    root = ET.parse(opf_path).getroot()
    manifest = {
        item.get("id", ""): item.get("href", "")
        for item in root.findall("opf:manifest/opf:item", OPF_NS)
    }
    return [
        (manifest[idref], idref)
        for idref in (ref.get("idref", "") for ref in root.findall("opf:spine/opf:itemref", OPF_NS))
        if manifest.get(idref)
    ]


def book_title_keys(opf_path: Path, title: str) -> set[str]:
    """Folded forms of the book's own title, to recognise a publisher's default page <title>.

    Project Gutenberg titles every page "Title, by Author", and the metadata title may carry a subtitle after " / ".
    The keys are the title argument and the EPUB's dc:title, each whole and with the subtitle or author part removed.

    Args:
        opf_path: Path to the package document (content.opf).
        title: Book title passed on the command line.

    Returns:
        Set of folded (letters and digits, lowercase) title strings.
    """
    names = {title}
    names.update(element.text or "" for element in ET.parse(opf_path).getroot().iter(DC_TITLE_TAG))
    keys: set[str] = set()
    for name in names:
        keys.add(_fold(name))
        keys.add(_fold(re.split(r"\s+/\s+|,\s+by\s+", name, maxsplit=1)[0]))
    keys.discard("")
    return keys


def read_toc_points(ncx_path: Path | None, base: Path) -> list[tuple[str, str, str, int]]:
    """List the NCX table-of-contents entries in reading order, keeping fragments.

    Args:
        ncx_path: Path to the NCX table of contents, or None when the book has none.
        base: Directory of the package document; page paths are returned relative to it.

    Returns:
        One (page, fragment, label, depth) tuple per navPoint. The page is relative to
        base, the fragment is "" for a whole-page entry, and depth is 0 at the top level.
    """
    if ncx_path is None:
        return []
    navmap = ET.parse(ncx_path).getroot().find(NCX_NS + "navMap")
    points: list[tuple[str, str, str, int]] = []

    def walk(parent: ET.Element, depth: int) -> None:
        """Record each navPoint under parent, then recurse into its children."""
        for point in parent.findall(NCX_NS + "navPoint"):
            label = point.findtext(NCX_NS + "navLabel/" + NCX_NS + "text", default="").strip()
            content = point.find(NCX_NS + "content")
            src = content.get("src") if content is not None else None
            if src:
                page, _, fragment = src.partition("#")
                # NCX hrefs are relative to the NCX file; page hrefs are relative to the OPF directory.
                page = posixpath.normpath(posixpath.relpath(posixpath.join(ncx_path.parent.as_posix(), page), base.as_posix()))
                points.append((page, fragment, label, depth))
            walk(point, depth + 1)

    if navmap is not None:
        walk(navmap, 0)
    return points


def standalone_svg(block: str, glyphs: dict[str, str]) -> str:
    """Make one inline SVG self-contained by copying in the glyph outlines it uses.

    Glyphs are shared between the SVGs of one EPUB file: an SVG may <use> a glyph defined in another
    SVG. Each referenced id that the block does not define is copied into a <defs> element placed
    right after the opening tag, and the copied glyphs' own references are followed in turn.

    Args:
        block: The complete <svg> element as it appears in the XHTML.
        glyphs: Map from glyph id to its self-closing <path> element, for the whole page.

    Returns:
        The SVG element with a <defs> block added where it is needed, and the xlink namespace declared.
    """
    seen = set(ID_ATTR_RE.findall(block))
    pending = SVG_REF_RE.findall(block)
    needed: list[str] = []
    while pending:
        ident = pending.pop()
        if ident in seen:
            continue
        seen.add(ident)
        if ident not in glyphs:
            print(f"  unresolved svg reference #{ident}", file=sys.stderr)
            continue
        needed.append(glyphs[ident])
        pending.extend(SVG_REF_RE.findall(glyphs[ident]))
    if not needed and "xlink:" not in block:
        return block
    end_of_open_tag = block.index(">") + 1
    head = block[:end_of_open_tag]
    if "xmlns:xlink=" not in head:
        # Some SVGs use xlink:href but declare the namespace only in the XHTML root; as a standalone file that is an unbound prefix.
        head = head.replace("<svg", '<svg xmlns:xlink="http://www.w3.org/1999/xlink"', 1)
    defs = f"<defs>{''.join(needed)}</defs>" if needed else ""
    return head + defs + block[end_of_open_tag:]


def extract_svgs(text: str, stem: str, images: Path) -> str:
    """Write each inline SVG of a page to src/images/ and replace it with an <img> reference.

    Formulas become <stem>-eqNNN.svg and figures (class "imageobject" inside a figure with
    id figN) become <stem>-figN.svg. A self-closing SVG has no content (for example the empty
    left and label slots of a display equation) and is dropped. Each written file is checked
    to parse as XML; a failure is reported on stderr. The <img> keeps the SVG's vertical-align style.

    Args:
        text: XHTML of one EPUB page (the body is enough).
        stem: The page's file stem, used to name the images.
        images: Destination directory (src/images).

    Returns:
        The page text with every SVG replaced by an <img> tag.
    """
    glyphs = {match.group(1): match.group(0) for match in GLYPH_DEF_RE.finditer(text)}
    out: list[str] = []
    pos = 0
    equation_count = 0
    for match in SVG_BLOCK_RE.finditer(text):
        block = match.group(0)
        out.append(text[pos:match.start()])
        pos = match.end()
        if block.endswith("/>"):
            continue
        open_tag = block[: block.index(">") + 1]
        figure_ids = FIGURE_ID_RE.findall(text[max(0, match.start() - 4000):match.start()])
        if 'class="imageobject"' in open_tag and figure_ids:
            fig_id, number = figure_ids[-1]  # the nearest figure container before this SVG
            name = f"{stem}-{fig_id}.svg"
            alt = f"Figure {number}"
        else:
            equation_count += 1
            name = f"{stem}-eq{equation_count:03d}.svg"
            alt = ""
        content = standalone_svg(block, glyphs)
        try:
            ET.fromstring(content.encode("utf-8"))
        except ET.ParseError as error:
            print(f"  svg {name} does not parse: {error}", file=sys.stderr)
        (images / name).write_text(content, encoding="utf-8")
        SVG_FILES.add(f"images/{name}")
        style = STYLE_ATTR_RE.search(open_tag)
        style_attr = f' style="{style.group(1)}"' if style else ""
        if not style and 'class="contentdisp"' in open_tag:
            style_attr = ' style="vertical-align:middle"'  # display formulas are tall; centre them on the line
        out.append(f'<img src="images/{name}" alt="{alt}"{style_attr} />')
    out.append(text[pos:])
    return "".join(out)


class Part(NamedTuple):
    """One output page cut from an EPUB file: where it starts and ends in the text, and how it is titled."""

    fragment: str  # id of the NCX entry or heading the part starts at; "" for the text before the first one
    label: str
    depth: int
    start: int
    end: int


def split_page(text: str, key: str, points: list[tuple[str, str, str, int]]) -> list[Part]:
    """Cut one XHTML page at the NCX entries that point into it.

    Headings with the same tag as the NCX targets (for example an "Acknowledgments" the NCX omits)
    are cut points too, at depth 0. Text before the first cut is kept as its own part. A page with
    no cut point stays one part.

    Args:
        text: The page text after SVG extraction.
        key: The page's normalized href, matched against the NCX entries.
        points: NCX entries from read_toc_points.

    Returns:
        The parts in reading order.
    """
    cuts: list[tuple[int, str, str, int]] = []  # start, fragment, label, depth
    for page, fragment, label, depth in points:
        if page != key or not fragment:
            continue
        found = re.search(r'<[A-Za-z][^>]*?\sid="' + re.escape(fragment) + r'"', text)
        if found:
            cuts.append((found.start(), fragment, label, depth))
        else:
            print(f"  no element with id #{fragment} in {key}", file=sys.stderr)
    linked_starts = {start for start, _, _, _ in cuts}
    tags = {tag.group(1) for tag in (TAG_NAME_RE.match(text, start) for start in linked_starts) if tag}
    for tag_name in tags:
        for heading in re.finditer(rf"<{tag_name}\b([^>]*)>(.*?)</{tag_name}>", text, re.DOTALL):
            if heading.start() in linked_starts:
                continue
            id_match = ID_ATTR_RE.search(heading.group(1))
            fragment = id_match.group(1) if id_match else f"part-{heading.start()}"
            cuts.append((heading.start(), fragment, clean_title(heading.group(2)), 0))
    cuts.sort()
    parts: list[Part] = []
    first = cuts[0][0] if cuts else len(text)
    if not cuts or text[:first].strip():
        parts.append(Part("", "", 0, 0, first))
    for position, (start, fragment, label, depth) in enumerate(cuts):
        end = cuts[position + 1][0] if position + 1 < len(cuts) else len(text)
        parts.append(Part(fragment, label, depth, start, end))
    return parts


class Segment(NamedTuple):
    """One output page: a whole EPUB file, or one part of a split file."""

    href: str  # normalized href of the EPUB file
    fragment: str
    label: str  # NCX label of a split part; "" for a whole file (the file's own NCX label applies)
    depth: int | None  # SUMMARY depth of a split part; None for a whole file (the NCX depth of its page applies)
    name: str
    text: str
    number: int


def _keep_id_anchor(match: re.Match[str]) -> str:
    """Add an explicit empty anchor for an element's id, so intra-book fragments still resolve.

    Pandoc drops ids on block elements such as <p>; an <a id> placed inside the
    element survives conversion as raw HTML.

    Args:
        match: Match of an opening tag that carries an id attribute.

    Returns:
        The original opening tag followed by the anchor, or the tag unchanged for void elements.
    """
    tag, name, element_id = match.group(0), match.group(1).lower(), match.group(2)
    if name == "a":
        # pandoc keeps an <a> that still has an id as raw HTML, so the id moves to an anchor in front of the bare link.
        bare = re.sub(r'\sid="[^"]*"', "", tag)
        return f'<a id="{element_id}"></a>' + bare if element_id in REFERENCED_IDS else bare
    if name in VOID_ELEMENTS or tag.endswith("/>") or element_id not in REFERENCED_IDS:
        return tag
    return tag + f'<a id="{element_id}"></a>'


# --- Opt-in layouts (command-line flags; off for every other book) ---------------------------------------------
# --heading-divs: a heading is a <div class="heading_*"> block (no h tag). Promoted to h1 (first on the page) or h2,
# so the heading levels can nest the SUMMARY (see main: the nesting follows the heading depth when the NCX is flat).
# --shape-code: the listings are plain one-line paragraphs with no code markup. A line with Python statement shape
# (a block opener ending in ":", a return, import or print, an assignment or a call) is code; a run of them is one fence.
HEADING_DIVS = False  # set from the command line
SHAPE_CODE = False  # set from the command line
# --part-pattern=REGEX: a page whose text starts with the regex is a part cover (top level, titled by the match); the
# pages after it nest under it. The heading_* divs carry no level, so the part covers are named by the book's own text.
PART_PATTERN: re.Pattern[str] | None = None  # set from the command line
HEADING_DIV_RE = re.compile(r'<div(?:\s[^>]*)?\sclass="heading_[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
ID_SPAN_RE = re.compile(r'<(span|a)\b[^>]*\bid="([^"]+)"[^>]*>\s*</\1>')  # an empty anchor, kept in front of the heading
CODE_BLOCK_START_RE = re.compile(r"^(def|class) \w+.*:$|^(if|elif|while|for) .+:$|^(else|try|finally|except\b.*):$")
CODE_STATEMENT_RE = re.compile(
    r"^(return( .*)?|pass|break|continue|import \w[\w.]*( as \w+)?(, \w+)*|from \S+ import .+|print\s*\(.*\)"
    r"|@\w+.*|[A-Za-z_][\w.]*\(.*\)|[A-Za-z_][\w.]*\s*[-+*/]?=\s*[^=].*)$"
)
CODE_NUMBER_RE = re.compile(r"^\d+\\?\.\s*")  # a listing line number such as "3. " at the start


def promote_headings(text: str) -> str:
    """Turn <div class="heading_*"> blocks into <h1> (the first on the page) or <h2>, so pandoc writes markdown headings.

    Args:
        text: Page XHTML, before pandoc.

    Returns:
        The XHTML with the heading blocks replaced by h1/h2 elements. An image-only block stays as it is.
    """
    count = 0

    def repl(match: re.Match[str]) -> str:
        """Replace one heading block, keeping its empty anchors in front of the heading."""
        nonlocal count
        inner = match.group(1)
        if not re.search(r"\w", re.sub(r"<[^>]+>", "", inner)):
            return match.group(0)  # an image-only block is a figure, not a heading
        anchors = "".join(f'<a id="{ident}"></a>' for _, ident in ID_SPAN_RE.findall(inner))
        inner = ID_SPAN_RE.sub("", inner).strip()
        level = 1 if count == 0 else 2
        count += 1
        return f"{anchors}<h{level}>{inner}</h{level}>"

    return HEADING_DIV_RE.sub(repl, text)


def _code_line(paragraph: str) -> str | None:
    """Return the unescaped code text of a one-line paragraph, or None when it is prose.

    Args:
        paragraph: One markdown paragraph (a single line after pandoc).

    Returns:
        The code text with markdown escapes removed, or None when the line does not have code shape.
    """
    if "\n" in paragraph.strip():
        return None
    text = CODE_NUMBER_RE.sub("", paragraph.replace("\xa0", " ").strip())
    text = re.sub(r"\\(.)", r"\1", text).strip()
    if CODE_BLOCK_START_RE.match(text) or CODE_STATEMENT_RE.match(text):
        return text
    return None


def _indent_code(lines: list[str]) -> list[str]:
    """Re-create Python indentation for flat listing lines, which the EPUB stores without it.

    A line ending in ":" indents the lines after it; elif, else, except and finally step back out. A def inside a
    class is a method; a top-level def, class, import or "if __name__" resets to column 0.

    Args:
        lines: Code lines with no indentation.

    Returns:
        The same lines with four-space indentation applied.
    """
    out: list[str] = []
    level = 0
    in_class = False
    previous_opens = False
    for line in lines:
        if re.match(r"^(elif|else|except|finally)\b", line):
            level = max(level - 1, 0)
        elif re.match(r"^(def|@)", line) and in_class:
            level = 1
        elif re.match(r"^(def|class|import|from|if __name__)", line) and not previous_opens:
            level = 0
            in_class = line.startswith("class ")
        elif line.startswith("class "):
            level = 0
            in_class = True
        out.append("    " * level + line)
        previous_opens = line.endswith(":")
        if previous_opens:
            level += 1
    return out


def fence_code_paragraphs(markdown: str) -> str:
    """Wrap each run of code-shaped one-line paragraphs in a fence of the book's code language.

    Args:
        markdown: Converted page markdown, paragraphs separated by blank lines.

    Returns:
        The markdown with each run of code lines in a fenced block.
    """
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        """Emit the pending run of code lines as one fenced block."""
        if run:
            out.append(f"```{CODE_LANGUAGE}\n" + "\n".join(_indent_code(run)) + "\n```")
            run.clear()

    for block in markdown.split("\n\n"):
        code = _code_line(block)
        if code is None:
            flush()
            out.append(block)
        else:
            run.append(code)
    flush()
    return "\n\n".join(out)


def _promote_code_looking(match: re.Match[str]) -> str:
    """Give a prose-classed paragraph the code class when its text is a code line.

    Args:
        match: Match of a paragraph with the plain "content" class.

    Returns:
        The paragraph, re-classed as "prog" when its text looks like code, else unchanged.
    """
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", match.group(2))).replace("\xa0", " ")
    if CODE_LOOKING_RE.match(text):
        return f'<p class="prog"{match.group(1)}>{match.group(2)}</p>'
    return match.group(0)


def _code_paragraph_block(match: re.Match[str]) -> str:
    """Turn a run of code paragraphs into one fenced block, one line per paragraph.

    Tags inside each paragraph are dropped and entities decoded, so the listing text is exact
    (indentation kept); the block is escaped again by _fenced so pandoc keeps it literal.

    Args:
        match: Match of consecutive code paragraphs.

    Returns:
        A single <pre><code> element holding the paragraph texts, one per line.
    """
    lines: list[str] = []
    for para in CODE_PARAGRAPH_RE.findall(match.group(0)):
        lines.extend(_code_paragraph_lines(para))
    return _fenced("\n".join(lines), CODE_LANGUAGE)


def _code_paragraph_lines(paragraph: str) -> list[str]:
    """Split one code paragraph into listing lines.

    A <br/> ends a line, and a raw newline right after it is the same break, so it is dropped
    (the next line keeps its indentation). Any other raw newline is a line wrapped in the EPUB
    source, which is not a line break in the listing, so it is joined to the line before.

    Args:
        paragraph: Inner HTML of one code paragraph.

    Returns:
        The decoded listing lines, trailing spaces removed.
    """
    lines: list[str] = []
    for piece in re.split(r"<br\s*/?>", paragraph):
        piece = re.sub(r"^\r?\n", "", piece)  # the newline that follows a <br/>
        piece = re.sub(r"\r?\n\s*", "", piece)  # a soft wrap inside the line
        lines.append(htmllib.unescape(re.sub(r"<[^>]+>", "", piece)).replace("\xa0", " ").rstrip())
    return lines


def _fenced(code: str, language: str) -> str:
    """Wrap code in a language-tagged <pre><code>, escaped so pandoc keeps it literal.

    Args:
        code: Plain code text, already decoded from HTML.
        language: Fence language, e.g. "python", "bash" or "text".

    Returns:
        A <pre><code> element holding the escaped code.
    """
    return f'<pre><code class="language-{language}">{htmllib.escape(code, quote=False)}</code></pre>'


def _code_block_html(match: re.Match[str]) -> str:
    """Turn any EPUB <pre> into fenced-code markup, unwrapping Jupyter cell prompts.

    Packt exports notebook cells as ``<pre>In [ ]:<br/>    code<br/>Out[ ]:<br/>    result</pre>``,
    sometimes with several cells in one <pre>; Leanpub exports ``In [3]: code`` with the
    continuation lines indented by the prompt width. Every "In [n]:" and "Out[n]:" prompt
    is dropped and starts a new block: input becomes a code fence, output a plain-text
    fence. Only notebook cells are dedented; an ordinary listing keeps its indentation.
    A "$ " shell transcript is tagged bash; unprompted C++-looking text in a Python book is tagged cpp.

    Args:
        match: Match of a complete <pre> element (any attributes), including Pygments listings
            whose content starts with an empty <code>.

    Returns:
        One or more <pre><code> elements, or an empty string for an empty block.
    """
    text = LINENO_RE.sub("", match.group(1))  # line numbers are display furniture, not code
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").replace("\u200b", "")
    # Each segment is (kind, prompt width, lines); text before the first prompt is plain code.
    segments: list[tuple[str, int, list[str]]] = [("plain", 0, [])]
    for line in text.split("\n"):
        prompt = JUPYTER_PROMPT_RE.match(line)
        if prompt:
            width = len(prompt.group(0)) if line[prompt.end():].strip() else 0
            segments.append(("in" if prompt.group(1) == "In" else "out", width, [line[prompt.end():]]))
        elif segments[-1][1] and line[: segments[-1][1]].strip() == "":
            # Continuation lines of "In [3]: code" are indented by the prompt width.
            segments[-1][2].append(line[segments[-1][1]:])
        else:
            segments[-1][2].append(line)
    rendered: list[str] = []
    for kind, width, lines in segments:
        body = [line.rstrip() for line in lines]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if not body:
            continue
        # Packt-style cells (bare prompt line, indented body) are dedented; an inline prompt already consumed its indent.
        code = textwrap.dedent("\n".join(body)) if kind != "plain" and not width else "\n".join(body)
        first = next((line for line in body if line.strip()), "")
        if kind == "out":
            language = "text"
        elif first.startswith("$ "):
            language = "bash"
        elif kind == "plain" and CODE_LANGUAGE == "python" and CPP_HINT_RE.search(code):
            language = "cpp"  # a bare listing in a Python book that shows a C++ signature
        else:
            language = CODE_LANGUAGE
        rendered.append(_fenced(code, language))
    return "\n".join(rendered)


def _pg_preformatted(match: re.Match[str]) -> str:
    """Turn a Project Gutenberg preformatted block into markup that pandoc keeps.

    Gutenberg marks footnotes and verse with the same class (pgmonospaced), and pandoc turns it into indented
    text that renders as a code block. A block whose first line starts with "*" is a footnote group: each
    blank-line-separated note becomes a paragraph, its wrapped lines joined with spaces. Any other block is verse
    (or a listing): its lines are kept as a "text" fence, with the non-breaking spaces Gutenberg uses for
    indentation turned into spaces.

    Args:
        match: Match of a <div class="pgmonospaced"> element.

    Returns:
        Paragraph or fenced-code markup, or an empty string for a blank block.
    """
    text = re.sub(r"<br\s*/?>", "\n", match.group(1))
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").replace("\u200b", "")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    if lines[0].lstrip().startswith("*"):
        notes: list[list[str]] = [[]]
        for line in lines:
            if line.strip():
                notes[-1].append(line.strip())
            elif notes[-1]:
                notes.append([])
        return "\n".join(f"<p>{htmllib.escape(' '.join(note), quote=False)}</p>" for note in notes if note)
    return _fenced("\n".join(lines), "text")


# Pragprog testimonial attribution: a one-row table "arrow | name"; as a table it renders with an empty header row.
PRAISE_TABLE_RE = re.compile(r'<table class="praise"[^>]*>(?:<col[^>]*>(?:</col>)?)*\s*<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>\s*</table>', re.DOTALL)


# Pragprog footnotes: a table of "[n] | text" rows; as a table it renders with an empty header row, so each row becomes a paragraph.
FOOTNOTE_TABLE_RE = re.compile(r'<table[^>]*>\s*((?:<tr[^>]*>\s*<td class="footnote-number">.*?</tr>\s*)+)</table>', re.DOTALL)
FOOTNOTE_ROW_RE = re.compile(r'<tr[^>]*>\s*<td class="footnote-number">(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>', re.DOTALL)


def _footnote_table(match: re.Match[str]) -> str:
    """Turn a footnote table into one paragraph per footnote (number, then text)."""
    rows = FOOTNOTE_ROW_RE.findall(match.group(1))
    return "".join(f"<p>{num.strip()} {re.sub(r'</?p[^>]*>', '', body).strip()}</p>" for num, body in rows)


def _sniff_language(code: str) -> str | None:
    """Recognise a listing without a file name by its syntax (a Java ``public`` member, a Lisp form).

    Args:
        code: Plain text of the listing.

    Returns:
        "java", "clojure", or None when the text is not clear-cut (the caller then uses context).
    """
    stripped = code.strip()
    if re.search(r"\b(?:public|protected)\s", stripped):
        return "java"  # Scala and Clojure listings have no public/protected members
    if re.match(r"\(\s*[a-z][\w.*+!?<>=/-]*[\s)]", stripped) and "=>" not in stripped.split("\n")[0]:
        return "clojure"  # starts with a Lisp form such as (try ...) or (def x ...); a Scala lambda has "=>"
    return None


def _listing_language(body: str, file_name: str | None, text_before: str, inherited: str | None) -> str:
    """Choose the fence language for one listing table.

    Order: the source file's extension, then a REPL prompt in the listing
    (``scala>`` or ``=>``), then the language word in the paragraph just before
    the listing, then the language of the last listing on the page, then the book's default.

    Args:
        body: Inner HTML of the listing table.
        file_name: Source file name from the lozenge row, or None for continuation tables.
        text_before: Raw HTML of the page before the table.
        inherited: Language of the previous listing on the page, if any.

    Returns:
        A fence language name.
    """
    if file_name:
        extension = file_name.rsplit(".", 1)[-1].lower()
        if extension in LANGUAGE_BY_EXTENSION:
            return LANGUAGE_BY_EXTENSION[extension]
    code_text = htmllib.unescape(re.sub(r"<[^>]+>", "", body)).replace("\u200b", "")
    prompt = REPL_PROMPT_RE.search(code_text)
    if prompt:
        return "scala" if prompt.group(0).strip().startswith("scala") else "clojure"
    sniffed = _sniff_language(code_text)
    if sniffed:
        return sniffed
    previous = re.search(r"<p\b[^>]*>((?:(?!</p>).)*)</p>\s*$", text_before, re.DOTALL)
    if previous:
        words = PRE_LISTING_RE.findall(htmllib.unescape(re.sub(r"<[^>]+>", "", previous.group(1))))
        if words:
            return LANGUAGE_BY_WORD[words[-1].lower()]
    return inherited or CODE_LANGUAGE


def _processed_code_tables(text: str) -> str:
    """Turn every Packt/Pragprog listing table into a fenced code block.

    Each code row holds one line of source in its ``codeline`` cell; the
    ``codeprefix`` cell is an empty spacer and is dropped. Zero-width spaces
    are removed, non-breaking spaces become plain spaces, and the indentation
    of each line is kept. The lozenge row's source file name is kept as a
    line of inline code above the fence.

    Args:
        text: XHTML page content, before pandoc.

    Returns:
        The page with each listing table replaced by an optional file-name paragraph
        and a ``<pre><code class="language-...">`` block.
    """
    out: list[str] = []
    pos = 0
    inherited: str | None = None
    for match in PROCESSED_CODE_RE.finditer(text):
        body = match.group(1)
        lines = []
        for cell in CODELINE_CELL_RE.findall(body):
            if 'class="codeprefix"' in cell:  # the spacer cell also carries class="codeline"; it is not a source line
                continue
            line = htmllib.unescape(re.sub(r"<[^>]+>", "", cell)).replace("\u200b", "").replace("\xa0", " ")
            lines.append(line.rstrip())
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        file_match = LISTING_FILE_RE.search(body)
        file_name = htmllib.unescape(re.sub(r"<[^>]+>", "", file_match.group(1))).strip() if file_match else None
        language = _listing_language(body, file_name, text[:match.start()], inherited)
        inherited = language
        out.append(text[pos:match.start()])
        if file_name:
            out.append(f"<p><code>{htmllib.escape(file_name, quote=False)}</code></p>")
        out.append(_fenced("\n".join(lines), language))
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def _arr_recipe_heading(match: re.Match[str]) -> str:
    """Turn a pattern-number banner table into a level-1 heading.

    Pragprog pattern pages open with a one-row table ("Pattern 5" | "Replacing Iterator").
    As a heading the banner becomes the page title in SUMMARY.md.

    Args:
        match: Match of the banner table; group 1 is an optional id anchor, 2 the number cell, 3 the name cell.

    Returns:
        An h1 element "Pattern N: Name", with the id anchor kept inside it.
    """
    anchor = match.group(1) or ""
    number = htmllib.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
    name = htmllib.unescape(re.sub(r"<[^>]+>", "", match.group(3))).strip()
    return f"<h1>{anchor}{htmllib.escape(number, quote=False)}: {htmllib.escape(name, quote=False)}</h1>"


def _toc_table_paragraph(match: re.Match[str]) -> str:
    """Turn one single-row table of contents entry into a paragraph, keeping every cell.

    A row holds a chapter number cell (usually the link) and a name cell, so the
    cells are joined with a space rather than keeping only the first link.

    Args:
        match: Match of a table-of-contents2 table.

    Returns:
        A paragraph with the row's cells in order (links kept).
    """
    inner = re.sub(r"<col\b[^>]*>(</col>)?|</?tbody>|</?tr\b[^>]*>", "", match.group(1))
    cells = [re.sub(r"</?td\b[^>]*>", "", cell).strip() for cell in re.split(r"<td\b[^>]*>", inner)]
    cells = [cell for cell in cells if cell]
    return f"<p>{' '.join(cells)}</p>" if cells else ""


def mark_admonitions(text: str) -> str:
    """Turn Packt tip and info boxes (div.packt_tip / div.packt_infobox) into marker paragraphs.

    The box's opening and closing div become paragraphs containing a marker
    word (ADMONISHOPENTIP, ADMONISHOPENINFO, ADMONISHCLOSE). After pandoc,
    main() replaces those paragraphs with mdbook-admonish fences. Nested divs
    are matched by depth, so inner notebook wrappers stay intact.

    Args:
        text: XHTML page content, after code blocks are converted.

    Returns:
        The XHTML with box divs replaced by marker paragraphs.
    """
    out: list[str] = []
    pos = 0
    stack: list[str | None] = []
    for match in BOX_TAG_RE.finditer(text):
        closing, attrs = match.group(1), match.group(2)
        if closing:
            if not stack:
                continue
            kind = stack.pop()
            if kind:
                out.append(text[pos:match.start()])
                out.append("<p>ADMONISHCLOSE</p></div>")
                pos = match.end()
            continue
        classes = re.search(r'class="([^"]*)"', attrs)
        kind = None
        if classes:
            for box_class, label in BOX_CLASSES.items():
                if box_class in classes.group(1).split():
                    kind = label
                    break
        stack.append(kind)
        if kind:
            out.append(text[pos:match.start()])
            out.append(f"<div><p>ADMONISHOPEN{kind.upper()}</p>")
            pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def _callout_box(match: re.Match[str]) -> str:
    """Turn a Packt callout (heading paragraph plus body paragraphs) into a tip box with a title.

    The heading text becomes the admonish title; the body paragraphs stay inside the box.
    Runs after mark_admonitions, so the markers are written here directly.

    Args:
        match: Match of a ``callout-heading`` paragraph and the ``callout`` paragraphs after it.

    Returns:
        Marker paragraphs (ADMONISHOPENTIP with the title, ADMONISHCLOSE) around the body.
    """
    title = htmllib.unescape(re.sub(r"<[^>]+>", "", match.group(1))).replace("\xa0", " ")
    title = " ".join(title.split()).replace('"', "'")  # the title goes into an admonish title="..." attribute
    return f"<div><p>ADMONISHOPENTIP {title}</p>{match.group(2)}<p>ADMONISHCLOSE</p></div>"


def _admonish_fence(match: re.Match[str]) -> str:
    """Turn an admonish marker line into the mdbook-admonish fence line.

    Args:
        match: Match of ADMONISHOPENTIP/INFO (optional title in group 2) or ADMONISHCLOSE.

    Returns:
        The fence line that opens or closes the admonish block.
    """
    if match.group(1) is None:
        return "```"
    kind = "tip" if match.group(1) == "TIP" else "info"
    title = (match.group(2) or "").strip()
    return f'```admonish {kind} title="{title}"' if title else f"```admonish {kind}"


def clean_title(text: str) -> str:
    """Turn a heading or TOC label into plain text for SUMMARY.md and page titles.

    Args:
        text: Heading text, possibly with tags, HTML entities or markdown escapes.

    Returns:
        Plain, single-spaced title text (for example "S&P 500", not "S\\&amp;P 500").
    """
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # an image-only heading has no title text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # a link inside a heading would nest inside the SUMMARY link
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).replace("\u200b", "")
    text = re.sub(r"\*+([^*\\]+)\*+", r"\1", text)  # emphasis markers around heading text (escaped "\\*" is kept)
    text = re.sub(r"\\([\\`*_\[\]&#<>$])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    """Lowercase text with every non-letter and non-digit removed, for comparing labels with file names."""
    return re.sub(r"[\W_]+", "", text).lower()


def is_id_label(label: str) -> bool:
    """True when a label is a file-style id (part0002, bm01, b19434), not a name. A label with a space is never an id."""
    return " " not in label.strip() and bool(ID_LIKE_RE.fullmatch(_fold(label)))


def is_file_label(label: str, href: str) -> bool:
    """True when a label names the file, not the page: the file stem itself (a lowercase "index" for index.htm,
    but not "Cover" for cover.xhtml), or a file-style id."""
    stem = Path(href).stem
    return label == stem or (label.islower() and _fold(label) == _fold(stem)) or is_id_label(label)


def upper_first(text: str) -> str:
    """Capitalize the first letter of a lowercase word title, keeping the rest as written (not a URL such as www.x.com)."""
    if not text[:1].islower() or "." in text.split(" ")[0]:
        return text
    return text[:1].upper() + text[1:]


def page_case(text: str, href: str) -> str:
    """Capitalize a heading that is a front- or back-matter name ("contents", "front matter") or the file stem ("index").

    Other lowercase headings (a code name such as "int" in a reference book) keep the case the source uses.

    Args:
        text: Heading text, already cleaned.
        href: EPUB page path of the heading.

    Returns:
        The heading, with its first letter capitalized when it is a structural name.
    """
    if _fold(text) in STRUCTURAL_TITLES or _fold(text) == _fold(Path(href).stem):
        return upper_first(text)
    return text


def first_text_line(markdown: str) -> str:
    """Return the first prose line of a page when it is short enough to serve as a title.

    Pictures, raw HTML, code fences, headings and tables are skipped. A leading file-style token
    printed on the page ("part0002 © Copyright ...") is dropped before the length test.

    Args:
        markdown: Converted page markdown.

    Returns:
        The cleaned line, or "" when there is no such line or it is a paragraph (longer than TITLE_MAX_CHARS).
    """
    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith(("![", "<", "```", "#", "|", "\\*")):  # "\*": a footnote marker, not a title
            continue
        text = re.sub(r"^[a-z]+\d+\s+", "", clean_title(stripped))
        return text if 0 < len(text) <= TITLE_MAX_CHARS else ""
    return ""


def strip_hard_breaks(markdown: str) -> str:
    """Remove pandoc hard-break backslashes at line ends, leaving fenced code untouched.

    Admonish fences hold prose and are processed; any other fence is code and is kept verbatim,
    since a trailing backslash in a listing (a C macro, a shell continuation) is real code.

    Args:
        markdown: Converted page markdown.

    Returns:
        The markdown with trailing hard-break backslashes removed outside code.
    """
    out: list[str] = []
    in_code = in_admonish = False
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code or in_admonish:
                if stripped == "```":
                    in_code = in_admonish = False
            elif stripped.startswith("```admonish"):
                in_admonish = True
            else:
                in_code = True
        elif not in_code and line.endswith("\\"):
            line = line[:-1]
        out.append(line)
    return "\n".join(out)


def prepare_html(text: str) -> str:
    """Make EPUB markup pandoc-friendly before conversion.

    Images are normalized to src/alt-only tags, so pandoc emits markdown
    image syntax (it keeps raw <img> when width/height attributes are present).
    Code listings (``<pre class="programlisting">``) get a ``language-c`` code
    class so pandoc emits fenced blocks. Index back-links (``<a class="index">``)
    are unwrapped to plain text, since their EPUB-relative hrefs are dead here.

    Args:
        text: Raw XHTML page content.

    Returns:
        The rewritten HTML.
    """
    text = text.replace("\u200b", "")  # zero-width spaces around inline code and names are invisible noise
    if HEADING_DIVS:
        text = promote_headings(text)  # before any other rule: the heading blocks become h1/h2 for pandoc
    text = _convert_mathjax(text)  # first: the formula's inner spans must not be touched by the rules below
    text = HEADING_LINK_RE.sub(_unwrap_heading_link, text)
    text = _drop_running_numbers(text)  # before ids are rewritten: a page anchor is still in the paragraph
    # Ids go first: the anchors they become must survive the <a> attribute strip below.
    text = ID_ELEMENT_RE.sub(_keep_id_anchor, text)
    text = EPUB_TYPE_ATTR_RE.sub("", text)
    text = re.sub(r'<a\s+href="([^"]*)"[^>]*>', r'<a href="\1">', text)  # pandoc keeps <a> with extra attributes as raw HTML
    text = SVG_IMAGE_RE.sub(r'<img src="\1" alt="" />', text)  # an SVG wrapper around one image becomes a plain image
    text = ITALIC_JOIN_RE.sub(r"\1", text)  # one italic run per line, not one <i> per fragment
    text = ENDNOTE_NUMBER_RE.sub(r"\1 ", text)
    # pandoc writes a figure that holds code as raw HTML (highlighter spans and all), so figures become plain divs.
    text = FIGURE_OPEN_RE.sub("<div>", text).replace("</figure>", "</div>")
    text = FIGCAPTION_RE.sub(r"<p>\1</p>", text)
    text = FOOTNOTE_TABLE_RE.sub(_footnote_table, text)
    text = PRAISE_TABLE_RE.sub(lambda m: f"<p>{m.group(1).strip()} {m.group(2).strip()}</p>", text)
    text = ARR_RECIPE_RE.sub(_arr_recipe_heading, text)
    text = TOC_TABLE_RE.sub(_toc_table_paragraph, text)
    text = CODE_BLOCK_RE.sub(_code_block_html, text)
    text = PG_PREFORMATTED_RE.sub(_pg_preformatted, text)  # after the <pre> rule: its fences keep the "text" language
    # After the <pre> rule, which would re-fence these blocks with the book's default language; before pandoc,
    # so no listing table reaches the output as raw HTML.
    text = _processed_code_tables(text)
    text = mark_admonitions(text)
    text = CALLOUT_RE.sub(_callout_box, text)
    text = INLINE_CODE_RE.sub(r"<code>\2</code>", text)
    text = PROSE_CODE_PARAGRAPH_RE.sub(_promote_code_looking, text)
    text = CODE_PARAGRAPH_RUN_RE.sub(_code_paragraph_block, text)
    text = HEADING_PAIR_RE.sub(_chapter_heading, text)
    text = HEADING_PARAGRAPH_RE.sub(_heading_paragraph, text)
    text = QUOTE_RUN_RE.sub(_quote_block, text)
    text = ITALIC_RE.sub(_italic_marker, text)
    text = INDEX_LINK_RE.sub(r"\1", text)
    text = apply_script_math(text)  # em/sub/sup formulas (no TeX in the source) become $...$ after pandoc
    text = EQUATION_IMG_RE.sub(_equation_placeholder, text)
    return IMG_TAG_RE.sub(_normalize_img, text)


def _unwrap_heading_link(match: re.Match[str]) -> str:
    """Drop the link around a heading's text, keeping the link's id as an empty anchor."""
    link_id = ID_ATTR_RE.search(match.group(2))
    anchor = f'<a id="{link_id.group(1)}"></a>' if link_id else ""
    return f"{match.group(1)}{anchor}{match.group(3)}{match.group(4)}"


def _heading_text(fragment: str) -> str:
    """Drop markup from a heading paragraph, keeping its text and empty id anchors (note back-links target them).

    A <br/> inside the heading is a line break in the title, so it becomes a space ("History of" + "Modern").
    """
    fragment = re.sub(r"<br\s*/?>", " ", fragment)
    text = re.sub(r'(<a id="[^"]*"></a>)|<[^>]+>', lambda m: m.group(1) or "", fragment)
    return re.sub(r"\s+", " ", text).strip()


def _chapter_heading(match: re.Match[str]) -> str:
    """Turn a chapter-number paragraph plus its title paragraph into one level-1 heading ("ONE: Dragon")."""
    return f"<h1>{_heading_text(match.group(1))}: {_heading_text(match.group(2))}</h1>"


def _heading_paragraph(match: re.Match[str]) -> str:
    """Turn a paragraph of a HEADING_CLASS_LEVELS class into a heading of that level."""
    level = HEADING_CLASS_LEVELS[match.group(1)]
    return f"<h{level}>{_heading_text(match.group(2))}</h{level}>"


def _quote_block(match: re.Match[str]) -> str:
    """Wrap a run of block-quote paragraphs (QUOTE_CLASSES) in one <blockquote>."""
    paragraphs = QUOTE_PARAGRAPH_RE.findall(match.group(0))
    return "<blockquote>" + "".join(f"<p>{body}</p>" for body in paragraphs) + "</blockquote>"


def _italic_marker(match: re.Match[str]) -> str:
    """Mark an <i> run that Markdown emphasis would render literally, so it becomes <em> after pandoc.

    Args:
        match: Match of an <i> element with plain-text content.

    Returns:
        The content wrapped in marker words, or the original element when plain emphasis is safe.
    """
    content = match.group(1)
    if content and content[0].isalnum() and content[-1].isalnum():
        return match.group(0)
    return f"{ITALIC_OPEN}{content}{ITALIC_CLOSE}"


def to_katex(latex: str) -> str | None:
    """Turn an equation image's alt text into KaTeX source, or None when it is not clean LaTeX.

    KaTeX has no eqnarray, so ``eqnarray`` becomes ``aligned`` (``&=&`` becomes ``&=``) and
    ``\\nonumber`` is dropped. Anything with unbalanced braces or another environment is left
    as an image.

    Args:
        latex: Decoded alt text.

    Returns:
        Trimmed KaTeX source, or None to keep the image.
    """
    latex = latex.strip()
    if not latex or "$" in latex:
        return None
    latex = latex.replace("eqnarray*", "aligned").replace("eqnarray", "aligned")
    latex = latex.replace("\\nonumber", "").replace("&=&", "&=")
    if set(re.findall(r"\\begin\{(\w+)\}", latex)) - {"aligned"}:
        return None
    if latex.count("{") != latex.count("}") or latex.count("\\left") != latex.count("\\right"):
        return None
    return latex


def _equation_placeholder(match: re.Match[str]) -> str:
    """Replace one equation image by a placeholder word that pandoc passes through untouched.

    Args:
        match: Match of an equation <img> tag.

    Returns:
        The placeholder, or the original tag when the alt text is not clean LaTeX.
    """
    alt = ALT_ATTR_RE.search(match.group(0))
    latex = to_katex(htmllib.unescape(alt.group(1))) if alt else None
    if latex is None:
        return match.group(0)
    EQUATIONS.append(latex)
    return f"EQUATIONPLACEHOLDER{match.group(1).upper()}{len(EQUATIONS) - 1}X"


class _MathUnsupported(Exception):
    """A MathJax formula holds something the TeX rebuild does not handle; the message is the fallback reason."""


class _MathNode:
    """One element of a MathJax span tree; text runs are plain strings in ``children``."""

    def __init__(self, tag: str, classes: tuple[str, ...]) -> None:
        self.tag = tag
        self.classes = classes
        self.children: list[_MathNode | str] = []


class _MathBuilder(HTMLParser):
    """Build the element tree of one MathJax span from its HTML (void elements such as img and br are leaves)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _MathNode("root", ())
        self.open: list[_MathNode] = [self.root]

    def _add(self, tag: str, attrs: list[tuple[str, str | None]]) -> _MathNode:
        node = _MathNode(tag, tuple((dict(attrs).get("class") or "").split()))
        self.open[-1].children.append(node)
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._add(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.open.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.open) - 1, 0, -1):
            if self.open[index].tag == tag:
                del self.open[index:]
                return

    def handle_data(self, data: str) -> None:
        self.open[-1].children.append(data)


# Unicode letters from MathJax's HTML output; the variant forms (ϕ, ϵ, ϑ) keep the glyph the book shows.
MATH_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "varepsilon", "ϵ": "epsilon", "ζ": "zeta",
    "η": "eta", "θ": "theta", "ϑ": "vartheta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu",
    "ξ": "xi", "π": "pi", "ϖ": "varpi", "ρ": "rho", "ϱ": "varrho", "σ": "sigma", "ς": "varsigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "ϕ": "varphi", "χ": "chi", "ψ": "psi", "ω": "omega", "Γ": "Gamma", "Δ": "Delta",
    "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma", "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi",
    "Ω": "Omega",
}
MATH_SYMBOLS = {
    "−": "-", "×": r"\times ", "·": r"\cdot ", "⋅": r"\cdot ", "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ",
    "±": r"\pm ", "∑": r"\sum ", "∏": r"\prod ", "∫": r"\int ", "∞": r"\infty ", "∈": r"\in ", "∉": r"\notin ",
    "∀": r"\forall ", "∃": r"\exists ", "→": r"\to ", "∂": r"\partial ", "∇": r"\nabla ", "′": "'",
    "∝": r"\propto ", "≈": r"\approx ", "∼": r"\sim ", "~": r"\sim ", "|": r"\vert ", "\\": r"\backslash ",
    "{": r"\{ ", "}": r"\} ", "%": r"\% ", "&": r"\& ", "#": r"\# ", "_": r"\_ ", "^": r"\^{} ", "\xa0": " ",
}
MATH_FUNCTIONS = {"log", "ln", "exp", "max", "min", "sin", "cos", "tan", "lim", "det", "arg"}  # upright operator names
MATH_TEXT_ESCAPES = {"%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "\\": r"\textbackslash "}
MATH_TOKEN_CLASSES = {"mi", "mn", "mo", "mtext"}
MATH_TRANSPARENT_CLASSES = {"MathJax", "math", "mrow", "mstyle", "texatom"}


def _math_symbols(text: str) -> str:
    """Map the characters of a number or operator token to TeX.

    Args:
        text: Token text, already free of markup.

    Returns:
        TeX source for the characters.

    Raises:
        _MathUnsupported: When the text holds a dollar sign, which would end the inline math early.
    """
    pieces: list[str] = []
    for char in text:
        if char == "$":
            raise _MathUnsupported("dollar sign in formula (would end the math span)")
        if char in MATH_GREEK:
            pieces.append(f"\\{MATH_GREEK[char]} ")
        else:
            pieces.append(MATH_SYMBOLS.get(char, char))
    return "".join(pieces)


def _math_run(text: str, convert: Callable[[str], str]) -> str:
    """Emit TeX for a run of characters, keeping its spaces as ``\\ `` (a space in the book is visible spacing).

    Args:
        text: The raw run, with non-breaking spaces possible.
        convert: Maps the collapsed words (single spaces, no edges) to TeX.

    Returns:
        TeX source; a run of only spaces is one ``\\ ``.
    """
    word = " ".join(text.replace("\xa0", " ").split())
    if not word:
        return "\\ " if (" " in text or "\xa0" in text) else ""
    before = "\\ " if text[:1] in (" ", "\xa0") else ""  # "A" then " " then "matrix" is "A\ \mathrm{matrix}"
    after = "\\ " if text[-1:] in (" ", "\xa0") else ""
    return before + convert(word) + after


def _math_word(word: str) -> str:
    """Map one identifier word to TeX: a Greek letter, an operator name, an upright word, or the letters as they are.

    Args:
        word: Token text with single spaces only and no edge spaces.

    Returns:
        TeX source for the word.
    """
    if word in MATH_GREEK:
        return f"\\{MATH_GREEK[word]} "
    if word in MATH_FUNCTIONS:
        return f"\\{word} "
    if len(word) == 1:
        return _math_symbols(word)
    if word.isascii() and word.isalpha():
        return f"\\mathrm{{{word}}}"  # an upright multi-letter name, such as "matrix"
    if " " in word:
        return _math_text(word)  # prose inside the formula, such as "A matrix"
    return _math_symbols(word)


def _math_text(text: str) -> str:
    """Wrap plain text in ``\\text{...}``, escaping the TeX specials that can appear in it.

    Raises:
        _MathUnsupported: When the text holds a dollar sign.
    """
    if "$" in text:
        raise _MathUnsupported("dollar sign in formula (would end the math span)")
    collapsed = " ".join(text.replace("\xa0", " ").split())
    return "\\text{" + "".join(MATH_TEXT_ESCAPES.get(char, char) for char in collapsed) + "}"


def _token_tex(node: _MathNode, convert: Callable[[str], str]) -> str:
    """Emit TeX for a token element (mi, mn, mo, mtext): its text through ``convert``, in order with its scripts.

    Text runs are joined before ``convert`` so a word split across em or span wrappers stays one unit. Scripts
    (sub, sup) and nested tokens are emitted where they sit, so ``mn(em(mi x, sub 1))`` gives ``x_{1}``.

    Args:
        node: The token element.
        convert: Maps one run of token text to TeX.

    Returns:
        TeX source for the token.

    Raises:
        _MathUnsupported: When the token holds an element other than em, a plain span, a script or a nested token.
    """
    pieces: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            pieces.append(convert("".join(run)))
            run.clear()

    def walk(current: _MathNode) -> None:
        for child in current.children:
            if isinstance(child, str):
                run.append(child)
            elif child.tag in ("sub", "sup") or set(child.classes) & MATH_TOKEN_CLASSES:
                flush()
                pieces.append(_math_tex(child))
            elif child.tag == "em" or (child.tag == "span" and not child.classes):
                walk(child)
            else:
                raise _MathUnsupported(f"element {' '.join(child.classes) or child.tag} inside a token")

    walk(node)
    flush()
    return "".join(pieces)


def _math_parts(node: _MathNode, *counts: int) -> list[_MathNode | str]:
    """Return the element children of a layout element, whose count must be one of ``counts``.

    Args:
        node: An msub, msup, msubsup or mfrac element.
        counts: The element-child counts that are allowed.

    Returns:
        The element children, in order.

    Raises:
        _MathUnsupported: When the number of children is not one of ``counts``.
    """
    parts = [child for child in node.children if not (isinstance(child, str) and not child.strip())]
    if len(parts) not in counts:
        raise _MathUnsupported(f"{' '.join(node.classes)} with {len(parts)} parts")
    return parts


def _math_children(node: _MathNode) -> str:
    """Concatenate the TeX of all children of an element."""
    return "".join(_math_tex(child) for child in node.children)


def _math_tex(node: _MathNode | str) -> str:
    """Emit TeX for one node of a MathJax span tree.

    Class names mirror MathML element names (mi, mn, mo, msubsup, mfrac, msqrt, texatom and so on).
    Transparent wrappers (MathJax, math, mrow, texatom, plain span, em) pass their children through.

    Args:
        node: An element, or a text run.

    Returns:
        TeX source.

    Raises:
        _MathUnsupported: For an element this rebuild does not know (its message is the fallback reason).
    """
    if isinstance(node, str):  # a bare text run (inside a script, a wrapper or between tokens) is ordinary characters
        return _math_run(node, _math_symbols)
    if node.tag == "img":
        raise _MathUnsupported("equation image inside the formula")
    if node.tag == "br":
        raise _MathUnsupported("line break inside the formula")
    if node.tag == "sub":
        return f"_{{{_math_children(node)}}}"
    if node.tag == "sup":
        return f"^{{{_math_children(node)}}}"
    classes = set(node.classes)
    if "MJX_Assistive_MathML" in classes:
        raise _MathUnsupported("assistive text only (no MathML tree)")
    if "mi" in classes:
        return _token_tex(node, lambda run: _math_run(run, _math_word))
    if "mtext" in classes:
        return _token_tex(node, lambda run: _math_run(run, _math_text))
    if classes & {"mn", "mo"}:
        return _token_tex(node, lambda run: _math_run(run, _math_symbols))
    if classes & MATH_TRANSPARENT_CLASSES or node.tag == "em" or (node.tag == "span" and not classes):
        return _math_children(node)
    if "msubsup" in classes:  # one part: MathJax put the script inside the base, so the base is the whole thing
        return "".join(_math_tex(part) for part in _math_parts(node, 1, 2))
    if "msub" in classes:
        base, script = _math_parts(node, 2)
        return f"{_math_tex(base)}_{{{_math_tex(script)}}}"
    if "msup" in classes:
        base, script = _math_parts(node, 2)
        return f"{_math_tex(base)}^{{{_math_tex(script)}}}"
    if "mfrac" in classes:
        numerator, denominator = _math_parts(node, 2)
        return f"\\frac{{{_math_tex(numerator)}}}{{{_math_tex(denominator)}}}"
    if "msqrt" in classes:
        return f"\\sqrt{{{_math_children(node)}}}"
    if "mspace" in classes:
        return "\\,"
    raise _MathUnsupported(f"unsupported element {' '.join(node.classes) or node.tag}")


def mathjax_to_tex(span_html: str) -> str:
    """Rebuild the TeX of one MathJax span from its span tree.

    Args:
        span_html: The HTML of one ``<span class="MathJax">`` element, nested spans included.

    Returns:
        KaTeX source, passed through to_katex for the same brace checks as equation images.

    Raises:
        _MathUnsupported: When the formula cannot be rebuilt; the message is the fallback reason.
    """
    if "<img" in span_html:  # an equation image (fm-editor-equation) stands for the whole formula; no TeX to rebuild
        raise _MathUnsupported("equation image inside the formula")
    if "<br" in span_html:
        raise _MathUnsupported("line break inside the formula")
    builder = _MathBuilder()
    builder.feed(span_html)
    builder.close()
    if not builder.root.children:
        raise _MathUnsupported("empty span")
    tex = _math_tex(builder.root.children[0]).strip()
    if tex.endswith("\\"):  # a trailing space became "\ " and strip() left the backslash alone
        tex = tex[:-1].rstrip()
    if not tex:
        raise _MathUnsupported("no visible symbols")
    latex = to_katex(tex)
    if latex is None:
        raise _MathUnsupported("rebuilt TeX is not clean (unbalanced braces)")
    return latex


def _mathjax_span_end(text: str, start: int) -> int | None:
    """Return the index just past the </span> that closes the span opening at ``start``, or None if unclosed."""
    depth = 0
    for tag in MATHJAX_SPAN_TAG_RE.finditer(text, start):
        depth += -1 if tag.group(0) == "</span>" else 1
        if depth == 0:
            return tag.end()
    return None


def _convert_mathjax(text: str) -> str:
    """Replace MathJax span formulas by equation placeholders, or leave them as their original text.

    Each formula that mathjax_to_tex rebuilds becomes a placeholder (inline, or block inside a <p> when it
    sits in a div.MathJax_Display), so restore_equations emits $...$ or $$...$$. A formula that cannot be
    rebuilt stays as it is and is counted under its reason in MATHJAX_STATS.

    Args:
        text: Raw XHTML page content.

    Returns:
        The page with rebuilt formulas replaced by placeholders.
    """
    replacements: list[tuple[int, int, str]] = []
    previous: tuple[int, int] | None = None  # (end offset, EQUATIONS index) of the last inline formula placed
    for match in MATHJAX_START_RE.finditer(text):
        span_start = match.end() - len('<span class="MathJax">')
        MATHJAX_STATS["found"] += 1
        span_end = _mathjax_span_end(text, span_start)
        if span_end is None:
            MATHJAX_STATS["fallback: unclosed span"] += 1
            previous = None
            continue
        display_end = None
        if match.group(1):
            close = MATHJAX_CLOSE_DIV_RE.match(text, span_end)
            display_end = close.end() if close else None
        try:
            latex = mathjax_to_tex(text[span_start:span_end])
        except _MathUnsupported as error:
            MATHJAX_STATS[f"fallback: {error}"] += 1
            previous = None
            continue
        MATHJAX_STATS["converted"] += 1
        if display_end is not None:
            index = len(EQUATIONS)
            EQUATIONS.append(latex)
            replacements.append((match.start(), display_end, f"<p>EQUATIONPLACEHOLDERBLOCK{index}X</p>"))
            previous = None
        elif previous is not None and not re.sub(r"</?em>", "", text[previous[0] : span_start]):
            # The author split one formula into touching spans. Two placeholders in a row would put "$$" in the
            # markdown, so the pieces become one formula.
            index = previous[1]
            EQUATIONS[index] += latex
            MATHJAX_STATS["merged into previous"] += 1
            replacements[-1] = (replacements[-1][0], span_end, f"EQUATIONPLACEHOLDERINLINE{index}X")
            previous = (span_end, index)
        else:
            index = len(EQUATIONS)
            EQUATIONS.append(latex)
            replacements.append((span_start, span_end, f"EQUATIONPLACEHOLDERINLINE{index}X"))
            previous = (span_end, index)
    if not replacements:
        return text
    pieces: list[str] = []
    position = 0
    for start, end, replacement in replacements:
        pieces.append(text[position:start])
        pieces.append(replacement)
        position = end
    pieces.append(text[position:])
    return EM_AROUND_EQUATION_RE.sub(r"\1", "".join(pieces))


def _script_latex(fragment: str) -> str:
    """Convert a formula written with em, sub and sup tags to LaTeX (without delimiters).

    Italic runs are variables and stay italic. A run of two or more letters is a function or unit name and
    becomes upright (\\mathrm), as in m/s<sup>2</sup>.

    Args:
        fragment: HTML of one formula.

    Returns:
        The LaTeX source.
    """
    pieces: list[str] = []
    for match in SCRIPT_PIECE_RE.finditer(fragment):
        italic, sub, sup, plain = match.group(1), match.group(2), match.group(3), match.group(4)
        if italic is not None:
            pieces.append(_script_symbols(htmllib.unescape(re.sub(r"<[^>]+>", "", italic))))
        elif sub is not None:
            pieces.append("_{" + _script_latex(sub) + "}")
        elif sup is not None:
            pieces.append("^{" + _script_latex(sup) + "}")
        elif plain is not None:
            text = _script_symbols(htmllib.unescape(plain))
            pieces.append(re.sub(r"[A-Za-z]{2,}", lambda word: r"\mathrm{" + word.group(0) + "}", text))
    return "".join(pieces)


def _script_symbols(text: str) -> str:
    """Map EPUB typography characters in a formula to LaTeX-safe ones.

    Args:
        text: Unescaped formula text.

    Returns:
        The text with dashes, operators and LaTeX-special characters replaced.
    """
    for old, new in SCRIPT_SYMBOLS.items():
        text = text.replace(old, new)
    return text


def apply_script_math(text: str) -> str:
    """Replace formulas written with em, sub and sup tags by equation placeholders, outside <code> spans.

    Text inside <code> is literal (a subscript in a code span stays as it is), so the code spans are passed through.

    Args:
        text: Raw XHTML page content.

    Returns:
        The HTML with the formulas replaced by placeholders.
    """
    pieces = re.split(r"(<code\b[^>]*>.*?</code>)", text, flags=re.DOTALL)  # odd pieces are code spans
    return "".join(piece if index % 2 else _script_math_text(piece) for index, piece in enumerate(pieces))


def _script_math_text(text: str) -> str:
    """Replace the formulas in one piece of XHTML that holds no code span (see apply_script_math).

    A ``<p class="equation">`` paragraph becomes a display formula unless it holds a picture. An inline run such as
    ``<em>S</em><sub><em>I</em></sub>`` becomes an inline formula. restore_equations swaps the placeholders for $...$.

    Args:
        text: XHTML without code spans.

    Returns:
        The HTML with the formulas replaced by placeholders.
    """

    def display(match: re.Match[str]) -> str:
        """Turn an equation paragraph into a display placeholder; a paragraph with a picture stays as it is."""
        if "<img" in match.group(1):
            return match.group(0)
        EQUATIONS.append(_script_latex(match.group(1)))
        return f"<p>EQUATIONPLACEHOLDERBLOCK{len(EQUATIONS) - 1}X</p>"

    def inline(match: re.Match[str]) -> str:
        """Turn one italic or single-letter base with its sub and sup runs into an inline placeholder."""
        EQUATIONS.append(_script_latex(match.group(0)))
        return f"EQUATIONPLACEHOLDERINLINE{len(EQUATIONS) - 1}X"

    text = SCRIPT_EQUATION_P_RE.sub(display, text)
    # <em>T<sub>env</sub></em> is an italic variable with a subscript: move the italics onto the base first.
    text = SCRIPT_EM_RE.sub(lambda m: f"<em>{m.group(1)}</em><{m.group(2)}>{m.group(3)}</{m.group(2)}>", text)
    return SCRIPT_RUN_RE.sub(inline, text)


def restore_equations(markdown: str) -> str:
    """Swap equation placeholders for ``$...$`` (inline) and ``$$...$$`` (display) math.

    Args:
        markdown: Pandoc output holding placeholders.

    Returns:
        The markdown with KaTeX math.
    """

    def repl(match: re.Match[str]) -> str:
        latex = EQUATIONS[int(match.group(2))]
        if match.group(1) == "INLINE":
            return f"${' '.join(latex.split())}$"
        return f"\n$$\n{latex}\n$$\n"

    return EQUATION_PLACEHOLDER_RE.sub(repl, markdown)


def _normalize_img(match: re.Match[str]) -> str:
    """Rebuild one <img> tag with only its src and alt attributes (and style, for an extracted SVG), in that order.

    Args:
        match: Match of a complete <img ...> tag.

    Returns:
        The normalized tag, or the original when it has no src.
    """
    tag = match.group(0)
    src = SRC_ATTR_RE.search(tag)
    if not src:
        return tag
    alt = ALT_ATTR_RE.search(tag)
    alt_text = alt.group(1) if alt else ""
    style = STYLE_ATTR_RE.search(tag) if src.group(1) in SVG_FILES else None  # keeps vertical-align of extracted formulas
    style_attr = f' style="{style.group(1)}"' if style else ""
    if NUMERIC_ALT_RE.fullmatch(alt_text):
        alt_text = ""  # some exporters put an asset id in alt, which is not a description
    if "\\" in alt_text or "&#10;" in alt_text or "\n" in alt_text or len(alt_text) > 120:
        # Leanpub-style exporters put the equation's LaTeX source in alt; a multi-line value breaks the
        # markdown image link and the file is then never copied.
        alt_text = "equation"
    return f'<img src="{src.group(1)}" alt="{alt_text}"{style_attr} />'


def map_hrefs(
    html: str,
    href: str,
    current: str,
    pages: dict[str, str],
    files: set[str],
    segment_names: dict[tuple[str, str], str],
    id_pages: dict[tuple[str, str], str],
) -> str:
    """Point hrefs to other spine pages (and parts of split pages) at their new .md names, keeping fragments.

    Args:
        html: Raw XHTML of the page being converted.
        href: That page's href inside the EPUB (used to resolve relative links).
        current: Output name of the page or part being converted.
        pages: Map of EPUB href to output .md name for every spine page (the first part of a split page).
        files: Every file path in the EPUB (relative to the OPF directory).
        segment_names: Map of (EPUB href, NCX fragment) to the output name of that part of a split page.
        id_pages: Map of (EPUB href, element id) to the output name of the part of a split page that holds the id.

    Returns:
        The HTML with intra-book hrefs rewritten. A local link whose target is
        not in the EPUB (for example _ColorImages.pdf) is unwrapped to its text.
    """

    def unwrap_dead(match: re.Match[str]) -> str:
        """Keep the link text, not the link, when a local target does not exist in the EPUB."""
        target = match.group(1)
        if target.startswith("kindle:"):
            return match.group(2)  # Kindle-only embed links (cover pages) have no target in the book
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(href), target.partition("#")[0]))
        if resolved in pages or resolved in files:
            return match.group(0)
        return match.group(2)

    html = re.sub(r'<a href="([^"]+)"[^>]*>(.*?)</a>', unwrap_dead, html, flags=re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        target, _, fragment = match.group(1).partition("#")
        # page_N anchors are EPUB print-page markers, not kept in the book: link to the page.
        if fragment.startswith("page_"):
            fragment = ""
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(href), target)) if target else posixpath.normpath(href)
        if fragment and (resolved, fragment) in id_pages:
            name = id_pages[(resolved, fragment)]  # the id lives in a part of a split page
            return f'href="#{fragment}"' if name == current else f'href="{name}#{fragment}"'
        if not target or resolved not in pages:
            return match.group(0)
        if (resolved, fragment) in segment_names:
            return f'href="{segment_names[(resolved, fragment)]}"'  # an NCX entry of a split page is a whole part
        suffix = f"#{fragment}" if fragment else ""
        return f'href="{pages[resolved]}{suffix}"'

    return HREF_RE.sub(repl, html)


def pandoc_html(html: str) -> str:
    """Convert one XHTML page to GitHub-flavored markdown.

    Args:
        html: Page markup, already passed through prepare_html.

    Returns:
        Markdown text with span/div wrappers dropped.
    """
    result = subprocess.run(
        ["pandoc", "-f", "html-native_divs-native_spans", "-t", "gfm", "--wrap=none"],
        input=html,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def read_toc_depths(ncx_path: Path | None) -> dict[str, int]:
    """Map each EPUB page to its nesting depth in the NCX table of contents.

    Args:
        ncx_path: Path to the NCX table of contents, or None when the book has none.

    Returns:
        Dict from page path (relative to the NCX directory, no fragment) to depth, top level = 0.
    """
    if ncx_path is None:
        return {}
    ns = "{http://www.daisy.org/z3986/2005/ncx/}"
    navmap = ET.parse(ncx_path).getroot().find(ns + "navMap")
    depths: dict[str, int] = {}

    def walk(parent: ET.Element, depth: int) -> None:
        """Record the depth of each navPoint under parent, then recurse into its children."""
        for point in parent.findall(ns + "navPoint"):
            content = point.find(ns + "content")
            src = content.get("src") if content is not None else None
            if src:
                depths.setdefault(posixpath.normpath(src.partition("#")[0]), depth)
            walk(point, depth + 1)

    if navmap is not None:
        walk(navmap, 0)
    return depths


class _NavDepthParser(HTMLParser):
    """Collect the nesting depth of each link in an EPUB 3 ``<nav epub:type="toc">`` list."""

    def __init__(self) -> None:
        super().__init__()
        self.in_nav = False
        self.items: list[bool] = []  # one flag per open <li>: has it shown a link yet?
        self.depths: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "nav" and "toc" in (values.get("epub:type") or "").split():
            self.in_nav = True
        elif self.in_nav and tag == "li":
            self.items.append(False)
        elif self.in_nav and tag == "a" and (link := values.get("href")) and self.items and not self.items[-1]:
            # A group item without a link (a bare <span>) adds no level to its children.
            self.depths.setdefault(link.partition("#")[0], sum(self.items[:-1]))
            self.items[-1] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self.items:
            self.items.pop()
        elif tag == "nav":
            self.in_nav = False


def read_nav_depths(base: Path, spine: list[tuple[str, str]]) -> dict[str, int]:
    """Map each page to its depth in the HTML table of contents, for books whose NCX is flat.

    Leanpub NCX files list every page at one level while the toc page nests chapters under parts.

    Args:
        base: Directory of the package document.
        spine: (href, id) pairs in reading order.

    Returns:
        Dict from page path (relative to base) to depth, top level = 0; empty when no toc page nests.
    """
    for href, _ in spine:
        parser = _NavDepthParser()
        parser.feed((base / href).read_text(encoding="utf-8", errors="replace"))
        if parser.depths:
            return {posixpath.normpath(posixpath.join(posixpath.dirname(href), page)): depth for page, depth in parser.depths.items()}
    return {}


def slugify(text: str) -> str:
    """Make a filename-safe lowercase slug.

    Args:
        text: Source name, e.g. "ch02" or "B19434_02".

    Returns:
        Slug of lowercase letters, digits and dashes.
    """
    return SLUG_RE.sub("-", text.lower()).strip("-")


def first_heading_level(markdown: str) -> int | None:
    """Return the level of the first markdown heading outside code fences, or None when there is none."""
    in_fence = False
    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (heading := re.match(r"^(#{1,6}) ", line)):
            return len(heading.group(1))
    return None


def normalize_headings(markdown: str) -> str:
    """Make the page's top heading level 1, shifting all headings up if needed.

    Headings inside fenced code blocks are left alone, so C preprocessor lines
    such as ``#include`` are never treated as headings. An escaped line-initial
    ``\\#`` outside code is unescaped, since it is prose (e.g. an index entry).

    Args:
        markdown: Converted page markdown.

    Returns:
        The markdown with its heading levels normalized.
    """
    lines = markdown.split("\n")
    in_fence = False
    heading_lines = []
    for number, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^#{1,6} ", line):
            heading_lines.append(number)
        elif not in_fence and line.startswith("\\#") and re.match(r"\\#\S", line):
            # Pandoc escapes a line-initial "#" (e.g. an index entry "#include"); it is prose, not a heading.
            lines[number] = line[1:]
    if heading_lines and not lines[heading_lines[0]].startswith("# "):
        shift = len(lines[heading_lines[0]]) - len(lines[heading_lines[0]].lstrip("#")) - 1
        for number in heading_lines:
            # Remove `shift` hash marks, never more than the level allows, keeping the heading text intact.
            hashes = len(lines[number]) - len(lines[number].lstrip("#"))
            lines[number] = "#" * max(1, hashes - shift) + lines[number][hashes:]
    return "\n".join(lines)


def copy_image(ref: str, index: int, page: Path, href: str, copied: dict[str, Path], images: Path) -> str:
    """Copy one image referenced by a page into src/images/ and return its new path.

    Args:
        ref: Image reference as written in the page (relative or external).
        index: Spine index of the page, used to disambiguate colliding names.
        page: Path of the XHTML page that references the image.
        href: Page href inside the EPUB, for log messages.
        copied: Map of output names already written, used to detect collisions.
        images: Destination directory (src/images).

    Returns:
        The path to use in the markdown, or the original reference if it
        is external or missing.
    """
    if re.match(r"^[a-z]+:", ref):
        return ref
    if ref in SVG_FILES:
        return ref  # written by extract_svgs
    ref = urllib.parse.unquote(ref)  # EPUB src attributes are URL-encoded; file names are not
    source = (page.parent / ref).resolve()
    if not source.exists():
        print(f"  missing image {ref} in {href}", file=sys.stderr)
        return ref
    name = source.name
    if name in copied and copied[name].read_bytes() != source.read_bytes():
        name = f"{index:03d}-{name}"
    target = images / name
    if not target.exists():
        shutil.copy(source, target)
    copied[name] = target
    return f"images/{name}"


def drop_dead_fragments(src: Path) -> None:
    """Remove fragments from intra-book links whose target id no longer exists.

    Some anchors sit inside code listings, where pandoc drops them; the link
    then falls back to the page itself.

    Args:
        src: The book's src directory holding the converted pages.
    """
    ids_by_page = {
        page.name: set(re.findall(r'id="([^"]+)"', page.read_text(encoding="utf-8")))
        for page in src.glob("*.md")
    }
    link_re = re.compile(r'(\]\(|href=")([^)"\s#]+\.md)#([^)"\s]+)')

    def repl(match: re.Match[str]) -> str:
        """Keep the fragment only when the target page defines that id."""
        target, fragment = match.group(2), match.group(3)
        if fragment in ids_by_page.get(target, set()):
            return match.group(0)
        return f"{match.group(1)}{target}"

    for page in src.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        fixed = link_re.sub(repl, text)
        if fixed != text:
            page.write_text(fixed, encoding="utf-8")


def main(epub: Path, book: Path, title: str) -> None:
    """Build the mdBook source tree for one EPUB.

    Args:
        epub: Path to the .epub file.
        book: Book directory to create (src/ is written inside it).
        title: Book title for the SUMMARY header.
    """
    book.mkdir(parents=True, exist_ok=True)
    src = book / "src"
    images = src / "images"
    images.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        unpacked = Path(tmp)
        with zipfile.ZipFile(epub) as archive:
            archive.extractall(unpacked)
        # The EPUB may carry other packages (leftover books); use the one container.xml names.
        opf = find_package(unpacked)
        spine = read_spine(opf)
        base = opf.parent
        ncx = find_ncx(opf)
        toc_labels = read_toc_labels(ncx)
        toc_depths = read_toc_depths(ncx)
        # NCX hrefs are relative to the NCX file; page hrefs are relative to the OPF.
        ncx_dir = ncx.parent.as_posix() if ncx else ""
        own_titles = book_title_keys(opf, title)

        def from_opf(page: str) -> str:
            """Re-base an NCX-relative page path onto the OPF directory."""
            return posixpath.normpath(posixpath.relpath(posixpath.join(ncx_dir, page), base.as_posix()))

        toc_labels = {from_opf(page): label for page, label in toc_labels.items()} if ncx else {}
        toc_depths = {from_opf(page): depth for page, depth in toc_depths.items()} if ncx else {}
        nav_fallback = False
        nav_depths = read_nav_depths(base, spine)
        if nav_depths and max(nav_depths.values()) > 0 and max(toc_depths.values(), default=0) == 0:
            toc_depths, nav_fallback = nav_depths, True  # the NCX is flat but the toc page nests chapters under parts
        files = {path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_file()}

        # Cut the spine into output pages first, so links can be rewritten. A page is one segment, except an
        # SVG-heavy page (a paper packed into one file): its SVGs become image files and it splits at its NCX entries.
        points = read_toc_points(ncx, base)
        segments: list[Segment] = []
        pages: dict[str, str] = {}  # EPUB href -> output name of its first segment
        segment_names: dict[tuple[str, str], str] = {}
        for href, _ in spine:
            key = posixpath.normpath(href)
            text = (base / href).read_text(encoding="utf-8", errors="replace")
            if text.count("<svg") < INLINE_SVG_PAGE_MIN:
                parts = [Part("", "", 0, 0, len(text))]
                split = False
            else:
                body = BODY_RE.search(text)
                text = extract_svgs(body.group(1) if body else text, Path(href).stem, images)
                parts = split_page(text, key, points)
                split = True
            for part in parts:
                index = len(segments) + 1
                slug = slugify(part.label) if part.fragment else slugify(Path(href).stem)
                name = f"{index:03d}-{slug or 'page'}.md" if split else f"{index:03d}-{slug}.md"
                pages.setdefault(key, name)
                segment_names[(key, part.fragment)] = name
                segments.append(Segment(key, part.fragment, part.label, part.depth if split else None, name, text[part.start:part.end], index))
        # Links into a split page: each element id maps to the part that holds it.
        id_pages: dict[tuple[str, str], str] = {}
        for segment in segments:
            if segment.depth is not None:
                for ident in ID_ATTR_RE.findall(segment.text):
                    id_pages.setdefault((segment.href, ident), segment.name)

        numbers_seen: dict[str, set[str]] = {}
        for href, _ in spine:
            page_text = (base / href).read_text(encoding="utf-8", errors="replace")
            for target in HREF_RE.findall(page_text):
                if "#" in target:
                    REFERENCED_IDS.add(target.partition("#")[2])
            for number in BARE_NUMBER_P_RE.findall(_outside_tables(page_text)):
                numbers_seen.setdefault(number, set()).add(href)
        # A bare number paragraph repeated across pages is a running page footer, not content.
        RUNNING_NUMBERS.update(n for n, hrefs in numbers_seen.items() if len(hrefs) >= RUNNING_MIN_PAGES)
        summary_entries: list[tuple[str, str, str, int | None, int | None]] = []
        copied: dict[str, Path] = {}
        image_only_pages = 0  # numbers the "Image page N" titles
        in_part = False  # --part-pattern: true once a part cover has been seen
        for segment in segments:
            href, index, out_name = segment.href, segment.number, segment.name
            page = base / href
            html = map_hrefs(prepare_html(segment.text), href, out_name, pages, files, segment_names, id_pages)
            markdown = FENCE_OPEN_SPACE_RE.sub(r"\1```\2", pandoc_html(html))  # pandoc writes "``` scala"; the info string is "```scala"
            markdown = markdown.replace("\\&amp;", "&")  # pandoc escapes entities it has already decoded
            markdown = ADMONISH_MARK_RE.sub(_admonish_fence, markdown)
            markdown = KEPT_ANCHOR_RE.sub(lambda m: f'<a id="{m.group(1)}"></a>' if m.group(1) in REFERENCED_IDS else "", markdown)
            markdown = SPAN_RE.sub(r"\1", markdown)
            markdown = EMPTY_SPAN_RE.sub("", markdown)
            markdown = ENDNOTE_MARK_RE.sub(r"<sup>\1</sup>", markdown)
            markdown = markdown.replace(ITALIC_OPEN, "<em>").replace(ITALIC_CLOSE, "</em>")

            def fix_image(match: re.Match[str], index: int = index, page: Path = page, href: str = href) -> str:
                """Copy the image into src/images/ and point the link at it."""
                return f"![{match.group(1)}]({copy_image(match.group(2), index, page, href, copied, images)})"

            def fix_raw_src(match: re.Match[str], index: int = index, page: Path = page, href: str = href) -> str:
                """Rewrite a raw HTML src attribute the same way as a markdown image."""
                return f'src="{copy_image(match.group(1), index, page, href, copied, images)}"'

            markdown = IMG_RE.sub(fix_image, markdown)
            markdown = RAW_SRC_RE.sub(fix_raw_src, markdown)
            markdown = strip_hard_breaks(markdown)
            markdown = restore_equations(markdown)  # after the hard-break cleanup, which would eat "\\\\" line ends

            def fix_link(match: re.Match[str], href: str = href) -> str:
                """Rewrite links to other spine pages to their .md outputs."""
                target = posixpath.normpath(posixpath.join(posixpath.dirname(href), match.group(2)))
                if target in pages:
                    return f"{match.group(1)}{pages[target]}{match.group(3) or ''}{match.group(4)}"
                return match.group(0)

            markdown = LINK_RE.sub(fix_link, markdown)
            if SHAPE_CODE:
                markdown = fence_code_paragraphs(markdown)  # after the links, before the headings are normalized

            markdown = EMPTY_HEADING_RE.sub("", markdown)
            top_level = first_heading_level(markdown)
            markdown = normalize_headings(markdown)
            headings = [h for h in (clean_title(h) for h in TITLE_RE.findall(markdown)) if h]
            xhtml_match = TITLE_TAG_RE.search((base / href).read_text(encoding="utf-8", errors="replace"))
            # Title order: first heading, then the NCX label, then the XHTML <title>, then the first short prose line,
            # then a picture-only label, then the file name. A label that only names the file is skipped (see is_file_label).
            heading = headings[0] if headings and not is_id_label(headings[0]) else ""
            label = clean_title(segment.label or toc_labels.get(href) or "")
            if is_file_label(label, href):
                label = ""
            xhtml_title = clean_title(xhtml_match.group(1)) if xhtml_match else ""
            if xhtml_title and (
                _fold(xhtml_title) in own_titles or _fold(re.split(r",\s+by\s+", xhtml_title, maxsplit=1)[0]) in own_titles
            ):
                xhtml_title = ""  # the publisher's default <title> ("Title" or "Title, by Author") is the book's own title
            xhtml_name = _fold(xhtml_title) in GENERIC_XHTML_TITLES or is_file_label(xhtml_title, href)
            toc_title = "Contents" if TOC_NAV_RE.search(segment.text) else ""  # an EPUB contents page whose <title> is "nav"
            # Lowercase labels from headings and XHTML titles are capitalized ("index", "contents"); NCX labels keep their case.
            if heading:
                page_title = page_case(heading, href)
            elif label:
                page_title = label
            elif xhtml_title and not xhtml_name:
                page_title = upper_first(xhtml_title)
            elif toc_title:
                page_title = toc_title
            elif first_text_line(markdown):
                page_title = first_text_line(markdown)
            elif xhtml_title and not is_id_label(xhtml_title):
                page_title = upper_first(xhtml_title)  # "Cover" or "cover": the book's own name for a picture page
            elif (
                is_id_label(Path(href).stem)
                and "![" in markdown
                and not re.search(r"[A-Za-z]{3,}", re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>", " ", markdown))
            ):
                image_only_pages += 1  # a picture, no words, and an id-style file name (bm01): number it
                page_title = f"{IMAGE_ONLY_TITLE} {image_only_pages}"
            else:
                page_title = Path(href).stem.replace("_", " ").title()  # cover.xhtml -> "Cover", titlepage -> "Titlepage"
            if re.fullmatch(r"\d+", page_title) and len(headings) > 1:
                # Packt-style chapters: a bare number H1, then the chapter name in the next H1.
                page_title = f"{page_title} {headings[1]}"
            if PART_PATTERN is None:
                part_depth = segment.depth
            else:
                plain = " ".join(re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|^#+ ", " ", htmllib.unescape(markdown), flags=re.MULTILINE).split())
                part_match = PART_PATTERN.match(plain)
                if part_match:
                    page_title = part_match.group(0).title()  # "python for beginners" -> "Python For Beginners"
                    in_part = True
                part_depth = 0 if part_match or not in_part else 1  # a part cover is top level; the pages after it nest
            (src / out_name).write_text(markdown.strip() + "\n", encoding="utf-8")
            summary_entries.append((page_title, out_name, href, top_level, part_depth))
            print(f"{out_name}: {page_title}")

    drop_dead_fragments(src)

    # Nest pages by the EPUB's NCX hierarchy; a page missing from the NCX keeps the depth of the page before it.
    lines = ["# Summary", ""]
    depth = 0
    levels: list[tuple[int, int]] = []  # (heading level, depth) of the open sections, for sub-section pages
    for entry_title, name, href, level, part_depth in summary_entries:
        depth = toc_depths.get(href, depth) if part_depth is None else part_depth
        if nav_fallback and level and part_depth is None:
            # With a flat NCX a page whose heading is deeper than the page before it (an h3 section after an
            # h2 chapter) belongs inside that chapter, even though the toc page lists it beside the chapters.
            while levels and levels[-1][0] >= level:
                levels.pop()
            depth = max(depth, levels[-1][1] + 1 if levels else 0)
            levels.append((level, depth))
        lines.append("    " * depth + f"- [{entry_title}]({name})")
    (src / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if MATHJAX_STATS["found"]:
        reasons = "; ".join(
            f"{count} {key.removeprefix('fallback: ')}"
            for key, count in sorted(MATHJAX_STATS.items())
            if key.startswith("fallback: ")
        )
        print(
            f"MathJax spans: {MATHJAX_STATS['found']} found, {MATHJAX_STATS['converted']} converted to TeX "
            f"({MATHJAX_STATS['merged into previous']} of them merged into the formula before), "
            f"fallback {sum(v for k, v in MATHJAX_STATS.items() if k.startswith('fallback: '))} ({reasons})"
        )

    asset = Path.home() / ".claude/skills/mdbook-authoring/assets"
    toml = (asset / "book.toml").read_text(encoding="utf-8")
    toml = toml.replace('title = "TODO — course title"', f'title = "{title}"')
    (book / "book.toml").write_text(toml, encoding="utf-8")
    shutil.copy(asset / "scripts/katex_text_fix.py", book / "katex_text_fix.py")


if __name__ == "__main__":
    # Usage: epub2mdbook.py <epub> <book-dir> <title> [code-language] [--heading-divs] [--shape-code] [--part-pattern=REGEX]
    FLAGS = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    POSITIONAL = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    HEADING_DIVS = "--heading-divs" in FLAGS
    SHAPE_CODE = "--shape-code" in FLAGS
    PART_FLAGS = [arg.removeprefix("--part-pattern=") for arg in FLAGS if arg.startswith("--part-pattern=")]
    PART_PATTERN = re.compile(f"^(?:{PART_FLAGS[0]})", re.IGNORECASE) if PART_FLAGS else None
    CODE_LANGUAGE = POSITIONAL[3] if len(POSITIONAL) > 3 else "cpp"
    main(Path(POSITIONAL[0]), Path(POSITIONAL[1]), POSITIONAL[2])
