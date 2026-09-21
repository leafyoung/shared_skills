#!/usr/bin/env python3
"""Chain-canonical verification: prove a marimo conversion is semantically
identical to its .ipynb source — including WHICH VERSION of a re-bound
variable each occurrence refers to.

Rename-tolerant statement diffs (verify_structure.py) can pass a conversion
that loads `df_1` where the original's dataflow implies `df_2`. This script
closes that gap: both sides are walked in evaluation order and every variable
occurrence is labeled with its def-chain identity (fresh id per rebinding,
reused for loads of the live version, idempotent for re-imports, keyed by
name for never-defined externals). Statements are then compared as canonical
dumps over chain labels + normalized constants. The converter's mechanical
transforms vanish; any semantic difference — including a wrong-version
reference — shows up structurally.

Tolerated transforms (all logged, none silent):
  marimo scaffolding (cell wrappers, params, trailing returns);
  string quotes / float repr normalization; redundant parens;
  `x += 1` expanded to `x = x + 1`;
  converter version-renames (`df` -> `df_1`) and privatization (`n` -> `_n`);
  redundant re-imports dropped; `from IPython.display import ...` dropped
  (marimo provides display as a cell parameter).

Usage:
    python verify_chains.py --ipynb-dir DIR --py-dir DIR [--files "A,B"]

Exit 0 iff every pair passes. Run under several PYTHONHASHSEED values when
trusting a new corpus:
    for s in 0 1 42; do PYTHONHASHSEED=$s python verify_chains.py ... ; done

Tooling gotcha this script encodes (learned the hard way): every id()-keyed
map (marks, def_marks, skip_dump) MUST be scoped to a single cell. Dead ASTs
from earlier cells free their node addresses and CPython id reuse silently
relabels live nodes — flaky, seed-dependent verdicts that look like verifier
bugs in the conversion.
"""
import argparse
import ast
import difflib
import json
import sys
import textwrap
from pathlib import Path


class Bail(Exception):
    pass


# ---------------------------------------------------------------- chaining

