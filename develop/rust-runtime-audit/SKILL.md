---
name: rust-runtime-audit
description: This skill should be used when the user asks to benchmark, profile, or audit compiled Rust programs or Rust solution/exercise banks - measuring peak memory (max RSS) and wall time across debug/release profiles, per-line heap attribution (valgrind massif), leak detection (memcheck, or Miri/LSan), or data-race detection (TSan via nightly -Zsanitizer, loom, Miri), including parallel runs with per-core pinning (taskset) and multi-thread detection. Triggers include "benchmark Rust programs", "measure peak memory / RSS of Rust", "Rust memory profiling", "valgrind on Rust", "massif", "leak check Rust", "TSan", "race detection Rust", "loom", "miri", "profile rust binaries".
---

# Rust Runtime Audit

**Objective**: benchmark time and peak memory first, then expand into heap/stack-safety checks and
race detection - and synthesize everything into a concrete improvement perspective for the sources
(safety, robustness, speed, memory).

Audit Rust executables - the Rust sibling of `cpp-runtime-audit`, with the tool choices the Rust
ecosystem actually uses. The bundled
`scripts/measure_rust.py` implements the automatable pipeline; adjudication and the tools that
need per-project wiring (loom tests, criterion benches) are documented here.

## Tool map (what research + practice say to use, per goal)

| Goal | Use | Why |
|---|---|---|
| Peak RSS + wall time of executables | bundled harness (`os.wait4` per-child max RSS) | hyperfine (the CLI benchmarking standard) gives statistics but no per-child RSS |
| In-process function benchmarks | `criterion` / `cargo bench` | statistical, regression-sensitive; needs test wiring, not automatable blindly |
| Heap shape / allocation sites | `valgrind --tool=massif` (bundled), `dhat`, `heaptrack`, `bytehound` | massif works on stock binaries with `-C debuginfo=2`; dhat-rs gives exact in-process counts |
| Leaks | memcheck (bundled); Miri; `-Zsanitizer=leak` (nightly) | safe Rust leaks only via `mem::forget`, `Rc`/`Arc` cycles, intentional `Box::leak`, FFI |
| UB (unsafe code) | **Miri** (nightly interpreter), `cargo-careful` | definitive; slow; pure-Rust syscalls only |
| Data races | **TSan** (`RUSTFLAGS="-Zsanitizer=thread" cargo +nightly ...`), **loom** (exhaustive, small tests), Miri | TSan understands LLVM atomics -> far fewer FPs; loom enumerates interleavings; Miri detects races on observed schedules |
| helgrind / DRD | **not scripted, use only as last-resort cross-check** | they see pthread but not atomic/fence ordering - idiomatic Rust sync is all atomics, so near-100% FP rate |

## Prerequisites

Run inside a distrobox/podman container (repo at same path). <container> is known-good:

```bash
podman exec <container> dnf install -y rust cargo valgrind   # rustc 1.95, valgrind 3.26 verified
podman exec <container> bash -lc 'rustup toolchain install nightly'   # needed only for TSan/Miri
```

`/tmp` is the container's own tmpfs (NOT shared with the host): scratch in `/tmp/memsweep` is
invisible to the host and wiped per invocation; all durable artifacts go to
`runtime_audit_report/` in the audited tree (shared via $HOME).

## Modes

Copy `scripts/measure_rust.py` into `<tree>/runtime_audit_report/` (the same dir that receives the
CSVs; the script detects it sits inside `runtime_audit_report` and audits the tree above), then:

Inside a git repo the script appends `runtime_audit_report/` to the tree's `.gitignore` itself, so the
script and all artifacts never dirty `git status`.

| command | measures | artifact | annotation |
|---|---|---|---|
| `measure_rust.py` | peak RSS + wall time, debug vs release | `runtime_audit_report/peak_memory.csv` | `// peak-rss:` |
| `... --massif` | heap lines at peak (DEBUG build: release inlines user frames away entirely) | `runtime_audit_report/peak_memory_lines.csv` | `// peak-alloc:` |
| `... --leaks` | memcheck leak kinds + errors (debug build) | `runtime_audit_report/leaks.csv` | `// leak-suspect:` (only when flagged) |
| `... --races` | TSan data races, MT-flagged units only | `runtime_audit_report/races.csv` | `// race-suspect:` (only when races) |
| `... --report` | synthesize all CSVs into per-unit improvement advice | `runtime_audit_report/IMPROVEMENT_REPORT.md` | none |

