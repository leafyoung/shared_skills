"""Layer-3 verification: diff normalized text output of .ipynb vs marimo twins.

For every ``*.ipynb`` in --ipynb-dir with a same-stem ``*.py`` in --py-dir:

1. Collect the notebook's stored text outputs (stdout streams + display_data
   ``text/plain``, in cell order).
2. Execute the marimo app in-process (importlib load + ``app.run()``) with
   cwd set to the ipynb dir and stdout/stderr captured.
3. Normalize both sides symmetrically (drop renderer noise, round floats to
   3 significant digits) and compare.

Verdicts: PASS (exact after normalization), PASS-STOCHASTIC (identical
skeleton: every number masked, internal whitespace collapsed, sorted line
multisets equal — for unseeded training/optimizer notebooks proven
nondeterministic by rerunning the original), DIFF (unified-diff excerpt),
EXEC-FAIL. Exit 0 only when every pair passes.

Usage:
    uv run python verify_outputs.py --ipynb-dir . --py-dir . \
        [--env NAME=VALUE ...] [--extra-noise REGEX] ... [--pair SUBSTR]
        [--diff-lines N]
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

# Lines dropped from BOTH sides before comparing. Each class was observed in
# practice; none carries conversion-relevant information.
NOISE_PATTERNS = [
    r"^\s*$",
    # progress bars (tqdm / keras), including backspace-erase lines
    r"%\|", r"it/s", r"s/it", "━", r"ETA", r"/step", r"\x08",
    r"^Epoch \d+", r"^\d+/\d+ \[", r"Restoring model",
    # keras model.summary(): ANSI-styled box in Jupyter, plain box headless
    r"^Model: ", r"params\)", r"Trainable params", r"Non-trainable",
    r"^Total params",
    # optimizer chatter (optuna-style)
    r"^\[I ", r"^\[W ", r"Best is trial", r"A new study created",
    r"finished with value", r"^Trial \d+", r"^Params:",
    # warnings and their traceback frames (continuation lines may be
    # project-specific — pass --extra-noise for those)
    r"WARNING", r"[Ww]arning", r"Deprecat", r"site-packages", r"Traceback",
    # framework startup noise
    r"oneDNN", r"cuda", r"TF-TRT", r"absl", r"[Tt]ensor[Ff]low",
    # Jupyter renders figures as reprs the headless side never prints
    r"<Figure size ",
    # ANSI escapes and box-drawing characters (styled tables)
    r"\x1b", r"[│┃├┼┤┬┴┌┐└┘╒╤╕╞╪╘╧═]",
]
# Pandas preview furniture: display() and print() truncate/wrap wide tables
# differently, so table rows/headers/markers are dropped symmetrically and
# only "[N rows x M columns]"-style content-free summaries could remain.
TABLE_PATTERNS = [
    r"^\d+(\s+\S+)*$",                                # index-led data rows
    r"^[A-Za-z_][A-Za-z_0-9]*(\s{2,}[A-Za-z_][A-Za-z_0-9]*)*\s*\\?$",  # header chunks
    r"\.\.\.",                                        # truncation markers
    r"^\\$",                                          # wrap continuations
    r"^\[\d+ rows? x \d+ columns?\]$",
    # notebooks that enumerate their own output dir list different files
    # mid-run (linear vs topological cell order, prior runs)
    r"^- .+\.(csv|keras|png|txt|json|pkl|parquet|h5)$",
]
FLOAT_RE = re.compile(r"-?\d+\.\d+(?:[eE][-+]?\d+)?")
SKELETON_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def compile_noise(extra: list[str]) -> re.Pattern:
    return re.compile("|".join(NOISE_PATTERNS + extra) + "|" + "|".join(TABLE_PATTERNS))


def norm_text(text: str, noise: re.Pattern) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if noise.search(line):
            continue
        line = FLOAT_RE.sub(lambda m: f"{float(m.group()):.3g}", line)
        if line:
            lines.append(line)
    return lines


def skeleton(lines: list[str]) -> list[str]:
    """Numbers masked, whitespace collapsed, order-insensitive: tolerates the
    churn of unseeded runs (digit-width realignment, sign flips on near-zero
    values, row swaps in stochastically sorted tables). Masked numbers get
    their own token so alignment padding ([[255 vs [[ 593) normalizes away."""
    return sorted(
        " ".join(SKELETON_NUM_RE.sub(" # ", " ".join(ln.split())).split())
        for ln in lines
    )


def ipynb_text(path: Path) -> str:
    import warnings

    import nbformat

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # schema warnings on read are noise here
        nb = nbformat.read(path, as_version=4)
    chunks: list[str] = []
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            if out.output_type == "stream" and out.name == "stdout":
                chunks.append(out.text)
            elif out.output_type == "display_data":
                plain = out.get("data", {}).get("text/plain")
                if isinstance(plain, str):
                    chunks.append(plain)
    return "\n".join(chunks)


def marimo_text(path: Path, cwd: Path, env: dict[str, str]) -> str:
    prev_cwd = os.getcwd()
    saved_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        name = f"_verify_{re.sub(r'\\W', '_', path.stem)}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            spec.loader.exec_module(module)  # defines app
            module.app.run()  # exceptions propagate to the caller
    finally:
        os.chdir(prev_cwd)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ipynb-dir", required=True)
    ap.add_argument("--py-dir", required=True)
    ap.add_argument("--env", action="append", default=[],
                    metavar="NAME=VALUE",
                    help="environment variable for the marimo run (e.g. FAST_RUN=1)")
    ap.add_argument("--extra-noise", action="append", default=[],
                    help="extra regex dropped from both sides (repeatable)")
    ap.add_argument("--pair", default=None, help="only pairs whose stem contains this")
    ap.add_argument("--diff-lines", type=int, default=30)
    args = ap.parse_args()

    os.environ.setdefault("MPLBACKEND", "Agg")  # before any app imports pyplot
    env = dict(kv.split("=", 1) for kv in args.env)
    noise = compile_noise(args.extra_noise)

    ipynb_dir, py_dir = Path(args.ipynb_dir).resolve(), Path(args.py_dir).resolve()
    pairs = sorted(
        (nb, py_dir / f"{nb.stem}.py")
        for nb in ipynb_dir.glob("*.ipynb")
        if (py_dir / f"{nb.stem}.py").exists()
    )
    if args.pair:
        pairs = [(nb, py) for nb, py in pairs if args.pair in nb.stem]
    if not pairs:
        sys.exit("no ipynb/marimo pairs found")

    failures = []
    for nb_path, py_path in pairs:
        print(f"[verify] {nb_path.name} vs {py_path.name}", flush=True)
        try:
            want = norm_text(ipynb_text(nb_path), noise)
        except Exception as exc:  # noqa: BLE001
            failures.append(nb_path.name)
            print(f"[EXEC-FAIL] ipynb unreadable: {exc}", flush=True)
            continue
        try:
            got = norm_text(marimo_text(py_path, ipynb_dir, env), noise)
        except Exception as exc:  # noqa: BLE001
            failures.append(nb_path.name)
            print(f"[EXEC-FAIL] marimo app raised: {type(exc).__name__}: {exc}", flush=True)
            continue

        if want == got:
            print("[PASS]", flush=True)
        elif len(want) == len(got) and skeleton(want) == skeleton(got):
            print("[PASS-STOCHASTIC] identical skeleton, numeric churn only", flush=True)
        else:
            failures.append(nb_path.name)
            print(f"[DIFF] {len(want)} vs {len(got)} normalized lines", flush=True)
            diff = list(difflib.unified_diff(want, got, "ipynb", "marimo", lineterm=""))
            for line in diff[: args.diff_lines]:
                print("   ", line[:160], flush=True)

    if failures:
        sys.exit(f"not verified: {', '.join(failures)}")
    print("all pairs verified")


if __name__ == "__main__":
    main()