class ChainCanon:
    """Assigns def-chain labels to Name nodes; one instance PER CELL.

    counter/chain_names are carried across cells by the driver (canon_stmts);
    everything id()-keyed dies with the cell's AST.
    """

    def __init__(self, counter=0, shared_names=None):
        self.counter = counter
        self.marks = {}                      # id(NameNode) -> chain label
        self.def_marks = {}                  # id(FunctionDef/ClassDef) -> label
        self.skip_dump = set()               # id(stmt) of redundant imports
        self.chain_names = shared_names if shared_names is not None else {}

    def fresh(self):
        self.counter += 1
        return f"@{self.counter}"

    def load(self, node, env):
        name = node.id
        if name not in env:
            env[name] = f"ext:{name}"
        self.marks[id(node)] = env[name]
        self.chain_names.setdefault(env[name], set()).add(name)

    def store(self, node, env, is_import=False):
        ch = self.store_name(node.id, env, is_import=is_import)
        self.marks[id(node)] = ch

    def store_name(self, name, env, is_import=False):
        # no node marking: used for aliases/def names/handler names
        if is_import and name in env:
            ch = env[name]          # re-import reuses the existing chain
        else:
            ch = self.fresh()
        env[name] = ch
        self.chain_names.setdefault(ch, set()).add(name)
        return ch

    def store_def(self, node, env):
        ch = self.fresh()
        env[node.name] = ch
        self.def_marks[id(node)] = ch
        self.chain_names.setdefault(ch, set()).add(node.name)

    # ---- expressions (mark loads; nested scopes handled in place) ----
    def x_expr(self, e, env):
        if e is None:
            return
        if isinstance(e, ast.Name):
            if isinstance(e.ctx, (ast.Load, ast.Del)):
                self.load(e, env)
            return
        if isinstance(e, ast.NamedExpr):
            self.x_expr(e.value, env)
            self.store(e.target, env)
            return
        if isinstance(e, ast.Lambda):
            inner = dict(env)
            for p in e.args.args + e.args.kwonlyargs + e.args.posonlyargs:
                inner[p.arg] = self.fresh()
            if e.args.vararg:
                inner[e.args.vararg.arg] = self.fresh()
            if e.args.kwarg:
                inner[e.args.kwarg.arg] = self.fresh()
            for d in e.args.defaults + [d for d in e.args.kw_defaults if d is not None]:
                self.x_expr(d, env)
            self.x_expr(e.body, inner)
            return
        if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self.x_expr(e.generators[0].iter, env)  # first iter: enclosing scope
            inner = dict(env)
            for gi, g in enumerate(e.generators):
                if gi > 0:
                    self.x_expr(g.iter, inner)
                self.s_target(g.target, inner)
                for iff in g.ifs:
                    self.x_expr(iff, inner)
            if isinstance(e, ast.DictComp):
                self.x_expr(e.key, inner)
                self.x_expr(e.value, inner)
            else:
                self.x_expr(e.elt, inner)
            return
        if isinstance(e, ast.Call):
            self.x_expr(e.func, env)
            for a in e.args:
                self.x_expr(a, env)
            for kw in e.keywords:
                self.x_expr(kw.value, env)
            return
        for c in ast.iter_child_nodes(e):
            if isinstance(c, ast.expr):
                self.x_expr(c, env)

    def s_target(self, t, env):
        if isinstance(t, ast.Name):
            self.store(t, env)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self.s_target(e, env)
        elif isinstance(t, ast.Starred):
            self.s_target(t.value, env)
        else:
            self.x_expr(t, env)  # Attribute/Subscript mutate; their Names load

    # ---- statements ----
    def x_stmt(self, s, env):
        if isinstance(s, ast.Assign):
            self.x_expr(s.value, env)
            for t in s.targets:
                self.s_target(t, env)
        elif isinstance(s, ast.AnnAssign):
            if s.value is not None:
                self.x_expr(s.value, env)
            if isinstance(s.target, ast.Name):
                self.store(s.target, env)
            else:
                self.x_expr(s.target, env)
        elif isinstance(s, ast.AugAssign):  # Name targets expanded by AugExpand
            self.x_expr(s.value, env)
            self.x_expr(s.target, env)
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            self.x_expr(s.iter, env)
            self.s_target(s.target, env)
            for x in s.body:
                self.x_stmt(x, env)
            for x in s.orelse:
                self.x_stmt(x, env)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for it in s.items:
                self.x_expr(it.context_expr, env)
                if it.optional_vars is not None:
                    self.s_target(it.optional_vars, env)
            for x in s.body:
                self.x_stmt(x, env)
        elif isinstance(s, (ast.If, ast.While)):
            self.x_expr(s.test, env)
            for x in s.body:
                self.x_stmt(x, env)
            for x in s.orelse:
                self.x_stmt(x, env)
        elif isinstance(s, (ast.Try, ast.TryStar)):
            for x in s.body:
                self.x_stmt(x, env)
            for h in s.handlers:
                if h.name:
                    self.store_name(h.name, env)
                for x in h.body:
                    self.x_stmt(x, env)
            for x in s.orelse:
                self.x_stmt(x, env)
            for x in s.finalbody:
                self.x_stmt(x, env)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in s.decorator_list:
                self.x_expr(d, env)
            if not isinstance(s, ast.ClassDef):
                a = s.args
                for d in a.defaults + [d for d in a.kw_defaults if d is not None]:
                    self.x_expr(d, env)
                for arg in a.args + a.kwonlyargs + a.posonlyargs:
                    if arg.annotation:
                        self.x_expr(arg.annotation, env)
                if getattr(s, "returns", None):
                    self.x_expr(s.returns, env)
            else:
                for b in s.bases:
                    self.x_expr(b, env)
                for kw in s.keywords:
                    self.x_expr(kw.value, env)
            self.store_def(s, env)
            inner = dict(env)
            if not isinstance(s, ast.ClassDef):
                for p in s.args.args + s.args.kwonlyargs + s.args.posonlyargs:
                    inner[p.arg] = self.fresh()
                if s.args.vararg:
                    inner[s.args.vararg.arg] = self.fresh()
                if s.args.kwarg:
                    inner[s.args.kwarg.arg] = self.fresh()
            for x in s.body:
                self.x_stmt(x, inner)
        elif isinstance(s, ast.Return) or isinstance(s, ast.Expr):
            self.x_expr(s.value, env)
        elif isinstance(s, ast.Import):
            if all((a.asname or a.name).split(".")[0] in env for a in s.names):
                self.skip_dump.add(id(s))  # redundant re-import: converter drops it
            for a in s.names:
                self.store_name((a.asname or a.name).split(".")[0], env, is_import=True)
        elif isinstance(s, ast.ImportFrom):
            if s.module == "__future__":
                return
            if all((a.asname or a.name) in env for a in s.names if a.name != "*"):
                self.skip_dump.add(id(s))
            for a in s.names:
                if a.name == "*":
                    raise Bail("star import")
                self.store_name(a.asname or a.name, env, is_import=True)
        elif isinstance(s, (ast.Global, ast.Nonlocal)):
            raise Bail("global/nonlocal statement")
        elif isinstance(s, ast.Match):
            raise Bail("match statement")
        else:
            for c in ast.iter_child_nodes(s):
                if isinstance(c, ast.stmt):
                    self.x_stmt(c, env)
                elif isinstance(c, ast.excepthandler):
                    if c.name:
                        self.store_name(c.name, env)
                    for x in c.body:
                        self.x_stmt(x, env)
                elif isinstance(c, ast.expr):
                    self.x_expr(c, env)


