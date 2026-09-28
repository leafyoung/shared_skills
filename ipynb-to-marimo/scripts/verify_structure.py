#!/usr/bin/env python3
"""Structural verification: every original .ipynb statement must be present in
its marimo .py conversion, in order, rename-tolerant.

Usage:
    python verify_structure.py --ipynb-dir DIR --py-dir DIR [--files "A,B"]

PASS = no lost statements. Report-only extras (e.g. an added display import)
and converter-deduplicated imports (verified present elsewhere) do not fail.
"""
import argparse
import ast
import copy
import difflib
import json
import sys
from pathlib import Path

FUZZY = 0.7
IGNORED_WINDOW = 7


def shallow_dump(node):
    n = copy.deepcopy(node)
    for field in ("body", "orelse", "finalbody", "handlers"):
        if getattr(n, field, None) is not None:
            setattr(n, field, [])
    return ast.dump(n)


class AugExpand(ast.NodeTransformer):
    """x += y  ->  x = x + y (converter emits the expanded form), for any
    assignable target -- Name, Subscript (`y[i] -= v`), or Attribute."""

    def visit_AugAssign(self, node):
        if isinstance(node.target, (ast.Name, ast.Subscript, ast.Attribute)):
            load_target = copy.deepcopy(node.target)
            load_target.ctx = ast.Load()
            store_target = copy.deepcopy(node.target)
            store_target.ctx = ast.Store()
            binop = ast.BinOp(left=load_target, op=node.op, right=node.value)
            new = ast.Assign(targets=[store_target], value=binop)
            return ast.copy_location(new, node)
        return self.generic_visit(node)


def all_stmts(src):
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                compound = bool(getattr(child, "body", None))
                out.append({"norm": shallow_dump(child) if compound else ast.dump(child)})
                walk(child)

    try:
        tree = ast.parse(src)
    except SyntaxError:
        stripped = "\n".join(
            "#" + ln if ln.lstrip().startswith(("%", "!")) else ln
            for ln in src.split("\n")
        )
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            return out
    tree = AugExpand().visit(tree)
    ast.fix_missing_locations(tree)
    walk(tree)
    return out


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


def orig_content_stmts(ipynb_path):
    nb = json.loads(ipynb_path.read_text())
    cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    n_with_code = sum(1 for c in cells if all_stmts(c))
    stmts = []
    for c in cells:
        stmts.extend(all_stmts(c))
    return stmts, n_with_code


def marimo_content_stmts(py_path):
    src = py_path.read_text()
    lines = src.split("\n")
    tree = ast.parse(src)
    cells = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "cell" for d in n.decorator_list)]
    # `@app.function`: marimo hoists a def with no cross-cell free-variable
    # deps out of the reactive graph. It has no marimo-added trailing
    # `return (...)` tuple -- the whole def IS the cell's one statement,
    # same as the original notebook cell it came from.
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "function" for d in n.decorator_list)]
    content, n_content = [], 0
    for node in funcs:
        n_content += 1
        func_src = "\n".join(lines[node.lineno - 1:node.end_lineno])
        content.extend(all_stmts(func_src))
    for node in cells:
        if not isinstance(node.body[-1], ast.Return):
            continue
        if is_noncontent_cell(node.body[:-1]) != "content":
            continue
        n_content += 1
        hdr_end = node.body[0].lineno - 1
        while hdr_end > node.lineno and (
                not lines[hdr_end - 1].strip()
                or lines[hdr_end - 1].strip().startswith("#")):
            hdr_end -= 1
        body = "\n".join(lines[hdr_end:node.end_lineno])
        body = "\n".join(l[4:] if l.startswith("    ") else
                         ("" if not l.strip() else l) for l in body.split("\n"))
        ret = next(n for n in ast.parse(body).body if isinstance(n, ast.Return))
        code = "\n".join(body.split("\n")[: ret.lineno - 1])
        content.extend(all_stmts(code))
    return content, n_content


def align(norm_o, norm_p):
    mapping, skipped = {}, []
    i = j = 0
    while i < len(norm_o) and j < len(norm_p):
        if norm_o[i] == norm_p[j]:
            mapping[i] = "exact"
            i += 1
            j += 1
            continue
        best = None
        for di in range(0, IGNORED_WINDOW):
            for dj in range(0, IGNORED_WINDOW):
                if i + di >= len(norm_o) or j + dj >= len(norm_p):
                    continue
                r = difflib.SequenceMatcher(
                    None, norm_o[i + di], norm_p[j + dj]).ratio()
                if r >= FUZZY and (best is None or (di + dj, -r) < best[0]):
                    best = ((di + dj, -r), di, dj, r)
        if best:
            _, di, dj, r = best
            skipped.extend(range(i, i + di))
            mapping[i + di] = round(r, 3)
            i, j = i + di + 1, j + dj + 1
        else:
            skipped.append(i)
            i += 1
    skipped.extend(range(i, len(norm_o)))
    return mapping, skipped, list(range(j, len(norm_p)))


def present_elsewhere(dump, norm_p):
    if dump in norm_p:
        return True
    return any(difflib.SequenceMatcher(None, dump, q).ratio() >= FUZZY
               for q in norm_p)


def shorten(dump, n=90):
    return dump.replace(" ", "")[:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ipynb-dir", default=".")
    ap.add_argument("--py-dir", default=".")
    ap.add_argument("--files", default="", help="comma-separated stems to limit to")
    args = ap.parse_args()

    ipynb_dir, py_dir = Path(args.ipynb_dir), Path(args.py_dir)
    wanted = {s.strip() for s in args.files.split(",") if s.strip()}
    pairs = [(p, py_dir / f"{p.stem}.py") for p in sorted(ipynb_dir.glob("*.ipynb"))
             if (py_dir / f"{p.stem}.py").exists()
             and (not wanted or p.stem in wanted)]
    if not pairs:
        sys.exit("no .ipynb/.py pairs found")

    fail = False
    for ipynb_path, py_path in pairs:
        o, n_o_cells = orig_content_stmts(ipynb_path)
        p, n_m_cells = marimo_content_stmts(py_path)
        line = [f"== {py_path.stem} =="]
        ok = True
        if n_o_cells != n_m_cells:
            line.append(f"  CELL MISMATCH: orig-with-code {n_o_cells} vs marimo {n_m_cells}")
            ok = False
        norm_o = [s["norm"] for s in o]
        norm_p = [s["norm"] for s in p]
        mapping, skipped, py_only = align(norm_o, norm_p)
        exact = sum(1 for v in mapping.values() if v == "exact")
        line.append(f"  orig stmts {len(o)} | marimo stmts {len(p)} | "
                    f"matched {len(mapping)} (exact {exact}, rename/fuzzy {len(mapping) - exact})")
        lost = [k for k in skipped if not present_elsewhere(norm_o[k], norm_p)]
        dedup = len(skipped) - len(lost)
        if dedup:
            line.append(f"  converter-deduplicated at position, verified present elsewhere: {dedup}")
        if lost:
            ok = False
            line.append(f"  LOST ORIG STATEMENTS: {len(lost)}")
            for k in lost[:6]:
                line.append(f"    orig[{k}]: {shorten(norm_o[k])}")
        if py_only:
            line.append(f"  marimo-only statements (trailing): {len(py_only)}")
            for k in py_only[:6]:
                line.append(f"    py[{k}]: {shorten(norm_p[k])}")
        line.append("  PASS" if ok else "  FAIL")
        if not ok:
            fail = True
        print("\n".join(line))

    print("\nSTRUCTURAL RESULT:", "FAIL" if fail else "ALL PASS")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
