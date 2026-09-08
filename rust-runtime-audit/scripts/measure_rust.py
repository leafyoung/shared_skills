#!/usr/bin/env python3
"""Runtime audit harness for Rust programs (cargo workspaces and standalone .rs files).

Modes:
  python3 measure_rust.py            # peak RSS + wall time, debug vs release profiles
                                     # -> runtime_audit_report/peak_memory.csv + "// peak-rss:" annotation
  python3 measure_rust.py --massif   # per-line heap attribution via valgrind massif
                                     # -> runtime_audit_report/peak_memory_lines.csv + "// peak-alloc:"
  python3 measure_rust.py --leaks    # memcheck leak-shape -> runtime_audit_report/leaks.csv + "// leak-suspect:"
  python3 measure_rust.py --races    # ThreadSanitizer (nightly -Zsanitizer=thread) on MT-flagged units
                                     # -> runtime_audit_report/races.csv + "// race-suspect:"

Notes vs the C++ sibling (cpp-runtime-audit):
- one compiler (rustc): the -O0/-O2/-O3 x clang/g++ matrix collapses to debug/release profiles
  (opt-level sweeps possible via RUSTFLAGS="-C opt-level=N" but non-idiomatic).
- helgrind/DRD are deliberately NOT scripted: Rust synchronization lowers to atomics and fences,
  which both tools cannot see -> near-100% false positives on idiomatic Rust. TSan is the dynamic
  race detector of record; loom (exhaustive model checking, test harness) and Miri (UB + races +
  leaks, interpreter, nightly) cover the rest - see SKILL.md.
- standalone .rs units are built with `rustc` (std only); cargo crates with `cargo build`.

Parallel with per-core taskset pinning; MT-flagged units deferred to serial unpinned runs;
resumable CSV appends; idempotent annotation prefixes. Run in a container with the toolchain.
"""
import argparse, csv, glob, os, queue, re, shutil, signal, subprocess, sys, threading, time
from collections import Counter

_here = os.path.dirname(os.path.abspath(__file__))
# script may sit at tree root OR inside runtime_audit_report/ (with the CSVs) - ROOT is the tree either way
ROOT = os.path.dirname(_here) if os.path.basename(_here) == "runtime_audit_report" else _here
OUT = "/tmp/memsweep_" + re.sub(r"\W+", "_", os.path.basename(ROOT))  # per-tree: concurrent audits must not share scratch
REPORTS = os.path.join(ROOT, "runtime_audit_report")

def _ensure_gitignore(root):  # append runtime_audit_report/ to .gitignore when inside a git worktree
    p = root
    while p != os.path.dirname(p) and not os.path.isdir(os.path.join(p, ".git")):
        p = os.path.dirname(p)
    if not os.path.isdir(os.path.join(p, ".git")):
        return
    gi = os.path.join(root, ".gitignore")
    try:
        covered = any("runtime_audit_report" in open(f).read()
                      for f in (gi, os.path.join(p, ".gitignore")) if os.path.exists(f))
        if not covered:
            have = open(gi).read() if os.path.exists(gi) else ""
            with open(gi, "a") as fh:
                if have and not have.endswith("\n"):
                    fh.write("\n")
                fh.write("runtime_audit_report/\n")
    except OSError:
        pass

_ensure_gitignore(ROOT)
TMO_BUILD, TMO_RUN, TMO_TOOL = 300, 180, 1800
DATE = time.strftime("%Y-%m-%d")
NWORK = max(1, min(24, (os.cpu_count() or 4) - 4))
# Rust MT patterns: std threads, scoped threads, async runtimes, rayon/crossbeam, shared-state types
MT_RE = re.compile(r"\bthread::spawn\b|std::thread\b|thread::scope|\.spawn\b|tokio::|async-std|rayon::|crossbeam::"
                   r"|\bArc\b|Mutex|RwLock|mpsc|channel|Condvar|[Aa]tomic")

def log(msg): print(msg, file=sys.stderr, flush=True)

def read(f):
    try:
        return open(f, errors="ignore").read()
    except OSError:
        return ""