# ------------------------------------------------------------- canonical dump

def const_norm(v):
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, int):
        return f"i:{v}"
    if isinstance(v, float):
        return f"f:{float(v)!r}"      # 1e-8 == 1e-08 == 0.00000001
    if isinstance(v, complex):
        return f"c:{complex(v)!r}"
    return repr(v)                     # decoded str/bytes: quotes irrelevant


def dump(n, cc):
    if isinstance(n, (ast.expr_context, ast.operator, ast.boolop,
                      ast.unaryop, ast.cmpop)):
        return type(n).__name__
    if isinstance(n, ast.Name):
        return f"N({cc.marks.get(id(n), 'unmarked:' + n.id)})"
    if isinstance(n, ast.Constant):
        return f"K({const_norm(n.value)})"
    if isinstance(n, ast.arg):
        return "arg"                   # param names are cell-local detail
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        lbl = cc.def_marks.get(id(n), f"unmarkeddef:{n.name}")
        parts = [lbl]
        for field, value in ast.iter_fields(n):
            if field in ("ctx", "name"):
                continue
            parts.append(dump_val(value, cc))
        return f"{type(n).__name__}({','.join(parts)})"
    parts = []
    for field, value in ast.iter_fields(n):
        if field == "ctx":
            continue
        parts.append(dump_val(value, cc))
    return f"{type(n).__name__}({','.join(parts)})"


def dump_val(v, cc):
    if isinstance(v, ast.AST):
        return dump(v, cc)
    if isinstance(v, list):
        return "[" + ",".join(dump_val(x, cc) for x in v) + "]"
    if v is None:
        return "~"
    return repr(v)


class AugExpand(ast.NodeTransformer):
    """x += y  ->  x = x + y (converter emits the expanded form)."""

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            binop = ast.BinOp(left=ast.Name(id=node.target.id, ctx=ast.Load()),
                              op=node.op, right=node.value)
            new = ast.Assign(targets=[ast.Name(id=node.target.id, ctx=ast.Store())],
                             value=binop)
            return ast.copy_location(new, node)
        return self.generic_visit(node)


def canon_stmts(cell_srcs, params_list):
    """Per-cell canonical statement dumps + the shared ChainCanon bookkeeping."""
    counter, shared_names, env, dumps = 0, {}, {}, []
    for src, params in zip(cell_srcs, params_list):
        cc = ChainCanon(counter, shared_names)   # marks etc. die with this cell
        tree = AugExpand().visit(ast.parse(textwrap.dedent(src)))
        ast.fix_missing_locations(tree)
        sub_env = dict(env)
        for p in params:
            if p not in sub_env:
                sub_env[p] = f"ext:{p}"
            cc.chain_names.setdefault(sub_env[p], set()).add(p)
        for st in tree.body:
            if not isinstance(st, ast.Return):
                cc.x_stmt(st, sub_env)
        env = sub_env
        cell_dumps = [dump(st, cc) for st in tree.body
                      if not isinstance(st, ast.Return) and id(st) not in cc.skip_dump]
        dumps.append(cell_dumps)
        counter = cc.counter
    out = ChainCanon(counter, shared_names)
    return dumps, out