`peak_memory.csv` also records debug vs release wall times - the debug/release ratio separates
compute-bound units (ship release) from IO/memory-bound ones (redesign, don't recompile).

Common: `--only ID1,ID2` (debug; refuses to rewrite full CSV), resumable appends, idempotent
annotation prefixes, 24 workers each pinned via `taskset` to its own core, MT-flagged units run
serially unpinned last, runtime `/proc/<pid>/task` thread counting.

## Unit discovery (adapt `units()`/`discover_cargo()` for new layouts)

- cargo crates (any `Cargo.toml` under the tree): bins from `src/main.rs` (id = package name) and
  `src/bin/*.rs` (id = `pkg-bin`); built via `cargo build --bins [--release]` with
  `CARGO_TARGET_DIR` pointed at scratch (keeps the repo clean).
- standalone `.rs` files with `fn main` not inside any crate: built with
  `rustc -C opt-level=0/-3 -C debuginfo=2`.
- MT static flag: `\bthread::spawn\b|std::thread\b|thread::scope|\.spawn\b|tokio::|async-std|rayon::|crossbeam::|\bArc\b|Mutex|RwLock|mpsc|channel|Condvar|[Aa]tomic`.

Run harness rules that must survive any edit: drain child stdout in a thread (pipes here hold
~8 KB - undrained children deadlock into fake TIMEOUTs); per-child RSS via `os.wait4(WNOHANG)`
polling (never `RUSAGE_CHILDREN` - cumulative max); fresh seeded run dir per program
(`*.csv *.txt *.dat *.json *.toml` copied in); `RUSTC_WRAPPER=""` (fedora cargo defaults to
sccache, which may not be installed).

## Rust-specific interpretation notes

- **massif frames use basename-only paths for the local crate** (`leaky.rs:5`) while libstd
  frames use `library/std/src/...` paths - filter top sites to the unit's own source basename
  before ranking, or libstd internals drown out user lines. Inclusive bytes tie across the whole
  allocation chain; rank by (own-file first, then bytes).
- **memcheck**: `Box::leak()` output that is still referenced at exit reports as "still
  reachable", not lost - that is correct semantics, don't "fix" it. `Rc`/`RefCell` cycles report
  as definite (one node) + indirect (the rest) lost, exactly like C++ shared_ptr cycles.
- **TSan**: build with `RUSTFLAGS="-Zsanitizer=thread -C debuginfo=2"` under nightly
  (`cargo +nightly build`; standalone: `rustc -Zsanitizer=thread -g`). Probe the toolchain first
  (`rustc -Zsanitizer=thread` on a one-liner) - stable rustc silently ignores `+nightly` and then
  fails with "the option `Z` is only accepted on the nightly compiler". TSan binaries run
  directly (runtime is linked in). Data-race warnings in safe-Rust code mean an `unsafe` block or
  a dependency bug - take them seriously.
- **Benchmark hygiene**: wall time from a pinned single-thread run is comparable within a batch;
  MT/async units run unpinned serially. For publishable numbers use hyperfine
  (`hyperfine 'target/release/bin' --warmup 3`) or criterion; never quote single-run wall times.
- **Miri/loom are test-wiring tools**: `cargo +nightly miri test` and loom's model-checking
  harness need `#[test]`s - recommend them in the report for concurrent *libraries*, but they
  cannot be blind-swept over arbitrary executables.

## Finding -> improvement mapping (what --report encodes)

| Finding | Objective | Advice template |
|---|---|---|
| TSan data races in safe code | safety | an unsafe block or dependency bug - audit the unsafe surface; Mutex/RwLock or message passing (mpsc/crossbeam) |
| memcheck definite/indirect lost | robustness | Rc/Arc cycles -> Weak; audit mem::forget/Box::leak; document deliberate demos in-source |
| memcheck invalid reads/writes | safety | audit unsafe blocks; prefer safe abstractions |
| runtime outlier (>10x median) | speed | perf/flamegraph, algorithmic complexity first; rayon only after |
| RSS > median + 4 MB | memory | Vec::with_capacity/reserve; stream in chunks instead of materializing |
| debug ~= release time | speed | IO/memory-bound: flags will not help; redesign the data flow |
| threads observed | speed | verify near-linear scaling; sub-linear = contention |

Stack-usage for Rust: nightly `-Z emit-stack-sizes` (per-function, at codegen) - document for
units with deep recursion; spawned threads default to 2 MB stacks vs 8 MB for main.

## Massif attribution notes (hard-won)

- cargo release profiles default to `debuginfo=0` AND `strip="debuginfo"`: user-code frames
  vanish entirely. massif therefore runs on the DEBUG build; release stays for RSS/time.
- Tiny programs peak inside std (stdout buffer alloc): the peak snapshot may contain no
  user-code frames. The parser falls back to per-line maxima across ALL detailed snapshots.
- Top sites prefer the unit's own source basename; libstd frames (`library/...`, `alloc.rs`,
  `rt.rs`, `stack_overflow.rs`) are the allocation machinery, not your bug.