def cargo_name(crate_dir):
    m = re.search(r'^name\s*=\s*"([^"]+)"', read(os.path.join(crate_dir, "Cargo.toml")), re.M)
    return m.group(1) if m else os.path.basename(crate_dir)

def crate_root(src):
    """.../crate/src/bin/x.rs -> .../crate ; .../crate/src/main.rs -> .../crate"""
    p = os.path.dirname(src)
    if os.path.basename(p) == "bin":
        p = os.path.dirname(p)
    return os.path.dirname(p)

def discover_cargo():
    """Yield (crate_dir, [(bin_name, source_file)]) for every cargo crate."""
    for toml in sorted(glob.glob(os.path.join(ROOT, "**", "Cargo.toml"), recursive=True)):
        d = os.path.dirname(toml)
        if f"{os.sep}target{os.sep}" in d:
            continue
        bins = []
        sb = os.path.join(d, "src", "bin")
        if os.path.isdir(sb):
            bins += [(os.path.splitext(f)[0], os.path.join(sb, f)) for f in sorted(os.listdir(sb))
                     if f.endswith(".rs")]
        mainrs = os.path.join(d, "src", "main.rs")
        if os.path.isfile(mainrs):
            # an explicit [[bin]] name overrides the default (package-name) binary name
            m2 = re.search(r'\[\[bin\]\][^\[]*?name\s*=\s*"([^"]+)"', read(os.path.join(d, "Cargo.toml")), re.S)
            bins.append((m2.group(1) if m2 else cargo_name(d), mainrs))
        if bins:
            yield d, bins

def discover_rs():
    """Standalone .rs files with fn main (no Cargo.toml in their directory)."""
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.rs"), recursive=True)):
        if f"{os.sep}target{os.sep}" in f:
            continue
        p = os.path.dirname(f)  # skip files inside any cargo crate (Cargo.toml in self or ancestors)
        in_crate = False
        while len(p) >= len(ROOT):
            if os.path.isfile(os.path.join(p, "Cargo.toml")):
                in_crate = True
                break
            p = os.path.dirname(p)
        if in_crate:
            continue
        if re.search(r"\bfn\s+main\b", read(f)):
            yield f

def units(only=None):
    """Yield (bank, uid, bin_name, src_file, datadirs, mt)."""
    seen = set()
    for d, bins in discover_cargo():
        cname = cargo_name(d)
        for name, src in bins:
            uid = name if name == cname else f"{cname}-{name}"
            if only and uid not in only:
                continue
            seen.add(uid)
            yield "cargo", uid, name, src, [d], bool(MT_RE.search(read(src)))
    for f in discover_rs():
        uid = "rs-" + re.sub(r"[^A-Za-z0-9]+", "-", os.path.relpath(f, ROOT)[:-3])
        if only and uid not in only:
            continue
        seen.add(uid)
        yield "rs", uid, os.path.basename(f)[:-3], f, [os.path.dirname(f)], bool(MT_RE.search(read(f)))

def cargo_build(crate_dir, profile, env_extra=None):
    cmd = ["cargo", "build", "--bins"]
    if profile == "release":
        cmd.append("--release")
    # RUSTC_WRAPPER="": fedora cargo defaults to sccache. Release builds additionally need
    # debuginfo=2 + strip=none (cargo release defaults: debuginfo=0 + strip="debuginfo" - without
    # them massif/memcheck see no user-code lines). DEBUG builds must stay PLAIN: empirically,
    # injecting RUSTFLAGS into dev builds produces DWARF valgrind cannot map to lines.
    env = dict(os.environ, CARGO_TARGET_DIR=os.path.join(OUT, "cargo_target", profile), RUSTC_WRAPPER="")
    if profile == "release":
        env["RUSTFLAGS"] = "-C debuginfo=2"
        env["CARGO_PROFILE_RELEASE_STRIP"] = "none"
    env.update(env_extra or {})
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TMO_BUILD, cwd=crate_dir, env=env)
    tdir = os.path.join(env["CARGO_TARGET_DIR"], "release" if profile == "release" else "debug")
    return p.returncode == 0, p.stderr, tdir