# ------------------------------------------------------------------- inputs

def ipynb_cells(path):
    nb = json.loads(path.read_text())
    out = []
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            src = "".join(c["source"])
            if src.strip():
                out.append(src)
    return out


def strip_ipython_imports(src):
    """Converter drops `from IPython.display import ...` (display becomes a
    cell parameter); mirror that on the ipynb side before comparing."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith(("!", "%")))
    keep = [st for st in tree.body
            if not (isinstance(st, ast.ImportFrom) and st.module == "IPython.display")]
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


def marimo_cells(path):
    src = path.read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "cell" for d in n.decorator_list)]
    bodies, params = [], []
    for fn in fns:
        a = fn.args
        plist = [p.arg for p in a.args + a.kwonlyargs + a.posonlyargs]
        if a.vararg:
            plist.append(a.vararg.arg)
        if a.kwarg:
            plist.append(a.kwarg.arg)
        start = fn.body[0].lineno - 1
        block = lines[start:fn.body[-1].end_lineno]
        if isinstance(fn.body[-1], ast.Return):  # trailing return is scaffolding
            block = block[:fn.body[-1].lineno - 1 - start]
        bodies.append("".join(block))
        params.append(plist)
    return bodies, params


def suspicious(old, new):
    """Renames beyond the converter's two shapes deserve a human look."""
    if new == "_" + old:
        return False  # privatization
    if new.startswith(old):
        tail = new[len(old):]
        if tail and tail.startswith("_") and tail[1:].isdigit():
            return False  # versioning
    return True


# ------------------------------------------------- private-name flow check
#
# `marimo check` / `export script` pass these; they die at runtime:
#   1. `_x` bound in cell A, loaded in cell B  -> NameError (`_` names are
#      cell-private; marimo's error hints at the mangled `_cell_XXXX_x`).
#   2. `_x` bound in cells A and B, and B loads `_x` before its first in-cell
#      store (the `df = df.dropna()` pattern reaching for the previous cell's
#      value) -> UnboundLocalError. Duplicate private defs alone are legal.
# Both rules are params-aware: a cell parameter satisfies the load.

def _cell_fns(tree):
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        getattr(d, "attr", "") == "cell" for d in n.decorator_list)]


def _params_of(fn):
    a = fn.args
    names = [p.arg for p in a.args + a.kwonlyargs + a.posonlyargs]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return set(names)


def _cell_binds(fn):
    """Cell-scope binds (control-flow targets included; nested scopes excluded)."""
    binds = set()

    def target(t):
        if isinstance(t, ast.Name):
            binds.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                target(e)
        elif isinstance(t, ast.Starred):
            target(t.value)

    def expr(e):
        if e is None or isinstance(e, (ast.Lambda, ast.FunctionDef,
                                       ast.AsyncFunctionDef, ast.ClassDef,
                                       ast.ListComp, ast.SetComp,
                                       ast.DictComp, ast.GeneratorExp)):
            return
        if isinstance(e, ast.NamedExpr):
            target(e.target)
        for c in ast.iter_child_nodes(e):
            if isinstance(c, ast.expr):
                expr(c)

    def stmt(s):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binds.add(s.name)
            return
        if isinstance(s, ast.Import):
            for a in s.names:
                binds.add((a.asname or a.name).split(".")[0])
            return
        if isinstance(s, ast.ImportFrom):
            for a in s.names:
                if a.name != "*":
                    binds.add(a.asname or a.name)
            return
        if isinstance(s, (ast.Global, ast.Nonlocal, ast.Match)):
            raise Bail(f"{type(s).__name__} statement")
        if isinstance(s, ast.Assign):
            for t in s.targets:
                target(t)
        elif isinstance(s, (ast.AnnAssign, ast.AugAssign)):
            target(s.target) if isinstance(s.target, ast.Name) else None
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            target(s.target)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for it in s.items:
                if it.optional_vars is not None:
                    target(it.optional_vars)
        elif isinstance(s, ast.ExceptHandler):
            if s.name:
                binds.add(s.name)
        for c in ast.iter_child_nodes(s):
            if isinstance(c, ast.stmt) or isinstance(c, ast.excepthandler):
                stmt(c)
            elif isinstance(c, ast.expr):
                expr(c)

    for st in fn.body:
        stmt(st)
    return binds


