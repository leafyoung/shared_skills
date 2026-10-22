#!/usr/bin/env python3
"""Restore original comment placement in marimo conversions of Jupyter notebooks.

`marimo convert` misplaces cell comments (section banners land mid-statement,
comment blocks get folded onto one line). This script re-anchors every original
comment to the statement it preceded (or trailed), at any nesting depth,
rename-tolerantly, and asserts executable code is unchanged before writing.

Usage:
    python restore_comments.py --ipynb-dir DIR --py-dir DIR [--write] [--files "A,B"]

Pairs each `X.ipynb` in --ipynb-dir with `X.py` in --py-dir. Default is a dry
run; pass --write to modify the .py files. Backups land in /tmp/marimo_restore_backup/.
"""
import argparse
import ast
import copy
import difflib
import io
import json
import shutil
import sys
import tokenize
from collections import defaultdict
from pathlib import Path

IGNORED = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
           tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
FUZZY_RATIO = 0.7


def shallow_dump(node):
    n = copy.deepcopy(node)
    for field in ("body", "orelse", "finalbody", "handlers"):
        if getattr(n, field, None) is not None:
            setattr(n, field, [])
    return ast.dump(n)


def all_stmts(src):
    """Preorder list of every statement node."""
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                compound = bool(getattr(child, "body", None))
                out.append({"start": child.lineno, "end": child.end_lineno,
                            "indent": child.col_offset,
                            "norm": shallow_dump(child) if compound else ast.dump(child)})
                walk(child)

    try:
        tree = ast.parse(src)
    except SyntaxError:
        # Cell has IPython magic lines (e.g. "%matplotlib inline") mixed with
        # real code; the converter drops the magics, so strip lines starting
        # with %/! (comment out, to preserve line numbers) and retry.
        stripped = "\n".join(
            "#" + ln if ln.lstrip().startswith(("%", "!")) else ln
            for ln in src.split("\n")
        )
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            return out
    walk(tree)
    return out


def comments_of(src):
    lines = src.split("\n")
    out = []
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.COMMENT:
            out.append({"line": t.start[0], "col": t.start[1], "text": t.string,
                        "trailing": bool(lines[t.start[0] - 1][: t.start[1]].strip())})
    return out


def bind_comments(statements, comments):
    pre, trail = defaultdict(list), defaultdict(list)
    trailing_cs = [c for c in comments if c["trailing"]]
    standing = [c for c in comments if not c["trailing"]]
    for c in trailing_cs:
        ends = [i for i, s in enumerate(statements) if s["end"] == c["line"]]
        if ends:
            trail[max(ends)].append(c)
        else:
            standing.append(c)
    starts = [s["start"] for s in statements]
    for c in standing:
        idx = next((i for i, ln in enumerate(starts) if ln >= c["line"]),
                   len(statements))
        while idx + 1 < len(starts) and starts[idx + 1] == starts[idx]:
            idx += 1  # deepest node sharing the start
        pre[idx].append(c)
    return pre, trail


def is_noncontent_cell(body_nodes):
    if not body_nodes:
        return "empty"
    for n in body_nodes:
        if isinstance(n, ast.Import):
            if not all(a.name == "marimo" for a in n.names):
                return "content"
        elif isinstance(n, ast.Expr):
            ok = isinstance(n.value, ast.Constant) or (
                isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute)
                and isinstance(n.value.func.value, ast.Name)
                and n.value.func.value.id == "mo")
            if not ok:
                return "content"
        else:
            return "content"
    return "markdown"


def is_banner(text):
    s = text.strip()
    return s.startswith("#") and set(s[1:]) <= set("= ")


def collapse_banners(group):
    out = []
    for c in group:
        if is_banner(c["text"]) and out and is_banner(out[-1]["text"]):
            continue
        out.append(c)
    return out


def dedent4(lines):
    return [l[4:] if l.startswith("    ") else ("" if not l.strip() else l)
            for l in lines]