def make_bin(u, profile):
    """Build one unit; return (bin_path_or_None, datadirs, err)."""
    bank, uid, name, src, datadirs, mt = u
    tag = re.sub(r"\W+", "_", uid)
    if bank == "cargo":
        ok, err, tdir = cargo_build(crate_root(src), profile)
        binp = os.path.join(tdir, name)
        if ok and os.path.isfile(binp):
            return binp, datadirs, ""
        return None, datadirs, err or f"bin {binp} not found"
    out = os.path.join(OUT, f"bin_{profile}_{tag}")
    flags = ["-C", "opt-level=0", "-C", "debuginfo=2"] if profile == "debug" else \
            ["-C", "opt-level=3", "-C", "debuginfo=2"]
    p = subprocess.run(["rustc", *flags, "-o", out, src], capture_output=True, text=True,
                       timeout=TMO_BUILD, cwd="/")
    return (out if p.returncode == 0 else None), datadirs, p.stderr

def run_peak(argv, datadirs, tmo, pin_cpu=None):
    """Run argv in an isolated dir seeded with data files; return (status, exit, rss_kb, secs, max_threads)."""
    rd = os.path.join(OUT, "run", re.sub(r"\W+", "_", os.path.basename(argv[-1])) + f"_{pin_cpu}")
    shutil.rmtree(rd, ignore_errors=True); os.makedirs(rd)
    # ponytail: data-dep heuristic = copy csv/txt/dat/json/toml from source dirs; extend if a run fails on missing input
    for dd in datadirs:
        for pat in ("*.csv", "*.txt", "*.dat", "*.json", "*.toml"):
            for f in glob.glob(os.path.join(dd, pat)):
                shutil.copy(f, rd, follow_symlinks=True)
    if pin_cpu is not None:
        argv = ["taskset", "-c", str(pin_cpu), *argv]
    t0 = time.time()
    p = subprocess.Popen(argv, cwd=rd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # drain stdout concurrently: pipes here hold only ~8KB, a chatty child would block forever
    threading.Thread(target=p.stdout.read, daemon=True).start()
    max_threads, timed_out = 1, False
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        try:
            max_threads = max(max_threads, len(os.listdir(f"/proc/{p.pid}/task")))
        except OSError:
            pass
        if time.time() - t0 > tmo:
            os.kill(p.pid, signal.SIGKILL)
            pid, status, ru = os.wait4(p.pid, 0)
            timed_out = True
            break
        time.sleep(0.02)
    p.returncode = 0
    p.stdout.close()
    secs = round(time.time() - t0, 2)
    exit_code = os.waitstatus_to_exitcode(status)
    if timed_out:      return "TIMEOUT", -9, ru.ru_maxrss, secs, max_threads  # RSS is valid even for killed runs
    if exit_code != 0: return "RUN_FAIL", exit_code, ru.ru_maxrss, secs, max_threads
    return "OK", exit_code, ru.ru_maxrss, secs, max_threads

def parallel_run(jobs, job, nwork):
    """jobs: list of arg tuples; job(*j) on nwork worker threads; results ordered, never crash the pool."""
    results, q = [None] * len(jobs), queue.Queue()
    for i in range(len(jobs)):
        q.put(i)
    def worker():
        while True:
            try:
                i = q.get_nowait()
            except queue.Empty:
                return
            try:
                results[i] = job(*jobs[i])
            except Exception as e:
                log(f"ERROR job {jobs[i]}: {e}")
    ws = [threading.Thread(target=worker) for _ in range(min(nwork, len(jobs) or 1))]
    for t in ws: t.start()
    for t in ws: t.join()
    return results

def replace_or_append(path, prefix, line):
    if not path:
        return
    text = read(path)
    if prefix in text:
        text = re.sub(rf"^[^\n]*{re.escape(prefix)}[^\n]*\n", line, text, count=1, flags=re.M)
    else:
        text = (text.rstrip("\n") + "\n\n" + line) if text.strip() else line
    with open(path, "w", errors="surrogateescape") as f:
        f.write(text)

def split_mt(unit_list):
    st = [u for u in unit_list if not u[5]]
    mt = [u for u in unit_list if u[5]]
    return st, mt

# ---------------- mode: profiles (default) ----------------

def phase_profiles(only=None):
    unit_list = list(units(only))
    st, mt = split_mt(unit_list)
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {len(mt)})")

    def job(u, cpu):
        bank, uid, name, src, datadirs, mt = u
        kbs, tms, status, exit_code, secs, threads = {}, {}, "OK", 0, 0.0, 1
        for prof in ("debug", "release"):
            binp, dd, err = make_bin(u, prof)
            if binp is None:
                status, exit_code = "BUILD_FAIL", 1
                log(f"BUILD_FAIL {uid} ({prof}): {(err.strip().splitlines() or [err or '?'])[-1]}")
                break
            st2, ec, kb, se, th = run_peak([binp], dd, TMO_RUN, cpu)
            secs, exit_code, threads = max(secs, se), ec, max(threads, th)
            kbs[prof] = kb
            tms[prof] = se
            if st2 != "OK":
                status = st2
                log(f"{st2} {uid} ({prof}) exit={ec}")
                break
        if status == "OK":
            replace_or_append(src, "// peak-rss:",
                              f"// peak-rss: debug {kbs['debug']} KB | release {kbs['release']} KB "
                              f"(max RSS, <container>, {DATE})\n")
        return (bank, uid, src, status, exit_code, threads, "no" if cpu is None else "yes",
                kbs.get("debug"), kbs.get("release"), secs, tms.get("debug", ""), tms.get("release", ""))

    rows = parallel_run([(u, i % NWORK) for i, u in enumerate(st)], job, NWORK)
    rows += [job(u, None) for u in mt]
    rows = [r for r in rows if r]
    if only:
        log("only-mode: CSV not written"); return
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, "peak_memory.csv"), "w") as f:
        f.write("bank,id,source,status,exit_code,threads_max,pinned,peak_rss_kb_debug,peak_rss_kb_release,"
                "run_seconds,time_debug,time_release\n")
        for r in sorted(rows, key=lambda r: (r[0], r[1])):
            f.write(f'{r[0]},{r[1]},"{os.path.relpath(r[2], ROOT) if r[2] else ""}",{r[3]},{r[4] or ""},'
                    f'{r[5]},{r[6]},{r[7] or ""},{r[8] or ""},{r[9]},{r[10] or ""},{r[11] or ""}\n')
    log(f"\nrows: {len(rows)}  statuses: {dict(Counter(r[3] for r in rows))}")