def _cell_ops(fn):
    """[(name, 'load'|'store')] in evaluation order at CELL scope; loads free
    in nested scopes are recorded at the scope root's position."""
    ops = []

    def target_ops(t):
        for n in ast.walk(t):
            if isinstance(n, ast.Name):
                ops.append((n.id, "store" if isinstance(n.ctx, ast.Store) else "load"))

    def stmt(s):
        if isinstance(s, ast.Assign):
            expr(s.value)
            for t in s.targets:
                target_ops(t)
        elif isinstance(s, ast.AnnAssign):
            expr(s.value)
            target_ops(s.target)
        elif isinstance(s, ast.AugAssign):
            if isinstance(s.target, ast.Name):
                ops.append((s.target.id, "load"))
                ops.append((s.target.id, "store"))
            else:
                target_ops(s.target)
                expr(s.value)
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            expr(s.iter)
            target_ops(s.target)
            for x in s.body:
                stmt(x)
            for x in s.orelse:
                stmt(x)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for it in s.items:
                expr(it.context_expr)
                if it.optional_vars is not None:
                    target_ops(it.optional_vars)
            for x in s.body:
                stmt(x)
        elif isinstance(s, (ast.If, ast.While)):
            expr(s.test)
            for x in s.body:
                stmt(x)
            for x in s.orelse:
                stmt(x)
        elif isinstance(s, (ast.Try, ast.TryStar)):
            for x in s.body:
                stmt(x)
            for h in s.handlers:
                if h.name:
                    ops.append((h.name, "store"))
                for x in h.body:
                    stmt(x)
            for x in s.orelse:
                stmt(x)
            for x in s.finalbody:
                stmt(x)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in s.decorator_list:
                expr(d)
            if isinstance(s, ast.ClassDef):
                for b in s.bases:
                    expr(b)
                for kw in s.keywords:
                    expr(kw.value)
            else:
                a = s.args
                for d in a.defaults + [d for d in a.kw_defaults if d is not None]:
                    expr(d)
            ops.append((s.name, "store"))
            # free loads of the body surface at the def site
            body_loads = all_loads(s) - all_binds_within(s)
            for ld in sorted(body_loads):
                ops.append((ld, "load"))
        elif isinstance(s, ast.Import):
            for a in s.names:
                ops.append(((a.asname or a.name).split(".")[0], "store"))
        elif isinstance(s, ast.ImportFrom):
            for a in s.names:
                if a.name != "*":
                    ops.append((a.asname or a.name, "store"))
        elif isinstance(s, (ast.Global, ast.Nonlocal, ast.Match)):
            raise Bail(f"{type(s).__name__} statement")
        elif isinstance(s, (ast.Return, ast.Expr)):
            expr(s.value)
        else:
            for c in ast.iter_child_nodes(s):
                if isinstance(c, ast.stmt):
                    stmt(c)
                elif isinstance(c, ast.excepthandler):
                    for x in c.body:
                        stmt(x)
                elif isinstance(c, ast.expr):
                    expr(c)

    def expr(e):
        if e is None:
            return
        if isinstance(e, ast.Name):
            ops.append((e.id, "load"))
            return
        if isinstance(e, (ast.Lambda, ast.ListComp, ast.SetComp,
                          ast.DictComp, ast.GeneratorExp)):
            body_loads = all_loads(e) - all_binds_within(e)
            for ld in sorted(body_loads):
                ops.append((ld, "load"))
            return
        if isinstance(e, ast.NamedExpr):
            expr(e.value)
            target_ops(e.target)
            return
        for c in ast.iter_child_nodes(e):
            if isinstance(c, ast.expr):
                expr(c)

    for st in fn.body:
        stmt(st)
    return ops


def all_loads(node):
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def all_binds_within(node):
    """Any name bound anywhere inside node (any scope depth) - conservative."""
    binds = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            binds.add(n.id)
        elif isinstance(n, ast.arg):
            binds.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binds.add(n.name)
        elif isinstance(n, ast.alias):
            binds.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            binds.add(n.name)
    return binds


