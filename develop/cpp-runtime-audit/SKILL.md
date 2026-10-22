---
name: cpp-runtime-audit
description: This skill should be used when the user asks to benchmark, profile, or audit compiled C++ programs or C++ solution/exercise banks - measuring peak memory (max RSS), wall time, or speed across optimization levels (-O0/-O2/-O3) and compilers (clang++/g++), attributing heap to source lines (valgrind massif), finding leaks (memcheck), detecting data races (helgrind, DRD), or running such checks in parallel with per-core pinning (taskset) and multi-thread detection. Triggers include "benchmark these solutions", "measure peak memory / RSS", "memory profiling", "valgrind", "massif", "leak check", "leak-shape analysis", "helgrind", "drd", "race detection", "profile cpp executables", "pin to CPU", "parallel profiling".
---

# C++ Runtime Audit

**Objective**: benchmark time and peak memory first, then expand into stack/heap-safety checks and
parallel-race detection - and synthesize everything into a concrete improvement perspective for
the sources (safety, robustness, speed, memory).

Audit compiled C++ programs across compilers and optimization levels, in parallel with per-core
pinning. The bundled script `scripts/measure_peak_rss.py` implements the full pipeline; this
document tells you how to run it, adapt it to a new code layout, and adjudicate its findings.
Always finish an audit with `--report`: raw CSVs are evidence, the improvement report is the
deliverable.

## Prerequisites

The host is often immutable (Silverblue) or missing valgrind. Run everything inside a
distrobox/podman container that has the toolchain; the repo is visible at the same path
(distrobox shares $HOME). One consistent toolchain for all measurements:

```bash
# Bank layout: export CPP_AUDIT_BANKS=/path/to/banks.json (JSON describing the solution banks; the
# script refuses to run without it - see bank_specs() in scripts/measure_peak_rss.py for the format).
# one-time (<container> is a distrobox container with dnf):
podman exec <container> dnf install -y valgrind gcc-c++ clang   # check: which valgrind clang++ g++
# <container> is known-good: g++ 15.2.1, clang++ 20.1.8, valgrind 3.26, 32 cores
```

Copy `scripts/measure_peak_rss.py` into `<tree>/runtime_audit_report/` (the same dir that receives the
CSVs; the script detects it sits inside `runtime_audit_report` and audits the tree above), then invoke
via `podman exec <container> python3 <tree>/runtime_audit_report/measure_peak_rss.py <mode>`. Inside a git
repo the script appends `runtime_audit_report/` to the tree's `.gitignore` itself, so script and
artifacts never dirty `git status`. Note: the container's `/tmp` is its
own tmpfs, NOT the host's `/tmp` - scratch in `/tmp/memsweep` is container-side only and wiped per
invocation; keep durable artifacts inside the audited tree (shared via $HOME).

## Modes

| command | measures | artifact | source annotation |
|---|---|---|---|
| `measure_peak_rss.py` | peak RSS + wall time at `-O0/-O2/-O3` x clang++/g++ | `runtime_audit_report/peak_memory.csv` | `// peak-rss:` |
| `... --massif` | per-line heap attribution at peak | `runtime_audit_report/peak_memory_lines.csv` | `// peak-alloc:` |
| `... --leaks` | memcheck leak-shape: definite/indirect/possibly lost, still reachable, error count | `runtime_audit_report/leaks.csv` | `// leak-suspect:` (only when lost > 0 or errors) |
| `... --san` | ASan+UBSan+LSan, hardened stdlib (`-D_GLIBCXX_ASSERTIONS`), ~2x overhead | `runtime_audit_report/sanitizers.csv` | `// san-suspect:` (only when flagged) |
| `... --races` | helgrind + DRD on MT-flagged units only | `runtime_audit_report/races.csv` | `// race-suspect:` (only when errors > 0) |
| `... --tsan` | ThreadSanitizer (`-fsanitize=thread -O1 -g`) on MT-flagged units, serial unpinned | `runtime_audit_report/races.csv` (tool=tsan) | `// race-suspect:` (only when alerts) |
| `... --report` | synthesize all CSVs into per-unit improvement advice | `runtime_audit_report/IMPROVEMENT_REPORT.md` | none |