def align(norm_o, norm_p, report):
    mapping = {}
    i = j = 0
    hoisted = pyonly = 0
    while i < len(norm_o) and j < len(norm_p):
        if norm_o[i] == norm_p[j]:
            mapping[i] = j
            i += 1
            j += 1
            continue
        best = None
        for di in range(0, 7):
            for dj in range(0, 7):
                if i + di >= len(norm_o) or j + dj >= len(norm_p):
                    continue
                r = difflib.SequenceMatcher(
                    None, norm_o[i + di], norm_p[j + dj]).ratio()
                if r >= FUZZY_RATIO:
                    key = (di + dj, -r)
                    if best is None or key < best[0]:
                        best = (key, di, dj)
        if best:
            _, di, dj = best
            hoisted += di
            pyonly += dj
            mapping[i + di] = j + dj
            i, j = i + di + 1, j + dj + 1
        else:
            hoisted += 1
            i += 1
    hoisted += max(0, len(norm_o) - i)
    pyonly += max(0, len(norm_p) - j)
    if hoisted:
        report.append(f"    note: {hoisted} orig stmt(s) hoisted/dropped")
    if pyonly:
        report.append(f"    note: {pyonly} py-only stmt(s) kept")
    return mapping


def process_cell(py_body, orig_src, report, strip_return=True):
    # `@app.function` bodies are top-level (0-indent `def`); `@app.cell`
    # bodies are indented one level inside `def _(...):` and need dedenting.
    body = dedent4(py_body) if strip_return else list(py_body)
    tree = ast.parse("\n".join(body))
    body_nodes = tree.body
    if strip_return:
        ret_node = body_nodes[-1]
        if not isinstance(ret_node, ast.Return):
            return None
        if is_noncontent_cell(body_nodes[:-1]) != "content":
            return None
        ret_start = ret_node.lineno
    else:
        # `@app.function`: the whole def is real user code, no marimo-added
        # trailing `return (...)` tuple to strip.
        ret_start = len(body) + 1

    code_lines = [l for i, l in enumerate(body, 1) if i < ret_start]
    py_stmts = all_stmts("\n".join(code_lines))
    orig_stmts = all_stmts(orig_src.rstrip("\n"))
    orig_comments = comments_of(orig_src.rstrip("\n"))
    if not py_stmts or not orig_stmts:
        return None

    norm_p = [s["norm"] for s in py_stmts]
    mapping = align([s["norm"] for s in orig_stmts], norm_p, report)
    if mapping is None:
        return None
    pre_o, trail_o = bind_comments(orig_stmts, orig_comments)

    stripped = list(code_lines)
    for c in comments_of("\n".join(code_lines)):
        if c["trailing"]:
            stripped[c["line"] - 1] = stripped[c["line"] - 1][: c["col"]].rstrip()
        else:
            stripped[c["line"] - 1] = ""

    if [s["norm"] for s in all_stmts("\n".join(stripped))] != norm_p:
        report.append("    FAIL: statements changed after comment strip")
        return None

    for oi, pj in mapping.items():
        tl = trail_o.get(oi, [])
        if tl:
            s = py_stmts[pj]
            stripped[s["end"] - 1] = stripped[s["end"] - 1].rstrip() + "  " + \
                "  ".join(c["text"] for c in tl)

    ins = defaultdict(list)
    for oi, pj in mapping.items():
        grp = collapse_banners(pre_o.get(oi, []))
        if grp:
            ind = " " * py_stmts[pj]["indent"]
            ins[py_stmts[pj]["start"]].extend(ind + c["text"] for c in grp)
    end_grp = collapse_banners(pre_o.get(len(orig_stmts), []))

    out = list(stripped)
    for ln in sorted(ins.keys(), reverse=True):
        at = ln - 1
        if at > 0 and out[at - 1].strip():
            out.insert(at, "")
            at += 1
        for c in reversed(ins[ln]):
            out.insert(at, c)

    ret_lines = body[ret_start - 1:]
    if end_grp:
        if out and out[-1].strip():
            out.append("")
        out.extend(c["text"] for c in end_grp)
    out.extend(ret_lines)
    while out and not out[0].strip():
        out.pop(0)
    if not strip_return:
        return out  # already at the source's own indentation (0 for `@app.function`)
    return ["    " + l if l.strip() else "" for l in out]


def code_tokens(text):
    out = []
    for t in tokenize.generate_tokens(io.StringIO(text).readline):
        if t.type in IGNORED:
            continue
        s = t.string
        if t.type == tokenize.STRING and "\n" in s:
            # Rebuilding a cell body can rstrip trailing whitespace on blank
            # lines inside a multi-line docstring/string; that's cosmetic,
            # not a code change, so normalize per-line trailing whitespace
            # before comparing.
            s = "\n".join(ln.rstrip() for ln in s.split("\n"))
        out.append(s)
    return out