def private_flow_problems(py_path):
    """The two runtime-private-name rules, params-aware. Returns [messages]."""
    tree = ast.parse(py_path.read_text())
    cells = _cell_fns(tree)
    binds, params, ops = [], [], []
    for fn in cells:
        binds.append(_cell_binds(fn))
        params.append(_params_of(fn))
        ops.append(_cell_ops(fn))
    where = {}
    for i in range(len(cells)):
        for name in binds[i] | params[i]:
            where.setdefault(name, set()).add(i)
    problems = []
    for i in range(len(cells)):
        for name, kind in ops[i]:
            if kind != "load" or not name.startswith("_") or name == "_":
                continue
            if name in binds[i] or name in params[i]:
                continue
            if where.get(name):
                problems.append(
                    f"cell {i}: loads private `{name}` bound in cell(s) "
                    f"{sorted(where[name])} -> runtime NameError")
        first_store = {}
        for pos, (name, kind) in enumerate(ops[i]):
            if kind == "store" and name not in first_store:
                first_store[name] = pos
        for pos, (name, kind) in enumerate(ops[i]):
            if (kind == "load" and name.startswith("_") and name != "_"
                    and name in binds[i] and name not in params[i]
                    and pos < first_store.get(name, 10 ** 9)
                    and len(where.get(name, set())) > 1):
                problems.append(
                    f"cell {i}: private `{name}` loaded before its in-cell store "
                    f"(sees the previous cell's value) -> UnboundLocalError")
    return sorted(set(problems))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
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

    n_ok = n_fail = 0
    for nb_path, py_path in pairs:
        base = py_path.stem
        nb_srcs = ipynb_cells(nb_path)
        try:
            nb_clean = [strip_ipython_imports(s) for s in nb_srcs]
        except SyntaxError as e:
            print(f"FAIL: {base}: ipynb cell does not parse: {e}")
            n_fail += 1
            continue
        mbodies, mparams = marimo_cells(py_path)
        try:
            nb_dumps, nb_cc = canon_stmts(nb_clean, [[] for _ in nb_clean])
            mo_dumps, mo_cc = canon_stmts(mbodies, mparams)
        except Bail as e:
            print(f"SKIP (needs manual review): {base}: {e}")
            continue
        except SyntaxError as e:
            print(f"FAIL: {base}: converted cell does not parse: {e}")
            n_fail += 1
            continue

        problems = []
        if len(nb_dumps) != len(mo_dumps):
            problems.append(f"cell count {len(nb_dumps)} (ipynb) vs {len(mo_dumps)} (marimo)")
        for i in range(min(len(nb_dumps), len(mo_dumps))):
            if nb_dumps[i] == mo_dumps[i]:
                continue
            sm = difflib.unified_diff(nb_dumps[i], mo_dumps[i], lineterm="", n=0)
            problems.append(f"cell {i}:\n" + "\n".join("    " + l for l in list(sm)[2:30]))
        try:
            problems.extend(private_flow_problems(py_path))
        except Bail as e:
            print(f"SKIP (needs manual review): {base}: private-flow check hit {e}")
            n_fail += 1
            continue

        renames = []
        for ch in nb_cc.chain_names.keys() | mo_cc.chain_names.keys():
            if not ch.startswith("@"):
                continue
            nset = nb_cc.chain_names.get(ch, set())
            mset = mo_cc.chain_names.get(ch, set())
            if nset and mset and nset != mset:
                renames.append((ch, sorted(nset), sorted(mset)))
        suspects = [(ch, a, b) for ch, a, b in renames
                    if any(suspicious(x, y) for x in a for y in b)]

        if problems:
            n_fail += 1
            print(f"FAIL: {base}")
            for p in problems:
                print("  " + p)
        else:
            n_ok += 1
            rr = "; ".join(f"{ch}:{'+'.join(a)}->{'+'.join(b)}"
                           for ch, a, b in renames) if renames else "-"
            print(f"OK: {base}  chains[{rr}]")
            for ch, a, b in suspects:
                print(f"  SUSPECT rename (review shape): {ch}: {a} -> {b}")

    print(f"\nCHAIN RESULT: {'FAIL' if n_fail else 'ALL PASS'} (ok={n_ok} fail={n_fail})")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