# ---------------- modes: massif / memcheck / tsan ----------------

def run_tool_mode(kind, only=None):
    """massif (release bin) / memcheck (debug bin) / tsan (nightly sanitizer build, MT units only)."""
    path = os.path.join(REPORTS, {"massif": "peak_memory_lines.csv", "memcheck": "leaks.csv",
                                  "tsan": "races.csv"}[kind])
    done = set()
    new_file = not os.path.exists(path)
    if not new_file:
        with open(path) as f:
            done = {r["id"] for r in csv.DictReader(f)}
    unit_list = list(units(only))
    if kind == "tsan":
        probe = os.path.join(OUT, "probe.rs")
        open(probe, "w").write("fn main() {}\n")
        pr = subprocess.run(["rustc", "-Zsanitizer=thread", "-o", probe + ".bin", probe],
                            capture_output=True, text=True)
        if pr.returncode != 0:
            log("TSan unavailable: rustc rejected -Zsanitizer (nightly toolchain required: "
                "rustup toolchain install nightly && rustup default nightly)"); return
        unit_list = [u for u in unit_list if u[5]]
    st, mt = split_mt(unit_list)
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {len(mt)})")
    rows_out, lock = [], threading.Lock()
    hdr = {"massif": ["bank", "id", "file", "line", "heap_kb_inclusive", "peak_heap_kb", "rank"],
           "memcheck": ["bank", "id", "status", "definite_bytes", "definite_blocks", "indirect_bytes",
                        "possible_bytes", "reachable_bytes", "memcheck_errors", "top_site"],
           "tsan": ["bank", "id", "status", "data_races", "first_sites"]}[kind]

    def tool_argv(binp, lg):
        if kind == "massif":
            return ["valgrind", "--tool=massif", f"--massif-out-file={lg}", "--detailed-freq=5", binp]
        if kind == "memcheck":
            return ["valgrind", "--tool=memcheck", "--leak-check=full", "--leak-resolution=high",
                    "--show-leak-kinds=definite,indirect,possible", f"--log-file={lg}", binp]
        return binp  # tsan binary runs directly (runtime linked in)

    def job(u, cpu):
        bank, uid, name, src, datadirs, mt = u
        if uid in done:
            return
        tag = re.sub(r"\W+", "_", uid)
        if kind == "tsan":
            env = {"RUSTFLAGS": "-Zsanitizer=thread -C debuginfo=2"}
            binp, dd, err = make_bin_tsan(u, env)
            if binp is None:
                with lock:
                    rows_out.append((bank, uid, "BUILD_FAIL", "", ""))
                    log(f"BUILD_FAIL {uid} [tsan]: {(err.strip().splitlines() or [err or '?'])[-1]}")
                return
            lg = os.path.join(OUT, f"tsan_{tag}.log")
        else:
            # massif on DEBUG: release inlines user frames away entirely (peak falls inside std),
            # so attribution to your own lines only works unoptimized - verified empirically
            binp, dd, err = make_bin(u, "debug")
            if binp is None:
                with lock:
                    rows_out.append((bank, uid, "BUILD_FAIL"))
                    log(f"BUILD_FAIL {uid}: {(err.strip().splitlines() or [err or '?'])[-1]}")
                return
            lg = os.path.join(OUT, f"{kind}_{tag}.{'out' if kind == 'massif' else 'log'}")
        st, ec, kb, secs, th = run_peak(tool_argv(binp, lg), dd, TMO_TOOL, cpu)
        if not os.path.exists(lg):
            with lock:
                rows_out.append((bank, uid, st or f"{kind.upper()}_FAIL"))
                log(f"{st or kind.upper()+'_FAIL'} {uid}")
            return
        if kind == "massif":
            sites, heap = parse_massif(lg, os.path.basename(src))
            with lock:
                if not sites:
                    rows_out.append((bank, uid, "", "", "", "", "MASSIF_FAIL"))
                else:
                    for b, f, ln in sites[:8]:
                        fr = os.path.relpath(f, ROOT) if os.path.isabs(f) else f
                        rows_out.append((bank, uid, fr, ln, round(b / 1024, 1), round(heap / 1024, 1)))
                    b, f, ln = sites[0]
                    tag2 = f"{os.path.basename(f)}:{ln}" if ROOT in f else "runtime baseline (no user-code heap)"
                    replace_or_append(src, "// peak-alloc:",
                                      f"// peak-alloc: {tag2} {b/1024:.1f} KB incl. "
                                      f"(heap peak {heap/1024:.1f} KB, massif, {DATE})\n")
                log(f"massif {uid}: {len(sites)} sites, peak heap {(heap or 0)/1024:.1f} KB")
        elif kind == "memcheck":
            kinds, errors, top = parse_memcheck(lg, os.path.basename(src))
            d, ind, pos = kinds["definitely lost"], kinds["indirectly lost"], kinds["possibly lost"]
            site = f"{top[0]}:{top[1]}" if top[0] else ""
            with lock:
                rows_out.append((bank, uid, st, d[0], d[1], ind[0], pos[0],
                                 kinds["still reachable"][0], errors, site))
                if d[0] or ind[0] or pos[0] or errors:
                    bits = []
                    if d[0]: bits.append(f"{d[0]} B definitely lost in {d[1]} blocks")
                    if ind[0]: bits.append(f"{ind[0]} B indirectly lost")
                    if pos[0]: bits.append(f"{pos[0]} B possibly lost")
                    if errors: bits.append(f"{errors} memcheck error(s)")
                    replace_or_append(src, "// leak-suspect:",
                                      "// leak-suspect: " + "; ".join(bits) + f" (memcheck, {DATE})\n")
                log(f"memcheck {uid}: lost {d[0]}+{ind[0]}+{pos[0]} B, {errors} errors")
        else:  # tsan
            t = read(lg)
            races = len(re.findall(r"WARNING: ThreadSanitizer: data race", t))
            sites = []
            for fm in re.finditer(r"\((\S+\.rs):(\d+)\)", t):
                fr = fm.group(1) if not os.path.isabs(fm.group(1)) else os.path.relpath(fm.group(1), ROOT)
                if fr not in sites:
                    sites.append(fr)
                if len(sites) == 2:
                    break
            with lock:
                rows_out.append((bank, uid, st, races, " <-> ".join(sites)))
                if races:
                    replace_or_append(src, "// race-suspect:",
                                      f"// race-suspect: {races} TSan data race(s); first: "
                                      f"{' <-> '.join(sites)} (TSan nightly, {DATE})\n")
                log(f"tsan {uid}: {races} races")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="") as fout:
        wtr = csv.writer(fout)
        if new_file:
            wtr.writerow(hdr)
        parallel_run([(u, i % NWORK) for i, u in enumerate(st)], job, NWORK)
        for u in mt:  # MT units: serial, unpinned
            job(u, None)
        for r in rows_out:
            wtr.writerow(r)
    log(f"\n{kind}: done; CSV: {os.path.relpath(path, ROOT)}")

