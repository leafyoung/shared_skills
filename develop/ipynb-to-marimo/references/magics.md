# Magic Command Translation

`marimo convert` cannot execute IPython magics. Unsupported ones survive as
`get_ipython()` calls, `!`/`%` line prefixes, or converter comments. Scan first:

```bash
grep -nE "get_ipython|^\s*[!%][a-zA-Z%]" <notebook.py>
```

Rule of thumb: **delete** environment magics, **translate** compute magics,
**replace** shell escapes. Keep translated timing visible — it was in the source
notebook for a reason.

## Timing magics

### `%timeit stmt` and `%timeit -n N -r R -p P stmt`

`%timeit` reports the *best of R repeats × N loops*. Direct equivalent:

```python
import timeit

best = min(timeit.repeat(lambda: f(x), number=N, repeat=R))
print(f"{best * 1e3 / N:.3f} ms per loop")   # timeit returns total per repeat
```

Notes:
- `lambda:` avoids re-binding globals; for statements, pass a string and set
  `globals=globals()`:
  ```python
  timeit.timeit("np.dot(a, b)", number=N, globals=globals())
  ```
- `-p N` (precision) has no direct knob — format the print yourself.

### `%%timeit` (whole cell)

Wrap the cell body in a function and time it:

```python
import timeit

def _bench():
    # ...original cell body, magic removed...
    result = heavy_pipeline(data)
    return result

best = min(timeit.repeat(_bench, number=1, repeat=7))
print(f"best of 7: {best:.4f}s")
```

Keep the result visible after the benchmark: assign inside `_bench` to a name you
return, or print it — a bare cell body that only benchmarks loses the side effect
the notebook relied on.

### `%time stmt`

```python
import time
t0 = time.perf_counter()
stmt
print(f"{time.perf_counter() - t0:.4f}s")
```

## Environment / install magics — delete

| Jupyter | Action |
|---|---|
| `%matplotlib inline` | Delete. marimo renders matplotlib figures automatically (one figure per cell; use `plt.gcf()` or return the figure). |
| `%pip install X` / `!pip install X` | Delete; declare the dependency with `uv add X` (project) or in PEP 723 script metadata. Never reintroduce install cells. |
| `%load_ext autoreload` / `%autoreload 2` | Delete. marimo re-runs cells on edit; for module development use `importlib.reload(mod)`. |
| `%env VAR` / `%set_env VAR=v` | `os.environ.get("VAR")` / `os.environ["VAR"] = "v"`. |
| `%xmode`, `%pdb`, `%debug` | Delete; use `breakpoint()` / the debugger UI. |
| `%who`, `%whos`, `%lsmagic`, `%magic`, `%quickref` | Delete or `print(dir())` / `print(locals().keys())`. |
| `%store`, `%xdel` | Delete; marimo's variable state is per-run, no cross-session persistence. |

## Shell escapes

| Jupyter | marimo / Python |
|---|---|
| `!cmd arg1 arg2` | `subprocess.run(["cmd", "arg1", "arg2"], check=True)` |
| `!cmd > out.txt` | `subprocess.run(..., stdout=open("out.txt", "w"))` |
| `!cd dir && cmd` | `subprocess.run([...], cwd="dir")` |
| `%%bash` (cell) | `subprocess.run(["bash", "-c", script_text], check=True)` or a `scripts/` file |
| `%%capture out` (cell) | `contextlib.redirect_stdout(io.StringIO())` |
| `%%writefile path` (cell) | `Path("path").write_text("...")` with the cell body as a string |
| `%run script.py args` | Refactor to `import script` / a function call; `%run`'s shared-namespace behavior does not translate. |

## What conversion failure looks like

- `SyntaxError` at convert time → a magic the parser can't drop; hand-edit the cell
  to its Python translation in the `.ipynb` first, then re-convert.
- `get_ipython()` remnants in the `.py` → translate per the tables above.
- `NameError: name 'display' is not defined` at run time → IPython auto-injects
  `display` in Jupyter; marimo does not. Add `from IPython.display import display`
  to the first cell using it and add `display` to that cell's `return` tuple.