def process_file(ipynb_path, py_path, write=False):
    report = [f"== {py_path.name} =="]
    ipynb = json.loads(ipynb_path.read_text())
    orig_cells = ["".join(c["source"]) for c in ipynb["cells"]
                  if c["cell_type"] == "code"]
    orig_kinds = ["empty" if not all_stmts(c) else "content" for c in orig_cells]
    orig_content_idx = [i for i, k in enumerate(orig_kinds) if k == "content"]

    src = py_path.read_text()
    lines = src.split("\n")
    tree = ast.parse(src)
    cells = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "cell" for d in n.decorator_list)]
    # `@app.function`: marimo hoists a def with no cross-cell free-variable
    # deps out of the reactive graph; the whole def is real user code
    # (1:1 with its original cell) rather than a `def _(...): ... return`
    # wrapper, so it needs different body/return handling below.
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "function" for d in n.decorator_list)]
    all_nodes = sorted([(n, "cell") for n in cells] + [(n, "function") for n in funcs],
                        key=lambda t: t[0].lineno)

    pairs, n_content = [], 0
    for node, kind in all_nodes:
        if kind == "cell":
            if not isinstance(node.body[-1], ast.Return):
                continue
            if is_noncontent_cell(node.body[:-1]) != "content":
                continue
        if n_content >= len(orig_content_idx):
            report.append("  SKIP: more content cells than orig")
            return report, True
        pairs.append((node, kind, orig_content_idx[n_content]))
        n_content += 1
    if n_content != len(orig_content_idx):
        report.append(f"  SKIP: content cells {n_content} != orig {len(orig_content_idx)}")
        return report, True

    new_lines = list(lines)
    for node, kind, oidx in reversed(pairs):
        if kind == "function":
            body_start, body_end = node.lineno - 1, node.end_lineno
            result = process_cell(lines[body_start:body_end], orig_cells[oidx], report,
                                   strip_return=False)
        else:
            hdr_end = node.body[0].lineno - 1
            while hdr_end > node.lineno and (
                    not lines[hdr_end - 1].strip()
                    or lines[hdr_end - 1].strip().startswith("#")):
                hdr_end -= 1
            body_start, body_end = hdr_end, node.end_lineno
            result = process_cell(lines[body_start:body_end], orig_cells[oidx], report)
        if result is None:
            report.append(f"  FAIL in cell {oidx}: cell left untouched")
            continue
        new_lines[body_start:body_end] = result
        report.append(f"  cell {oidx}: rebuilt")

    out = "\n".join(new_lines)
    ast.parse(out)
    if code_tokens(src) != code_tokens(out):
        report.append("  GLOBAL-FAIL: code tokens changed; file NOT written")
        return report, True
    if write:
        py_path.write_text(out)
    report.append("  OK: code identical, comments restored" + ("" if write else " (dry run)"))
    return report, False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ipynb-dir", default=".", help="directory containing X.ipynb files")
    ap.add_argument("--py-dir", default=".", help="directory containing X.py conversions")
    ap.add_argument("--write", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--files", default="", help="comma-separated stems to limit to")
    args = ap.parse_args()

    ipynb_dir, py_dir = Path(args.ipynb_dir), Path(args.py_dir)
    backup_dir = Path("/tmp/marimo_restore_backup")
    wanted = {s.strip() for s in args.files.split(",") if s.strip()}

    pairs = []
    for ipynb in sorted(ipynb_dir.glob("*.ipynb")):
        py = py_dir / f"{ipynb.stem}.py"
        if py.exists() and (not wanted or ipynb.stem in wanted):
            pairs.append((ipynb, py))
    if not pairs:
        sys.exit("no .ipynb/.py pairs found")

    if args.write:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for _, py in pairs:
            shutil.copy2(py, backup_dir / py.name)

    fail = False
    for ipynb, py in pairs:
        rep, bad = process_file(ipynb, py, write=args.write)
        print("\n".join(rep))
        fail |= bad
    print("\nRESULT:", "ATTENTION NEEDED" if fail else "ALL CLEAN")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