def make_bin_tsan(u, env):
    bank, uid, name, src, datadirs, mt = u
    tag = re.sub(r"\W+", "_", uid)
    out = os.path.join(OUT, f"bin_tsan_{tag}")
    if bank == "cargo":
        host = subprocess.run(["rustup", "run", "nightly", "rustc", "-vV"], capture_output=True, text=True).stdout
        triple = re.search(r"host:\s*(\S+)", host).group(1)
        flags = env.get("RUSTFLAGS", "-C debuginfo=2")
        # documented sanitizer recipe: -Z build-std + --target. --target makes RUSTFLAGS apply to
        # target units only (proc-macro dylibs stay uninstrumented -> loadable), and build-std
        # rebuilds std instrumented (no ABI-mismatch suppression needed). Needs rust-src.
        subprocess.run(["rustup", "component", "add", "rust-src", "--toolchain", "nightly"],
                       capture_output=True, text=True)
        cmd = ["rustup", "run", "nightly", "cargo", "build", "-Z", "build-std",
               "--target", triple, "--bins"]
        env2 = {**os.environ, "CARGO_TARGET_DIR": os.path.join(OUT, "cargo_target_tsan"),
                "RUSTC_WRAPPER": "", "CARGO_PROFILE_RELEASE_STRIP": "none", "RUSTFLAGS": flags}
        # nightly cargo must also find nightly rustc: with the distro cargo first on PATH, cargo's
        # rustc lookup hits /usr/bin/rustc (stable) which rejects -Zsanitizer - prepend nightly bin
        rustup_home = os.environ.get("RUSTUP_HOME", os.path.expanduser("~/.rustup"))
        nb = sorted(glob.glob(os.path.join(rustup_home, "toolchains", "nightly-*", "bin")))
        if nb:
            env2["PATH"] = nb[-1] + os.pathsep + env2["PATH"]
        subdir = os.path.join(triple, "debug")
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TMO_BUILD,
                           cwd=crate_root(src), env=env2)
        binp = os.path.join(env2["CARGO_TARGET_DIR"], subdir, name)
        if p.returncode == 0 and os.path.isfile(binp):
            return binp, datadirs, ""
        return None, datadirs, p.stderr or f"bin {binp} not found"
    p = subprocess.run(["rustc", "-Zsanitizer=thread", "-C", "debuginfo=2", "-o", out, src],
                       capture_output=True, text=True, timeout=TMO_BUILD, cwd="/")
    return (out if p.returncode == 0 else None), datadirs, p.stderr