## After the batch

- Verify annotations: `git diff` must show only additive comment lines; `// peak-rss:` in every
  unit's entry source, `// peak-alloc:` / `// leak-suspect:` / `// race-suspect:` only where
  flagged.
- Adjudicate before reporting: intentional `Box::leak`/cycle demos in teaching code are not
  defects - note them as deliberate. Safe-Rust race warnings are dependency/unsafe bugs - highest
  priority. Compare RSS against the ~13.5 MB toolchain floor; only multi-MB outliers matter.
- Record tool versions (rustc, valgrind), counts, and adjudications in the project ledger.

## Operational incidents to design against (2026-08 concurrent-audit session)

- **Concurrent audits share the scratch dir.** Two audits of two trees running at once wipe each other's detector logs mid-flight. Symptom triplet: scratch dir found emptied, `"0 newly checked"`-style skips, and rows where the program ran fine but every result column is empty (log unlinked between write and existence check). `OUT` is now suffixed with the tree name (`/tmp/memsweep_<tree>`); keep that property in any edit, and serialize audits sharing a container.
- **Aborted host commands leave container orphans.** Killing the host-side `podman exec` does not kill container children — a detector kept 99% CPU for 30+ minutes. Before re-running: `podman exec <container> sh -c "ps aux | grep -E 'valgrind|measure_rust' | grep -v grep"`, `kill -9` the tree, and wipe its scratch leftovers.
- **Durable artifacts written in-container are root-owned.** Host `rm` on `runtime_audit_report/*.csv` fails with Permission denied — delete via `podman exec <container> rm -f ...` (or `chown`); `sed -i` on source files still works (rename needs only a writable directory).
- **Long-running programs need a shadow tree.** Detectors run 10–50× slower (TSan worst with real threading); a unit whose native run takes minutes will never fit a detector timeout. Copy unit dirs to a scratch tree, `sed` the loop/iteration constant down (full budget → ~20; ~3 for MT units under detectors), point `discover_cargo()`/`units()` at the copies. Allocation shape stabilizes at iteration 1; the real repo stays untouched and annotations land in the shadow.
- **Resumable-skip trap.** `"0 newly checked"` + instant return = the CSV marks those ids done — including garbage rows appended by an aborted run. Wipe the CSV (container-side) to force a re-check.
- **Never `pkill -f <script-name>`.** It matches your own `podman exec sh -c "..."` wrapper — you SIGKILL your own shell (exit 137) and the detector children survive anyway. Kill by explicit PID list from `ps`, identifying ownership by tree path first (a PPID-0 detached run may be another session's audit).
- **The harness drops RSS on TIMEOUT.** `run_peak` returned `None` for killed runs — patched to return `ru_maxrss` (RSS is valid at SIGKILL). Note the asymmetry: killed *peak* runs still yield RSS, but killed memcheck/massif runs write no summary — cap iterations (shadow tree) instead of relying on timeouts.