`peak_memory.csv` also records per-opt wall times (clang) and `-fstack-usage` stack frames
(`stack_max_bytes`, `stack_sum_bytes`) - the inputs for the speed and stack perspectives.
massif attribution prefers ROOT-relative user frames; when the peak snapshot contains none
(tiny programs peak inside std's buffer alloc), it falls back to per-line maxima across all
detailed snapshots. Scratch lives in `/tmp/memsweep_<tree>` (per-tree, container-side).

## Order of operations (best practice)

1. **Build clean**: `-Wall -Wextra` first; warnings predict most findings.
2. **Sanitize fast**: `--san` (ASan+UBSan+LSan, ~2x slowdown) catches use-after-free, overflow,
   UB and leaks on the whole bank in minutes. One sanitizer at a time; ASan includes LSan on
   Linux; `ASAN_OPTIONS=detect_stack_use_after_return=1` is set by the script.
3. **Harden the stdlib**: `-D_GLIBCXX_ASSERTIONS` (bundled in san mode) catches container misuse
   (`.at()` bounds, invalid ranges) without sanitizer slowdown.
4. **Races**: `--tsan` first (sees LLVM atomics -> few FPs; `-O1` per upstream guidance - higher
   opts reduce accuracy). helgrind/DRD (`--races`) are the fallback cross-check; expect the FP
   classes listed under Adjudication.
5. **Deep dive**: memcheck/massif (`--leaks` / `--massif`, ~20x slowdown) for what sanitizers
   miss (uninitialised reads need memcheck; precise heap-shape per line). `valgrind --tool=dhat`
   is a faster massif alternative when exact allocation counts matter.
6. **Publishable wall times**: the harness gives single-run seconds + RSS; for publishable
   numbers use hyperfine (`hyperfine -w 3 -m 10 'bin'`), pin CPU, keep batches homogeneous.

All modes: `--only ID1,ID2` for subsets (debug; phase_opts refuses to write the full CSV in
only-mode), resumable (leaks/races append and skip already-done ids), idempotent annotations
(replaced by prefix match). Baseline facts for a typical 14 MB-floor toolchain: trivial programs
peak ~13-15 MB; massif heap peaks of 4 KB vs 40 MB are meaningful; anything within ~1 MB of the
floor is noise.

## Pipeline (what the script does, so you can adapt it)

1. **Discover units**: walk the tree for solution dirs (patterns `*_solution*`, `cpp` subdirs,
   per-question dirs) and map each to a stable id. Multi-cpp dirs: try link-all; on "multiple
   definition", fall back to per-cpp units. Probe-build with g++ for grouping (compiler-agnostic).
2. **Detect std**: `-std=c++20` if sources match `jthread|concept |co_await|operator<=>|<=>`,
   else `-std=c++17`. Always `-Wall -Wextra -pthread`, plus `-I<root> -I<root>/h` when present.
3. **Run harness** (the fragile part - do not simplify away):
   - isolate each run in a fresh dir seeded with `*.csv *.txt *.dat` from the solution dir
     (programs write outputs there, never into the repo);
   - `stdin=DEVNULL`; **drain stdout in a thread** - pipes on this host hold only ~8 KB, an
     undrained chatty child blocks forever (fake TIMEOUTs);
   - wait with `os.wait4(..., WNOHANG)` polling: gives **per-child max RSS** (`ru_maxrss`, KB on
     Linux) and a hard timeout (`SIGKILL` after poll overshoot); never use
     `resource.getrusage(RUSAGE_CHILDREN)` (cumulative max across children);
   - count `/proc/<pid>/task` entries while waiting -> runtime thread count;
   - pin via `taskset -c <cpu>` prepended to argv (RSS unaffected by pinning; wall time honest).
4. **Parallelism**: one worker thread per CPU (`NWORK = min(24, cores-4)`), each worker owning a
   core; per-worker-unique binary and log paths (shared names race). Units whose sources match
   `\bstd::thread\b|\bjthread\b|std::async|pthread_create|std::future\b|std::promise\b|#pragma omp|parallel_for`
   are **deferred and run serially unpinned** at the end (pinning MT programs distorts timing and
   invites hangs). If a "single-thread" unit shows `threads_max > 1` at runtime, re-run it
   unpinned - static grep misses hidden threads (thread pools, `std::async` inside libraries).
5. **Parse tool logs**:
   - massif: find the `heap_tree=peak` snapshot; frames look like
     ` n1: BYTES 0xADDR: FUNC (path/file.cpp:LINE)` (note the colon after the address); filter to
     ROOT-relative user files, fall back to all frames for runtime-baseline-only programs;
     bytes are inclusive per line; take max per (file,line), rank top 8;
   - memcheck: parse `LEAK SUMMARY` kinds + `N bytes in M blocks are (definitely|indirectly|
     possibly) lost in loss record` + `ERROR SUMMARY: N errors` (leak records count as errors);
   - helgrind: `Possible data race` contexts + two conflicting frames; DRD: `Conflicting load/
     store` + `Probably a race condition: condition variable ... signaled but ... mutex not locked`.
6. **Write back**: CSVs plus one idempotent comment line per measurement in the source file that
   contains `int main(` (multi-file projects: only the main file).

## Gotchas (each one cost a debugging session)

- Stale output files in shared `/tmp` (e.g. a report a program writes) cause false RUN_FAILs with
  exit=2; `rm` them before re-running. Container-root files (uid 524288) are unwritable from the
  host user and vice versa - do scratch work under `$HOME`, not `/tmp`.
- `--only` on modes that rewrite the CSV replaces the whole file; the script guards this, keep the
  guard if you edit.
- Pipe capacity here is ~8 KB (not the usual 64 KB) - always drain child stdout/stderr.
- `re.sub` patterns pasted through edit tooling: watch for doubled backslashes (`\\(` matches a
  literal backslash-paren, not a group). Test parsers on a real log before a long batch.
- Annotate only with ASCII hyphens (no U+2014/U+2013/U+2212) if the audited repo enforces it.
- **Aborted host `podman exec` leaves container orphans.** Killing the host-side call does not kill container children - a detector kept 99% CPU for 30+ min. Before re-running: `podman exec <container> sh -c "ps aux | grep -E 'valgrind|measure_peak' | grep -v grep"`, then `kill -9` by explicit PID. Identify ownership by source-tree path first - a PPID-0 detached run may be another session's audit, not yours.
- **Never `pkill -f <script-name>`.** It matches your own `podman exec sh -c "..."` wrapper - you SIGKILL your own shell (exit 137) and orphan the children anyway. Kill by PID list from `ps`.
- **Concurrent audits of different trees must not share `/tmp/memsweep`.** Worker-numbered detector files (`massif_0.out`, `leak_0.log`) collide and two instances read/write each other's logs. `OUT` is now suffixed with the audited tree name (`/tmp/memsweep_<tree>`); keep that property in any edit, and re-check the CSV for duplicated rows if instances ever overlapped.
- **Header suffix + std detection on new trees**: the source scan globs `*.h` only - add `*.hpp` for hpp trees; the `-std=c++20` heuristic (`jthread|concept|<=>`) misses C++23 features like `std::print` - force `-std=c++23` or builds fail with opaque errors.
- **Long-running programs never fit detector timeouts.** Units that train/serve for minutes-hours: audit a shadow copy of the tree with the loop constant `sed`'ed down (allocation shape stabilizes after iteration 1, so heap data stays representative), and remember killed runs write no valgrind summary - leaks/massif require a real exit. The harness now returns `ru_maxrss` even for TIMEOUT rows, but treat TIMEOUT massif/leak results as absent.
- **Floor-dominated RSS**: if every build peaks at the ~14 MB toolchain floor, peak-RSS mode carries no signal - say so and pivot to massif for differentiation.

## Incidents to design against (2026-08 ml-cpp audit)

- **Concurrent audits share the scratch dir.** `OUT` used to be hardcoded `/tmp/memsweep`; two audits of two trees running at once wipe each other's valgrind logs mid-flight. Symptom triplet: scratch dir found emptied, `"0 newly checked"`-style skips, and `MEMCHECK_FAIL {uid} (OK)` rows — program ran fine (exit 0) but the log file was unlinked between write and `os.path.exists`. Master script now suffixes `OUT` with the tree name (`/tmp/memsweep_<tree>`); keep that property in any edit, and serialize audits that share a container.
- **Aborted host commands leave container orphans.** Killing the host-side `podman exec` does not kill container children: a valgrind kept burning 99% CPU for 30+ minutes. Before any re-run: `podman exec <container> sh -c "ps aux | grep -E 'valgrind|measure_peak' | grep -v grep"` and `kill -9` the tree. Scratch leftovers from orphans also poison the next run.
- **Outputs written in-container are root-owned (uid 524288).** Host `rm`/`sed -w` on `runtime_audit_report/*.csv` fails with Permission denied. Delete via `podman exec <container> rm -f ...`; `sed -i` on *source* files still works (rename only needs a writable directory).
- **Long-running programs need a shadow tree, not a timeout.** Detector modes build at `-O0 -g` and run 15–50× slower (memcheck serializes threads); a program that trains for minutes per run will never fit `TMO_*`. Pattern: copy the unit dirs to a scratch tree, `sed` the loop constant down (`EPOCHS = 2000 → 20`; **3** for MT units under detectors), point the script's `discover()` at the copies. Allocation shape stabilizes at iteration 1, so findings hold; the real repo stays untouched (annotations land in the shadow). Budget against **O0 wall time × 15–50**, not O2.
- **Per-unit `-std` override.** `std_of`'s feature regex misses c++23-only code (`std::print`, deducing this), and the Makefile may say so explicitly — override per unit (a `UNIT_STD` map keyed on unit name) instead of guessing from source regexes.
- **Scan the project's actual header extension.** `MT_RE` ran over `*.h` only; a unit with `std::thread` in a `.hpp` header looks single-threaded, gets pinned, and distorts/hangs. Add the tree's header extension to `all_src` before the MT scan.
- **Resumable-skip trap.** `"0 newly checked"` + instant return = the CSV marks those ids done — including garbage rows appended by an aborted run (duplicated `OK` rows with empty columns). Wipe the CSV (container-side) to force a re-check; never trust partial rows.
- **valgrind writes the leak summary on SIGTERM.** A hand `timeout 500` run that gets killed still yields a usable `LEAK SUMMARY`/`ERROR SUMMARY` — handy for quick one-off checks before a scripted batch.

## Adjudication guide (findings are rarely what they first look like)

- **Leak findings**: check whether the unit is a *deliberate* demo (leak/bug-hunt lessons leak on
  purpose; cycle demos show up as "still reachable" or stay clean if the demo breaks the cycle at
  the end). Only undocumented loss is a real finding. A small definite-lost at exit in teaching
  code is fixed with a cleanup helper (e.g. recursive `free_tree`) plus a comment noting the OS
  would reclaim it anyway.
- **Race findings**: cross-check helgrind vs DRD - agreement means likely real. Known FP classes:
  helgrind does not model `std::atomic` or `std::lock`/`scoped_lock` (reports lock-order
  violations on the deadlock-avoidance pattern that is itself the fix; one error context per loop
  iteration = per-iteration FP or a real unsynchronized counter - read the site). DRD flags
  notify-without-holding-lock (benign when the predicate is mutated under the mutex) and counts
  one error per conflicting access (millions of errors = a deliberate unsynchronized-counter loop).
  Concurrent `std::cout` in demos is a cosmetic data race. `still reachable` at exit (globals,
  iostream buffers) is not a leak.
- **Peak memory**: compare against the toolchain floor; only multi-MB outliers matter. When floor-dominated, the audit's value moves to massif heap shape.
- **Many-thread units blow every valgrind budget.** memcheck/helgrind/DRD serialize threads 10-50x - a 32-worker pool at 20 epochs can exceed a 30-min memcheck timeout. Pragmatic substitutes that keep the audit honest:
  - *Leaks*: structural adjudication - grep the tree for manual `new`/`malloc`/`delete`; pure RAII (`vector`/`unique_ptr`/`shared_ptr`, no manual frees) excludes the loss class without a run. Validate the claim on a sibling RAII unit that does complete.
  - *Races*: **ThreadSanitizer** instead of helgrind/DRD - `g++ -fsanitize=thread` (`dnf install libtsan` in <container>), native speed, minutes not hours. Field result: a 32-worker pool ran 100 full epochs under TSan with 0 warnings and exit 0; treat that as stronger evidence than a timed-out helgrind run. `-O2/-O3`
  almost never change RSS (same allocation shape). Wall time only compares meaningfully for
  unpinned (MT) runs or pinned single-thread runs of the same batch.
- **ASan status RUN_FAIL**: ASan aborts the process on the first error by default (exit 1), TSan
  exits 66 on alerts - a nonzero status IS the detection signal, and error counts live in the CSV
  columns. Recurring benign reports go through `ASAN_OPTIONS=suppressions=` /
  `TSAN_OPTIONS=suppressions=` files rather than source edits.

## Adapting to a new tree

Edit `discover()` (yields bank, unit id, compile dir, include root) and, if ids are per-file
rather than per-dir, the group logic in `units()`. Keep: the run harness, MT deferral, per-worker
unique paths, resumable CSV appends, idempotent annotation prefixes. Smoke-test with
`--only` on 2-3 units (one trivial, one multi-file, one MT) before a full batch.

## Finding -> improvement mapping (what --report encodes)

| Finding | Objective | Advice template |
|---|---|---|
| ASan errors / LSan leaks | safety | ownership semantics: unique_ptr/RAII, bounds-checked access; re-run --san |
| UBSan events | robustness | checked arithmetic / wider types - UB can miscompile with -O2 at any time |
| memcheck definite/indirect lost | robustness | RAII owners; weak_ptr for cycles; document deliberate demos in-source |
| TSan/helgrind/DRD races | safety | mutex/atomic/scoped_lock, message passing; confirm with TSan; deliberate demos must say so in-source |
| runtime outlier (>10x median) | speed | profile hot loop (perf + flamegraph), fix algorithmic complexity before parallelizing |
| -O0 ~= -O2 time | speed | IO/memory-bound: optimizer flags will not help; cut IO volume and allocation churn |
| RSS > median + 4 MB | memory | reserve()/stream in chunks instead of materializing |
| stack frames >= 64 KB | robustness | deep recursion or large locals: iterate, or move buffers to the heap (overflow risk on 2 MB thread stacks) |
| threads observed | speed | verify near-linear scaling; sub-linear = shared-state contention |

## After the batch

- Spot-check one annotation of each kind; `git diff` should show only additive lines.
- Clean compile-in-place leftovers: `find ... -type f -exec file {} + | grep -i ELF | cut -d: -f1 | xargs -r rm`.
- Record counts, outliers, and adjudications in the project ledger; summarize FP classes so the
  next audit starts from this taxonomy.