def parse_massif(logf, prefer_base=None):
    """Per-line heap attribution. Peak snapshot first; tiny programs can peak inside std code
    (no user frames there), so fall back to ALL detailed snapshots (per-line max)."""
    text = read(logf)
    peak_heap, all_sites, peak_sites = None, {}, {}
    for blk in text.split("snapshot="):
        is_peak = "heap_tree=peak" in blk
        if not (is_peak or "heap_tree=detailed" in blk):
            continue
        heap = int(re.search(r"mem_heap_B=(\d+)", blk).group(1))
        if is_peak:
            peak_heap = heap
        for m in re.finditer(r"^\s*n\d+: (\d+) 0x[0-9a-fA-F]+: .* \(([^()]+):(\d+)\)$", blk, re.M):
            b, f, ln = int(m.group(1)), m.group(2), int(m.group(3))
            if f.endswith(".rs"):
                k = (f, ln)
                all_sites[k] = max(all_sites.get(k, 0), b)
                if is_peak:
                    peak_sites[k] = max(peak_sites.get(k, 0), b)
    tosites = lambda d: sorted(((b, f, ln) for (f, ln), b in d.items()), reverse=True)
    sites = tosites(all_sites)
    if prefer_base:
        user = [x for x in sites if os.path.basename(x[1]) == prefer_base]
        if user:
            return user, peak_heap
    return sites, peak_heap

def parse_memcheck(logf, prefer_base=None):
    """top_site prefers frames from prefer_base (the unit's own source file)."""
    text = read(logf)
    kinds = {k: [0, 0] for k in ("definitely lost", "indirectly lost", "possibly lost", "still reachable")}
    for m in re.finditer(r"^==\d+==\s+(definitely lost|indirectly lost|possibly lost|still reachable):"
                         r"\s+([\d,]+) bytes in ([\d,]+) blocks", text, re.M):
        kinds[m.group(1)] = [int(m.group(2).replace(",", "")), int(m.group(3).replace(",", ""))]
    e = re.search(r"^==\d+==\s+ERROR SUMMARY: (\d+) errors", text, re.M)
    frames, preferred = [], None
    for m in re.finditer(r"\((\S+\.rs):(\d+)\)", text):
        fr = (os.path.basename(m.group(1)), int(m.group(2)))
        frames.append(fr)
        if prefer_base and fr[0] == prefer_base and preferred is None:
            preferred = fr
    top = preferred or (frames[0] if frames else ("", 0))
    return kinds, int(e.group(1)) if e else -1, top

def phase_report(only=None):
    """Synthesize CSVs -> runtime_audit_report/IMPROVEMENT_REPORT.md (safety/robustness/speed/memory)."""
    import statistics
    def load(name):
        p = os.path.join(REPORTS, name)
        return list(csv.DictReader(open(p))) if os.path.exists(p) else []
    pm, leaks, races, lines = (load("peak_memory.csv"), load("leaks.csv"),
                               load("races.csv"), load("peak_memory_lines.csv"))
    find = {}
    def add(uid, cat, advice):
        find.setdefault(uid, {}).setdefault(cat, []).append(advice)
    int_ = lambda v: int(v) if str(v).strip().isdigit() else 0
    flo = lambda v: float(v) if str(v).strip() else 0.0

    ok = [r for r in pm if r["status"] == "OK"]
    med_t = statistics.median([flo(r["run_seconds"]) for r in ok if flo(r["run_seconds"]) > 0]) if ok else 0
    med_rss = statistics.median([int_(r["peak_rss_kb_release"]) for r in ok if int_(r["peak_rss_kb_release"])]) if ok else 0
    for r in ok:
        t, rss, th = flo(r["run_seconds"]), int_(r["peak_rss_kb_release"]), int_(r["threads_max"])
        if t > max(5.0, 10 * med_t) and med_t:
            add(r["id"], "speed", f"slowest in bank ({t}s vs median {med_t:.2f}s): profile with "
                "perf/flamegraph; check algorithmic complexity; consider rayon only after that")
        if rss and med_rss and rss > med_rss + 4096:
            add(r["id"], "memory", f"peak RSS {rss} KB is >4 MB above the {med_rss:.0f} KB bank median: "
                "Vec::with_capacity/reserve, stream in chunks instead of materializing")
        if th > 1 and r["pinned"] == "no":
            add(r["id"], "speed", f"multi-threaded ({th} threads): verify near-linear scaling; "
                "shared-counter contention appears as sub-linear speedup")
        td, tr = flo(r.get("time_debug", "")), flo(r.get("time_release", ""))
        if td and tr and td > 0.5 and tr > 0 and td / max(tr, 0.01) < 1.3:
            add(r["id"], "speed", f"debug and release times nearly equal ({td}s vs {tr}s): IO/memory-bound - "
                "optimization flags will not help; reduce IO volume and allocations")
        if int_(r.get("exit_code", "0").replace("-", "")) not in (0,) and r["status"] != "OK":
            pass

    for r in leaks:
        if int_(r["definite_bytes"]) or int_(r["indirect_bytes"]):
            add(r["id"], "robustness", f"memcheck: {r['definite_bytes']} B definite + {r['indirect_bytes']} B "
                f"indirect lost ({r['top_site'] or 'site in CSV'}): drop clone()s that create Rc/Arc cycles "
                "(use Weak), audit mem::forget/Box::leak; if a deliberate demo, document in-source")
        if int_(r["memcheck_errors"]):
            add(r["id"], "safety", f"memcheck: {r['memcheck_errors']} error(s) - invalid reads/writes in "
                "unsafe blocks: audit the unsafe surface, prefer safe abstractions")

    per_unit = {}
    for r in races:
        per_unit.setdefault(r["id"], []).append((int_(r["data_races"]), r["first_sites"]))
    for uid, rs in per_unit.items():
        n = sum(x for x, _ in rs)
        if n:
            sites = next((s for _, s in rs if s), "")
            add(uid, "safety", f"TSan: {n} data race(s) at {sites or 'sites in CSV'}: in safe Rust this means "
                "an unsafe block or a dependency bug - audit the unsafe surface; protect with Mutex/RwLock "
                "or restructure with message passing (mpsc/crossbeam)")

    cats = ("safety", "robustness", "speed", "memory")
    flagged = {u: c for u, c in find.items() if c}
    L = ["# Improvement report - Rust programs", ""]
    L += [f"Generated {DATE}. Objective: benchmark time + peak memory, audit heap/stack safety and "
          f"races, and distill a concrete improvement perspective.", ""]
    L += ["## Summary", "", f"- units profiled: {len(ok)} OK / {sum(1 for r in pm if r['status'] != 'OK')} with issues",
          f"- flagged units: {len(flagged)}"]
    for c in cats:
        L += [f"- {c}: {sum(1 for u in flagged.values() if c in u)} unit(s) with findings"]
    L += [""]
    for c in cats:
        L += [f"## {c.capitalize()}", ""]
        any_c = False
        for uid in sorted(flagged):
            if c in flagged[uid]:
                any_c = True
                for a in flagged[uid][c]:
                    L += [f"- **{uid}**: {a}"]
        if not any_c:
            L += ["- no findings"]
        L += [""]
    clean = sorted(set(r["id"] for r in ok) - set(flagged))
    L += ["## Clean units", "", f"{len(clean)} unit(s) with no findings.", ""]
    os.makedirs(REPORTS, exist_ok=True)
    open(os.path.join(REPORTS, "IMPROVEMENT_REPORT.md"), "w").write("\n".join(L) + "\n")
    log(f"report: {len(flagged)} flagged of {len(ok)} OK units")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--massif", action="store_true", help="per-line heap attribution")
    ap.add_argument("--leaks", action="store_true", help="memcheck leak-shape")
    ap.add_argument("--races", action="store_true", help="TSan on MT-flagged units (needs nightly)")
    ap.add_argument("--report", action="store_true", help="synthesize CSVs into IMPROVEMENT_REPORT.md")
    ap.add_argument("--only", help="comma-separated unit ids (debug)")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    if a.report:
        phase_report(only)
    elif a.races:
        run_tool_mode("tsan", only)
    elif a.leaks:
        run_tool_mode("memcheck", only)
    elif a.massif:
        run_tool_mode("massif", only)
    else:
        phase_profiles(only)
