#!/usr/bin/env python3
"""Peak-memory + timing tooling for the FN6805/6 solution bank (incl. openbook_quiz).

Modes:
  python3 measure_peak_rss.py            # peak RSS + wall time at -O0/-O2/-O3 for clang++ (primary)
                                         # and g++ -> peak_memory.csv + "// peak-rss:" annotation
  python3 measure_peak_rss.py --massif   # per-line heap attribution via valgrind massif (clang++ -g)
                                         # -> peak_memory_lines.csv + "// peak-alloc:" annotation
  python3 measure_peak_rss.py --leaks    # leak-shape analysis via valgrind memcheck leak records
                                         # -> leaks.csv + "// leak-suspect:" annotation where lost > 0
  python3 measure_peak_rss.py --races    # helgrind + DRD on the MT-flagged units (unpinned, 6-way)
                                         # -> races.csv + "// race-suspect:" annotation where errors > 0
  python3 measure_peak_rss.py --san     # ASan+UBSan+LSan with hardened stdlib (fast, ~2x) -> sanitizers.csv
  python3 measure_peak_rss.py --tsan    # ThreadSanitizer (-O1 -g, understands atomics) on MT units -> races.csv

Parallelism: single-threaded units run N-at-a-time, each pinned to its own core via taskset.
Units whose sources reference threads (std::thread/jthread/async/pthread/future/promise/omp)
are detected, deferred, and run serially UNPINNED at the end (MT-on-one-core distorts timing).
A runtime /proc/<pid>/task counter double-checks thread usage.

Run INSIDE the box2 distrobox container (podman exec box2 python3 <script> ...):
same compilers + valgrind for all measurements; repo visible at identical path.
Re-runs are idempotent: annotation lines are replaced by prefix, binaries stay in /tmp.
"""
import argparse, csv, glob, os, queue, re, shutil, signal, subprocess, sys, threading, time
from pathlib import Path
from collections import Counter

_here = os.path.dirname(os.path.abspath(__file__))
# script may sit at tree root OR inside runtime_audit_report/ (with the CSVs) - ROOT is the tree either way
ROOT = os.path.dirname(_here) if os.path.basename(_here) == "runtime_audit_report" else _here
OUT = "/tmp/memsweep_" + re.sub(r"\W+", "_", os.path.basename(ROOT))  # per-tree: concurrent audits must not share scratch
CSV = os.path.join(ROOT, "runtime_audit_report", "peak_memory.csv")
LEAKS_CSV = os.path.join(ROOT, "runtime_audit_report", "leaks.csv")
RACES_CSV = os.path.join(ROOT, "runtime_audit_report", "races.csv")
SAN_CSV = os.path.join(ROOT, "runtime_audit_report", "sanitizers.csv")
NW_RACE = 6  # MT programs under race detectors: moderate concurrency, no pinning
LINES_CSV = os.path.join(ROOT, "runtime_audit_report", "peak_memory_lines.csv")

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
TMO_BUILD, TMO_RUN, TMO_MASSIF, TMO_LEAKS, TMO_RACE, TMO_SAN = 120, 180, 900, 1800, 3600, 600
DATE = time.strftime("%Y-%m-%d")
OPTS = ("O0", "O2", "O3")
CXXS = ("clang++", "g++")  # clang++ primary (massif + annotation), g++ kept for comparison
NWORK = max(1, min(24, (os.cpu_count() or 4) - 4))
MT_RE = re.compile(r"\bstd::thread\b|\bjthread\b|std::async|pthread_create|std::future\b|std::promise\b|#pragma omp|parallel_for")

def log(msg): print(msg, file=sys.stderr, flush=True)

def read(f):
    try:
        return open(f, errors="ignore").read()
    except OSError:
        return ""

def discover():
    """Yield (bank, unit_id_or_None, compile_dir, include_root)."""
    for bank in ("quiz_s", "question_s", "ex_s", "openbook_quiz"):
        if bank == "openbook_quiz":
            for d in sorted(glob.glob(os.path.join(ROOT, "openbook_quiz", "fn*", "solutions"))):
                yield "openbook", None, d, d
            continue
        dirs = set(glob.glob(os.path.join(ROOT, bank, "**", "*_solution*"), recursive=True))
        dirs |= set(glob.glob(os.path.join(ROOT, bank, "**", "cpp"), recursive=True))
        for d in sorted(x for x in dirs if os.path.isdir(x)):
            rel = os.path.relpath(d, ROOT)
            if bank == "quiz_s":
                yield bank, None, d, os.path.dirname(d)
            elif bank == "question_s":
                m = re.search(r"Q(\d+)_\w+_solution", rel)
                yield bank, f"QS-Q{int(m.group(1)):02d}" if m else None, d, os.path.dirname(d)
            else:
                m = re.search(r"ex_week(\d+)/q(\d+)_solution$", rel)
                yield bank, f"EX-W{int(m.group(1)):02d}-Q{int(m.group(2)):02d}" if m else None, d, os.path.dirname(d)

def ob_id(cpp):
    m = re.search(r"fn(\d+)/solutions/q(\d+)_solution\.cpp$", cpp)
    return f"OB{m.group(1)[-1]}-Q{int(m.group(2)):02d}" if m else None

def build(cpps, root, std, out, extra=(), cxx="clang++", cwd=None, su_dir=None):
    inc = ["-I" + root] + (["-I" + os.path.join(root, "h")] if os.path.isdir(os.path.join(root, "h")) else [])
    if su_dir:  # -fstack-usage drops <file>.su into the compilation cwd
        extra = [*extra, "-fstack-usage"]
        os.makedirs(su_dir, exist_ok=True)
    cmd = [cxx, f"-std={std}", "-Wall", "-Wextra", "-pthread", *inc, *extra, "-o", out, *cpps]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TMO_BUILD, cwd=su_dir or "/")
    return p.returncode == 0, p.stderr

def run_peak(argv, datadirs, tmo, pin_cpu=None, env=None):
    """Run argv in an isolated dir seeded with data files; return (status, exit, rss_kb, secs, max_threads)."""
    rd = os.path.join(OUT, "run", re.sub(r"\W+", "_", os.path.basename(argv[-1])) + f"_{pin_cpu}")
    shutil.rmtree(rd, ignore_errors=True); os.makedirs(rd)
    # ponytail: data-dep heuristic = copy csv/txt/dat from solution dirs; extend if a run fails on missing input
    for dd in datadirs:
        for pat in ("*.csv", "*.txt", "*.dat"):
            for f in glob.glob(os.path.join(dd, pat)):
                shutil.copy(f, rd, follow_symlinks=True)
    if pin_cpu is not None:
        argv = ["taskset", "-c", str(pin_cpu), *argv]
    t0 = time.time()
    p = subprocess.Popen(argv, cwd=rd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=({**os.environ, **env} if env else None))
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
    p.returncode = 0  # already reaped via wait4; stop Popen from re-waiting
    p.stdout.close()
    secs = round(time.time() - t0, 2)
    exit_code = os.waitstatus_to_exitcode(status)
    if timed_out:      return "TIMEOUT", -9, ru.ru_maxrss, secs, max_threads  # RSS is valid even for killed runs
    if exit_code != 0: return "RUN_FAIL", exit_code, ru.ru_maxrss, secs, max_threads
    return "OK", exit_code, ru.ru_maxrss, secs, max_threads

def qz_id(cpp):
    m = re.search(r"q(\d+)_solution\.cpp$", cpp)
    return f"QZ-Q{int(m.group(1)):02d}" if m else None

def units(only=None):
    """Yield (bank, uid, d, root, std, srcs, main_src_or_None, mt, err) with build grouping resolved."""
    for bank, uid, d, root in discover():
        cpps = sorted(glob.glob(os.path.join(d, "*.cpp")))
        if not cpps:
            continue
        if bank == "openbook":
            groups = [(ob_id(c), [c]) for c in cpps]
        elif bank == "quiz_s":
            groups = [(qz_id(c), [c]) for c in cpps]
        elif len(cpps) == 1:
            groups = [(uid, cpps)]
        else:
            ok, err = build(cpps, root, std_of(cpps, root), os.path.join(OUT, "probe"), (), "g++")
            if ok:
                groups = [(uid, cpps)]
            elif "multiple definition" in err:
                groups = [(f"{uid}#{os.path.basename(c)[:-4]}", [c]) for c in cpps]
            else:
                log(f"BUILD_FAIL {uid}")
                yield bank, uid, d, root, std_of(cpps, root), cpps, None, False, "BUILD_FAIL"
                continue
        for u, srcs in groups:
            if only and u not in only:
                continue
            if uid is None and bank not in ("quiz_s", "openbook"):
                log(f"NO_ID {d}"); continue
            all_src = srcs + sorted(glob.glob(os.path.join(d, "*.h"))) + \
                sorted(glob.glob(os.path.join(root, "h", "*.h")))
            std = std_of(all_src, root)
            mt = any(MT_RE.search(read(f)) for f in all_src)
            if len(srcs) > 1:
                mains = [c for c in srcs if re.search(r"\bint\s+main\s*\(", read(c))]
                ms = mains[0] if mains else None
                yield bank, u, d, root, std, srcs, ms, mt, None if ms else "NO_MAIN"
            else:
                ms = srcs[0]
                ok = re.search(r"\bint\s+main\s*\(", read(ms))
                yield bank, u, d, root, std, srcs, ms if ok else None, mt, None if ok else "NO_MAIN"

def std_of(files, root):
    files = list(files)
    if os.path.isdir(os.path.join(root, "h")):
        files += sorted(glob.glob(os.path.join(root, "h", "*.h")))
    return "c++20" if any(re.search(r"jthread|concept |co_await|operator<=>|<=>", read(f)) for f in files) else "c++17"

def replace_or_append(path, prefix, line):
    rp = Path(path).resolve()
    if not rp.is_relative_to(Path(ROOT).resolve()):
        sys.exit(f"error: path escapes audit root: {path}")
    text = read(path)
    if prefix in text:
        text = re.sub(rf"^[^\n]*{re.escape(prefix)}[^\n]*\n", line, text, count=1, flags=re.M)
    else:
        text = (text.rstrip("\n") + "\n\n" + line) if text.strip() else line
    rp.write_text(text, errors="surrogateescape")

def parallel_run(units_list, job, cpus):
    """Run job(unit, cpu_or_None) over units; single-cpu-pinned workers for non-MT, MT serial unpinned last."""
    results = []
    mt = [u for u in units_list if u[7]]
    st = [u for u in units_list if not u[7]]
    q = queue.Queue()
    for u in st:
        q.put(u)
    def worker(cpu):
        while True:
            try:
                u = q.get_nowait()
            except queue.Empty:
                return
            try:
                r = job(u, cpu)
            except Exception as e:
                r = (u[0], u[1], u[2], u[6], u[4], "ERROR", "", "", 0, "yes", "", "", "", "", "", "", "")
                log(f"ERROR {u[1]}: {e}")
            with lock:
                results.append(r)
    lock = threading.Lock()
    ws = [threading.Thread(target=worker, args=(cpus[i],)) for i in range(min(len(cpus), len(st) or 1))]
    for t in ws: t.start()
    for t in ws: t.join()
    for u in mt:  # multi-threaded: serial, unpinned
        r = job(u, None)
        with lock:
            results.append(r)
    return results

def parse_su(su_dir):
    """Parse gcc/clang -fstack-usage .su files -> (max_frame, sum_frames) bytes."""
    mx = sm = 0
    for f in glob.glob(os.path.join(su_dir, "*.su")):
        for line in read(f).splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1].isdigit():
                b = int(parts[1]); mx = max(mx, b); sm += b
    return mx, sm

def measure_all(srcs, root, std, d, uid, pin_cpu):
    """Build+run one unit for both compilers x OPTS.
    -> (res, times, status, clang_status, exit, secs, threads, stack_max, stack_sum)"""
    res, times, secs, exit_code, threads = {c: {} for c in CXXS}, {c: {} for c in CXXS}, 0.0, 0, 1
    tag = re.sub(r"\W+", "_", str(uid))
    su_dir = os.path.join(OUT, f"su_{tag}")
    stack_max = stack_sum = 0
    for cxx in CXXS:
        for opt in OPTS:
            out = os.path.join(OUT, f"bin_{tag}_{cxx}_{opt}")
            with_su = cxx == "g++" and opt == "O0"  # -fstack-usage once (stable format, cheap)
            ok, berr = build(srcs, root, std, out, [f"-{opt}"], cxx, su_dir=su_dir if with_su else None)
            if not ok:
                log(f"BUILD_FAIL {uid} ({cxx} {opt}): {(berr.strip().splitlines() or ['?'])[-1]}")
                break
            st, ec, kb, se, th = run_peak([out], [d, root], TMO_RUN, pin_cpu)
            secs, exit_code, threads = max(secs, se), ec, max(threads, th)
            times[cxx][opt] = se
            res[cxx][opt] = kb
            if st != "OK":
                log(f"{st} {uid} ({cxx} {opt}) exit={ec}")
                break
    if os.path.isdir(su_dir):
        stack_max, stack_sum = parse_su(su_dir)
    status_of = lambda cxx: "OK" if len(res[cxx]) == len(OPTS) and all(res[cxx].values()) else (
        "BUILD_FAIL" if len(res[cxx]) < len(OPTS) else "RUN_FAIL")
    return res, times, status_of(CXXS[0]), status_of(CXXS[1]), exit_code, secs, threads, stack_max, stack_sum

def phase_opts(only=None):
    """Peak RSS + time at -O0/-O2/-O3 (clang++ + g++) -> peak_memory.csv + peak-rss annotation."""
    rows = []
    unit_list = list(units(only))
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {sum(1 for u in unit_list if u[7])})")

    def job(u, cpu):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        if err:
            return (bank, uid, d, main_src, std, err, "", "", 0, "n/a", "", "", "", "", "", "", 0, 0, "", "", "")
        res, times, status, clang_status, exit_code, secs, threads, stack_max, stack_sum = \
            measure_all(srcs, root, std, d, uid, cpu)
        if status == "OK" and clang_status == "OK" and main_src:
            line = "// peak-rss: " + " | ".join(
                f"{cxx} " + "/".join(f"{o} {res[cxx][o]}" for o in OPTS) + " KB" for cxx in CXXS
            ) + f" (max RSS, box2, {DATE})\n"
            replace_or_append(main_src, "// peak-rss:", line)
        tc = times.get("clang++", {})
        return (bank, uid, d, main_src, std, status, clang_status, exit_code, threads,
                "no" if cpu is None else "yes",
                res["g++"].get("O0"), res["g++"].get("O2"), res["g++"].get("O3"),
                res["clang++"].get("O0"), res["clang++"].get("O2"), res["clang++"].get("O3"), secs,
                stack_max, stack_sum, tc.get("O0", ""), tc.get("O2", ""), tc.get("O3", ""))

    rows = parallel_run(unit_list, job, list(range(NWORK)))
    # runtime-MT: static filter passed but threads appeared while pinned -> re-run unpinned for honest timing
    umap = {u[1]: u for u in unit_list}
    for i, r in enumerate(rows):
        if r[9] == "yes" and isinstance(r[8], int) and r[8] > 1 and r[1] in umap:
            log(f"runtime-MT {r[1]} (threads={r[8]}): re-running unpinned")
            rows[i] = job(umap[r[1]], None)
    q01 = os.path.join(ROOT, "question_s/bond_calculations/Q01_bond_bug_hunt_solution")
    if (not any(r[1] == "QS-Q01" for r in rows)) and os.path.isdir(q01):  # FN6805-specific prose-only unit
        rows.append(("question_s", "QS-Q01", q01,
                     None, "n/a", "NO_SOURCE", "", "", 0, "n/a", "", "", "", "", "", "", "", 0, 0, "", "", ""))
    if only:  # debug mode: don't clobber the full CSV
        log("only-mode: CSV not written"); return
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    csv_p = Path(CSV).resolve()
    if not csv_p.is_relative_to(Path(ROOT).resolve()):
        sys.exit(f"error: csv path escapes audit root: {CSV}")
    with csv_p.open("w") as f:
        f.write("bank,id,compile_dir,source,std,status,clang_status,exit_code,threads_max,pinned,"
                "peak_rss_kb_gcc_O0,peak_rss_kb_gcc_O2,peak_rss_kb_gcc_O3,"
                "peak_rss_kb_clang_O0,peak_rss_kb_clang_O2,peak_rss_kb_clang_O3,run_seconds,"
                "stack_max_bytes,stack_sum_bytes,time_o0_clang,time_o2_clang,time_o3_clang\n")
        for r in sorted(rows, key=lambda r: (r[0], r[1] or "")):
            f.write(f'{r[0]},{r[1]},"{os.path.relpath(r[2], ROOT)}","{os.path.relpath(r[3], ROOT) if r[3] else ""}",'
                    f'{r[4]},{r[5]},{r[6]},{r[7] or ""},{r[8]},{r[9]},'
                    f'{r[10] or ""},{r[11] or ""},{r[12] or ""},{r[13] or ""},{r[14] or ""},{r[15] or ""},{r[16]},'
                    f'{r[17]},{r[18]},{r[19] or ""},{r[20] or ""},{r[21] or ""}\n')
    log(f"\nrows: {len(rows)}  g++ statuses: {dict(Counter(r[5] for r in rows))}  "
        f"clang statuses: {dict(Counter(r[6] for r in rows))}")
    log(f"CSV: {os.path.relpath(CSV, ROOT)}")

def parse_massif(path):
    """Return (top_sites[(bytes,file,line),...], peak_heap_bytes) from a massif-out file.
    Peak snapshot first; tiny programs can peak inside std code (no user frames there),
    so fall back to ALL detailed snapshots (per-line max across snapshots)."""
    text = read(path)
    peak_heap, all_sites, peak_sites = None, {}, {}
    for blk in text.split("snapshot="):
        is_peak = "heap_tree=peak" in blk
        if not (is_peak or "heap_tree=detailed" in blk):
            continue
        heap = int(re.search(r"mem_heap_B=(\d+)", blk).group(1))
        if is_peak:
            peak_heap = heap
        # frame: " n1: BYTES 0xADDR: FUNC (path/file.cpp:LINE)" - library frames say "(in /lib...)"
        for m in re.finditer(r"^\s*n\d+: (\d+) 0x[0-9a-fA-F]+: .* \(([^()]+):(\d+)\)$", blk, re.M):
            b, f, ln = int(m.group(1)), m.group(2), int(m.group(3))
            k = (f, ln)
            all_sites[k] = max(all_sites.get(k, 0), b)  # inclusive bytes per line
            if is_peak:
                peak_sites[k] = max(peak_sites.get(k, 0), b)
    tosites = lambda d: sorted(((b, f, ln) for (f, ln), b in d.items()), reverse=True)
    user = [x for x in tosites(all_sites) if x[1].startswith(os.sep) and ROOT in x[1]]
    return (user or tosites(peak_sites) or tosites(all_sites)), peak_heap
    return [], None

def phase_massif(only=None):
    os.makedirs(os.path.dirname(LINES_CSV), exist_ok=True)
    """valgrind massif per-line attribution -> peak_memory_lines.csv (parallel, incremental)."""
    done = set()
    new_file = not os.path.exists(LINES_CSV)
    if not new_file:
        with open(LINES_CSV) as f:
            done = {r["id"] for r in csv.DictReader(f)}
    n = [0]
    fout = open(LINES_CSV, "a", newline="")
    w = csv.writer(fout)
    wl = threading.Lock()
    if new_file:
        w.writerow(["bank", "id", "file", "line", "heap_kb_inclusive", "peak_heap_kb", "rank"])

    def job(u, cpu):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        if uid in done:
            return
        if err:
            with wl:
                w.writerow([bank, uid, "", "", "", "", err]); fout.flush()
            return
        out_bin = os.path.join(OUT, f"bin_g_{cpu}")
        mf = os.path.join(OUT, f"massif_{cpu}.out")
        ok, berr = build(srcs, root, std, out_bin, ["-g"], "clang++")
        cxx = "clang++"
        if not ok:  # clang strictness: fall back to g++ so the unit still gets profiled
            ok, berr = build(srcs, root, std, out_bin, ["-g"], "g++")
            cxx = "g++"
        if not ok:
            log(f"BUILD_FAIL {uid}: {(berr.strip().splitlines() or ['?'])[-1]}")
            with wl:
                w.writerow([bank, uid, "", "", "", "", "BUILD_FAIL"]); fout.flush()
            return
        argv = ["valgrind", "--tool=massif", f"--massif-out-file={mf}", "--detailed-freq=5", out_bin]
        st, ec, kb, secs, th = run_peak(argv, [d, root], TMO_MASSIF, cpu)
        sites, heap = parse_massif(mf) if os.path.exists(mf) else ([], None)
        with wl:
            if not sites:
                log(f"{st if st != 'OK' else 'MASSIF_FAIL'} {uid} exit={ec}")
                w.writerow([bank, uid, "", "", "", "", st if st != "OK" else "MASSIF_FAIL"])
            else:
                for i, (b, f, ln) in enumerate(sites[:8], 1):
                    fr = os.path.relpath(f, ROOT) if os.path.isabs(f) else f
                    w.writerow([bank, uid, fr, ln, round(b / 1024, 1),
                                round(heap / 1024, 1), i])
                if main_src:
                    b, f, ln = sites[0]
                    tag = "runtime baseline (no user-code heap)" if ROOT not in sites[0][1] \
                        else f"{os.path.basename(f)}:{ln}"
                    replace_or_append(main_src, "// peak-alloc:",
                                      f"// peak-alloc: {tag} {sites[0][0]/1024:.1f} KB incl. "
                                      f"(heap peak {heap/1024:.1f} KB, massif {cxx} -g, {DATE})\n")
                n[0] += 1
                if n[0] % 25 == 0:
                    log(f"... {n[0]} profiled ({uid})")
            fout.flush()

    unit_list = list(units(only))
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {sum(1 for u in unit_list if u[7])})")
    parallel_run(unit_list, job, list(range(NWORK)))
    fout.close()
    log(f"\nmassif: {n[0]} newly profiled; CSV: {os.path.relpath(LINES_CSV, ROOT)}")

def parse_memcheck(path):
    """Parse a valgrind memcheck log: -> (kinds{definite,indirect,possible,reachable:(bytes,blocks)},
    errors, top_sites{kind:(file,line)}) ."""
    text = read(path)
    kinds = {k: [0, 0] for k in ("definitely lost", "indirectly lost", "possibly lost", "still reachable")}
    for m in re.finditer(r"^==\d+==\s+(definitely lost|indirectly lost|possibly lost|still reachable):"
                         r"\s+([\d,]+) bytes in ([\d,]+) blocks", text, re.M):
        kinds[m.group(1)] = [int(m.group(2).replace(",", "")), int(m.group(3).replace(",", ""))]
    errors = 0
    m = re.search(r"^==\d+==\s+ERROR SUMMARY: (\d+) errors", text, re.M)
    if m:
        errors = int(m.group(1))
    top = {}
    for m in re.finditer(r"^==\d+==\s+([\d,]+) bytes in [\d,]+ blocks are (definitely|indirectly|possibly) "
                         r"lost in loss record", text, re.M):
        start = m.start()
        seg = text[start:start + 1500]
        kind = m.group(2)
        b = int(m.group(1).replace(",", ""))
        fm = re.search(r"\((\S+\.(?:cpp|h)):(\d+)\)", seg)
        if fm and (kind not in top or b > top[kind][2]):
            top[kind] = (fm.group(1), int(fm.group(2)), b)
    return kinds, errors, top

def phase_leaks(only=None):
    os.makedirs(os.path.dirname(LINES_CSV), exist_ok=True)
    """valgrind memcheck leak analysis -> leaks.csv (parallel, incremental)."""
    done = set()
    new_file = not os.path.exists(LEAKS_CSV)
    if not new_file:
        with open(LEAKS_CSV) as f:
            done = {r["id"] for r in csv.DictReader(f)}
    n = [0]
    fout = open(LEAKS_CSV, "a", newline="")
    w = csv.writer(fout)
    wl = threading.Lock()
    if new_file:
        w.writerow(["bank", "id", "status", "definite_bytes", "definite_blocks", "indirect_bytes",
                    "possible_bytes", "reachable_bytes", "memcheck_errors", "top_site", "top_bytes"])

    def job(u, cpu):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        if uid in done:
            return
        if err:
            with wl:
                w.writerow([bank, uid, err, "", "", "", "", "", "", "", ""]); fout.flush()
            return
        out_bin = os.path.join(OUT, f"bin_l_{cpu}")
        lg = os.path.join(OUT, f"leak_{cpu}.log")
        ok, berr = build(srcs, root, std, out_bin, ["-g"], "clang++")
        cxx = "clang++"
        if not ok:
            ok, berr = build(srcs, root, std, out_bin, ["-g"], "g++")
            cxx = "g++"
        if not ok:
            log(f"BUILD_FAIL {uid}: {(berr.strip().splitlines() or ['?'])[-1]}")
            with wl:
                w.writerow([bank, uid, "BUILD_FAIL", "", "", "", "", "", "", "", ""]); fout.flush()
            return
        argv = ["valgrind", "--tool=memcheck", "--leak-check=full", "--leak-resolution=high",
                "--show-leak-kinds=definite,indirect,possible", f"--log-file={lg}", out_bin]
        st, ec, kb, secs, th = run_peak(argv, [d, root], TMO_LEAKS, cpu)
        if not os.path.exists(lg):
            log(f"MEMCHECK_FAIL {uid} ({st})")
            with wl:
                w.writerow([bank, uid, st or "MEMCHECK_FAIL", "", "", "", "", "", "", "", ""]); fout.flush()
            return
        kinds, errors, top = parse_memcheck(lg)
        definite, indirect, possible = kinds["definitely lost"], kinds["indirectly lost"], kinds["possibly lost"]
        # pick top site across kinds by bytes
        site, sbytes = "", 0
        for kind, (f, ln, b) in top.items():
            if b > sbytes:
                site, sbytes = f"{os.path.relpath(f, ROOT) if os.path.isabs(f) else f}:{ln}", b
        with wl:
            w.writerow([bank, uid, st, definite[0], definite[1], indirect[0], possible[0],
                        kinds["still reachable"][0], errors, site, sbytes])
            if main_src and (definite[0] or indirect[0] or possible[0] or errors):
                bits = []
                if definite[0]:  bits.append(f"{definite[0]} B definitely lost in {definite[1]} blocks")
                if indirect[0]:  bits.append(f"{indirect[0]} B indirectly lost")
                if possible[0]:  bits.append(f"{possible[0]} B possibly lost")
                if errors:       bits.append(f"{errors} memcheck error(s)")
                tag = f" top: {site}" if site else ""
                replace_or_append(main_src, "// leak-suspect:",
                                  f"// leak-suspect: " + "; ".join(bits) + f"{tag} (memcheck {cxx} -g, {DATE})\n")
            n[0] += 1
            if n[0] % 25 == 0:
                log(f"... {n[0]} leak-checked ({uid})")
            fout.flush()

    unit_list = list(units(only))
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {sum(1 for u in unit_list if u[7])})")
    parallel_run(unit_list, job, list(range(NWORK)))
    fout.close()
    log(f"\nleaks: {n[0]} newly checked; CSV: {os.path.relpath(LEAKS_CSV, ROOT)}")

def parse_race_log(path, tool):
    """-> (race_contexts, errors, first_sites "f1:l1 <-> f2:l2") from a helgrind/drd log."""
    text = read(path)
    pat = r"^==\d+== Possible data race" if tool == "helgrind" else r"^==\d+== Conflicting "
    races = len(re.findall(pat, text, re.M))
    m = re.search(r"^==\d+== ERROR SUMMARY: (\d+) errors", text, re.M)
    errors = int(m.group(1)) if m else -1
    sites = []
    i = text.find("Possible data race") if tool == "helgrind" else text.find("Conflicting ")
    if i >= 0:
        seg = text[i:i + 3000]
        for fm in re.finditer(r"\((\S+\.(?:cpp|h)):(\d+)\)", seg):
            f = fm.group(1)
            if os.path.isabs(f) and ROOT in f:
                fr = f"{os.path.relpath(f, ROOT)}:{fm.group(2)}"
                if fr not in sites:
                    sites.append(fr)
            if len(sites) == 2:
                break
    return races, errors, " <-> ".join(sites)

def phase_races(only=None):
    os.makedirs(os.path.dirname(RACES_CSV), exist_ok=True)
    """helgrind + DRD on MT units -> races.csv (incremental, 6-way concurrent, unpinned)."""
    done = set()
    new_file = not os.path.exists(RACES_CSV)
    if not new_file:
        with open(RACES_CSV) as f:
            done = {(r["id"], r["tool"]) for r in csv.DictReader(f)}
    n = [0]
    fout = open(RACES_CSV, "a", newline="")
    w = csv.writer(fout)
    wl = threading.Lock()
    if new_file:
        w.writerow(["bank", "id", "tool", "status", "race_contexts", "errors", "first_sites", "run_seconds"])

    def one(u, tool):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        res = (bank, uid, tool, err or "", "", "", "", "")
        if err:
            return res
        out_bin = os.path.join(OUT, f"bin_r_{re.sub(chr(87) + '+', '_', uid)}_{tool}")
        lg = os.path.join(OUT, f"race_{re.sub(chr(87) + '+', '_', uid)}_{tool}.log")
        ok, berr = build(srcs, root, std, out_bin, ["-g"], "clang++")
        cxx = "clang++"
        if not ok:
            ok, berr = build(srcs, root, std, out_bin, ["-g"], "g++")
            cxx = "g++"
        if not ok:
            log(f"BUILD_FAIL {uid} [{tool}]: {(berr.strip().splitlines() or ['?'])[-1]}")
            return (bank, uid, tool, "BUILD_FAIL", "", "", "", "")
        vgtool = "helgrind" if tool == "helgrind" else "drd"
        argv = ["valgrind", f"--tool={vgtool}", f"--log-file={lg}", out_bin]
        st, ec, kb, secs, th = run_peak(argv, [d, root], TMO_RACE, None)
        if not os.path.exists(lg):
            log(f"RACE_FAIL {uid} [{tool}] ({st})")
            return (bank, uid, tool, st or "RACE_FAIL", "", "", "", "")
        contexts, errors, sites = parse_race_log(lg, tool)
        return (bank, uid, tool, st, contexts, errors, sites, secs)

    def job(u, cpu):  # cpu ignored: MT units run unpinned
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        outs = []
        for tool in ("helgrind", "drd"):
            if (uid, tool) in done:
                continue
            r = one(u, tool)
            outs.append(r)
            with wl:
                w.writerow(r); fout.flush()
                n[0] += 1
                if n[0] % 4 == 0:
                    log(f"... {n[0]} race-runs done (last {uid}/{r[2]})")
        if outs and main_src:
            errs = {t: (int(r[5]) if r[5] not in ("", None) else 0) for r in outs for t in (r[2],)}
            total = sum(errs.values())
            if total > 0:
                first = next((r[6] for r in outs if r[6]), "")
                tools = "+".join(t for t in ("helgrind", "drd") if errs.get(t))
                replace_or_append(main_src, "// race-suspect:",
                                  f"// race-suspect: {total} race-detector error(s) ({tools}); "
                                  f"first: {first} (box2, {DATE})\n")
        return None

    unit_list = [u for u in units(only) if u[7]]  # MT-flagged units only
    log(f"MT units: {len(unit_list)} (workers: {NW_RACE}, unpinned)")
    q = queue.Queue()
    for u in unit_list:
        q.put(u)
    def worker():
        while True:
            try:
                u = q.get_nowait()
            except queue.Empty:
                return
            job(u, None)
    ws = [threading.Thread(target=worker) for _ in range(min(NW_RACE, len(unit_list) or 1))]
    for t in ws: t.start()
    for t in ws: t.join()
    fout.close()
    log(f"\nraces: {n[0]} runs; CSV: {os.path.relpath(RACES_CSV, ROOT)}")

def parse_san(text):
    """Parse ASan/UBSan/LSan output -> (asan_errors, ubsan_errors, leaked_bytes, first_site)."""
    asan = len(re.findall(r"ERROR: AddressSanitizer:", text))
    ubsan = len(re.findall(r": runtime error:", text))
    leak = re.search(r"SUMMARY: AddressSanitizer: ([\d,]+) byte\(s\) leaked in ([\d,]+) allocation", text)
    leaked = int(leak.group(1).replace(",", "")) if leak else 0
    site = ""
    for m in re.finditer(r"\((\S+\.(?:cpp|h)):(\d+)\)", text):
        f = m.group(1)
        if os.path.isabs(f) and ROOT in f:
            site = f"{os.path.relpath(f, ROOT)}:{m.group(2)}"
            break
    return asan, ubsan, leaked, site

def phase_san(only=None):
    os.makedirs(os.path.dirname(SAN_CSV), exist_ok=True)
    """ASan+UBSan+LSan with hardened stdlib -> sanitizers.csv + '// san-suspect:' where flagged.
    Best practice: run this FIRST - ~2x slowdown vs valgrind's ~20x; catches use-after-free,
    overflow, UB and leaks fast; keep memcheck/massif for what sanitizers miss."""
    done = set()
    new_file = not os.path.exists(SAN_CSV)
    if not new_file:
        with open(SAN_CSV) as f:
            done = {r["id"] for r in csv.DictReader(f)}
    unit_list = list(units(only))
    log(f"units: {len(unit_list)} (workers: {NWORK}, MT deferred: {sum(1 for u in unit_list if u[7])})")
    rows_out, lock = [], threading.Lock()
    def job(u, cpu):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        if uid in done:
            return
        if err:
            with lock:
                rows_out.append((bank, uid, err, 0, 0, 0, ""))
            return
        out = os.path.join(OUT, f"bin_san_{re.sub(chr(87) + chr(43), '_', uid)}")
        flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g",
                 "-D_GLIBCXX_ASSERTIONS"]
        ok, berr = build(srcs, root, std, out, flags, "clang++")
        cxx = "clang++"
        if not ok:
            ok, berr = build(srcs, root, std, out, flags, "g++")
            cxx = "g++"
        if not ok:
            log(f"BUILD_FAIL {uid} [san]: {(berr.strip().splitlines() or ['?'])[-1]}")
            with lock:
                rows_out.append((bank, uid, "BUILD_FAIL", 0, 0, 0, ""))
            return
        lg = os.path.join(OUT, f"san_{re.sub(chr(87) + chr(43), '_', uid)}")
        env = {"ASAN_OPTIONS": f"detect_stack_use_after_return=1:log_path={lg}",
               "UBSAN_OPTIONS": f"print_stacktrace=1:log_path={lg}"}
        st, ec, kb, secs, th = run_peak([out], [d, root], TMO_SAN, cpu, env)
        text = "".join(read(f) for f in glob.glob(lg + "*"))
        asan, ubsan, leaked, site = parse_san(text)
        flagged = asan or ubsan or leaked
        with lock:
            rows_out.append((bank, uid, st, asan, ubsan, leaked, site))
            if flagged and main_src:
                bits = []
                if asan: bits.append(f"{asan} ASan error(s)")
                if ubsan: bits.append(f"{ubsan} UBSan error(s)")
                if leaked: bits.append(f"{leaked} B leaked (LSan)")
                replace_or_append(main_src, "// san-suspect:",
                                  "// san-suspect: " + "; ".join(bits) +
                                  (f" first: {site}" if site else "") +
                                  f" (sanitizers {cxx}, {DATE})\n")
            if flagged:
                log(f"SAN_FLAGGED {uid}: asan={asan} ubsan={ubsan} leaked={leaked} B")
    with open(SAN_CSV, "a", newline="") as fout:
        w = csv.writer(fout)
        if new_file:
            w.writerow(["bank", "id", "status", "asan_errors", "ubsan_errors", "leaked_bytes", "first_site"])
        parallel_run(unit_list, job, list(range(NWORK)))  # defers MT units to serial unpinned runs
        for r in rows_out:
            w.writerow(r)
    log(f"\nsan: done; CSV: {os.path.relpath(SAN_CSV, ROOT)}")

def phase_tsan(only=None):
    os.makedirs(os.path.dirname(RACES_CSV), exist_ok=True)
    """ThreadSanitizer on MT-flagged units -> races.csv rows with tool=tsan.
    TSan sees LLVM atomics (unlike helgrind/DRD), so it is the right detector for modern C++;
    -O1 per upstream guidance (higher opts reduce detection accuracy). Runs serially unpinned."""
    done = set()
    new_file = not os.path.exists(RACES_CSV)
    if not new_file:
        with open(RACES_CSV) as f:
            done = {(r["id"], r["tool"]) for r in csv.DictReader(f)}
    unit_list = [u for u in units(only) if u[7]]  # MT units only
    log(f"MT units for TSan: {len(unit_list)}")
    rows_out, lock = [], threading.Lock()
    def job(u, cpu=None):
        bank, uid, d, root, std, srcs, main_src, mt, err = u
        if (uid, "tsan") in done:
            return
        if err:
            with lock:
                rows_out.append((bank, uid, "tsan", err, "", "", "", ""))
            return
        out = os.path.join(OUT, f"bin_tsan_{re.sub(chr(87) + chr(43), '_', uid)}")
        flags = ["-fsanitize=thread", "-O1", "-g"]
        ok, berr = build(srcs, root, std, out, flags, "clang++")
        if not ok:
            ok, berr = build(srcs, root, std, out, flags, "g++")
        if not ok:
            log(f"BUILD_FAIL {uid} [tsan]: {(berr.strip().splitlines() or ['?'])[-1]}")
            with lock:
                rows_out.append((bank, uid, "tsan", "BUILD_FAIL", "", "", "", ""))
            return
        lg = os.path.join(OUT, f"tsan_{re.sub(chr(87) + chr(43), '_', uid)}.log")
        env = {"TSAN_OPTIONS": f"log_path={lg}:history_size=4"}
        st, ec, kb, secs, th = run_peak([out], [d, root], TMO_RACE, cpu, env)
        text = "".join(read(f) for f in glob.glob(lg + "*"))
        races = len(re.findall(r"WARNING: ThreadSanitizer: data race", text))
        sites = []
        for m2 in re.finditer(r"\((\S+\.(?:cpp|h)):(\d+)\)", text):
            f = m2.group(1)
            if os.path.isabs(f) and ROOT in f:
                fr = f"{os.path.relpath(f, ROOT)}:{m2.group(2)}"
                if fr not in sites:
                    sites.append(fr)
            if len(sites) == 2:
                break
        alerts = re.search(r"ThreadSanitizer: reported (\d+) alerts", text)
        n = int(alerts.group(1)) if alerts else races
        with lock:
            rows_out.append((bank, uid, "tsan", st, n, n, " <-> ".join(sites), round(secs, 2)))
            if n and main_src:
                replace_or_append(main_src, "// race-suspect:",
                                  f"// race-suspect: {n} TSan alert(s) from {races} race contexts; "
                                  f"first: {' <-> '.join(sites) or '?'} (TSan -O1, {DATE})\n")
            log(f"tsan {uid}: {n} alerts ({races} race contexts)")
    with open(RACES_CSV, "a", newline="") as fout:
        w = csv.writer(fout)
        if new_file:
            w.writerow(["bank", "id", "tool", "status", "race_contexts", "errors", "first_sites", "run_seconds"])
        for u in unit_list:  # TSan programs use all cores: serial, unpinned
            job(u)
        for r in rows_out:
            w.writerow(r)
    log(f"\ntsan: done; CSV: {os.path.relpath(RACES_CSV, ROOT)}")

# ---------------- mode: report (synthesis) ----------------

def phase_report(only=None):
    """Synthesize all CSVs into runtime_audit_report/IMPROVEMENT_REPORT.md: per-unit findings mapped to
    concrete improvement advice, grouped by objective (safety / robustness / speed / memory).
    This is the deliverable: not raw tool output, but a perspective for improving the sources."""
    import statistics
    reports_dir = os.path.dirname(CSV)
    def load(name):
        p = os.path.join(reports_dir, name)
        return list(csv.DictReader(open(p))) if os.path.exists(p) else []
    pm, san, leaks, races, lines = (load("peak_memory.csv"), load("sanitizers.csv"),
                                    load("leaks.csv"), load("races.csv"), load("peak_memory_lines.csv"))
    find = {}  # uid -> {category: [advice lines]}
    def add(uid, cat, advice):
        find.setdefault(uid, {}).setdefault(cat, []).append(advice)
    int_ = lambda v: int(v) if str(v).strip().isdigit() else 0
    flo = lambda v: float(v) if str(v).strip() else 0.0

    # 1) timing + memory profiles -> speed / memory perspective
    ok = [r for r in pm if r["status"] == "OK"]
    med_t = statistics.median([flo(r["run_seconds"]) for r in ok if flo(r["run_seconds"]) > 0]) if ok else 0
    med_rss = statistics.median([int_(r["peak_rss_kb_clang_O0"]) for r in ok if int_(r["peak_rss_kb_clang_O0"])]) if ok else 0
    for r in ok:
        t, rss = flo(r["run_seconds"]), int_(r["peak_rss_kb_clang_O0"])
        th = int_(r["threads_max"])
        if t > max(5.0, 10 * med_t) and med_t:
            add(r["id"], "speed", f"slowest in bank ({t}s vs median {med_t:.2f}s): profile the hot loop "
                f"(perf record + flamegraph) and check algorithmic complexity before parallelizing")
        if rss and med_rss and rss > med_rss + 4096:
            add(r["id"], "memory", f"peak RSS {rss} KB is >4 MB above the {med_rss:.0f} KB bank median: "
                "reserve/container capacity growth or materialized datasets - reserve(), stream in chunks")
        if th > 1 and r["pinned"] == "no":
            add(r["id"], "speed", f"multi-threaded ({th} threads observed): confirm near-linear speedup vs 1 thread; "
                "contention on shared counters shows up as sub-linear scaling")
        t0, t2 = flo(r.get("time_o0_clang", "")), flo(r.get("time_o2_clang", ""))
        if t0 and t2 and t0 > 0.5 and t2 > 0 and t0 / max(t2, 0.01) < 1.3:
            add(r["id"], "speed", f"-O0 and -O2 times nearly equal ({t0}s vs {t2}s): runtime is IO/memory-bound - "
                "optimizer flags will not help; look at IO volume and allocation churn")
        smax = int_(r.get("stack_max_bytes", ""))
        if smax >= 65536:
            add(r["id"], "robustness", f"stack frame(s) up to {smax} B (deep recursion or large locals): "
                "risk of stack overflow on constrained threads (default thread stack ~8 MB, worker threads ~2 MB) - "
                "convert recursion to iteration or move buffers to the heap")
        elif smax >= 16384:
            add(r["id"], "memory", f"stack frame(s) up to {smax} B: large locals (arrays/matrices) - "
                "prefer heap allocation for big buffers")

    # 2) sanitizers + memcheck -> safety / robustness
    for r in san:
        if int_(r["asan_errors"]) or int_(r["leaked_bytes"]):
            add(r["id"], "safety", f"ASan: {r['asan_errors']} memory error(s), {r['leaked_bytes']} B leaked "
                f"({r['first_site'] or 'site in CSV'}): fix with owner semantics - unique_ptr/RAII, "
                "bounds-checked access; re-run --san to confirm")
        if int_(r["ubsan_errors"]):
            add(r["id"], "robustness", f"UBSan: {r['ubsan_errors']} undefined-behaviour event(s) "
                "(signed overflow, bad shifts, invalid casts): use checked arithmetic/wider types; "
                "UB can miscompile with -O2 at any time")
    for r in leaks:
        if int_(r["definite_bytes"]) or int_(r["indirect_bytes"]):
            add(r["id"], "robustness", f"memcheck: {r['definite_bytes']} B definite + {r['indirect_bytes']} B "
                f"indirect lost ({r['top_site'] or 'site in CSV'}): RAII owners (unique_ptr, containers), "
                "weak_ptr for shared cycles; if a deliberate demo, document it in-source")

    # 3) races -> safety
    per_unit = {}
    for r in races:
        per_unit.setdefault(r["id"], []).append((r["tool"], int_(r["errors"]), r["first_sites"]))
    for uid, tools in per_unit.items():
        tools_s = ", ".join(f"{t}:{e}" for t, e, _ in tools if e)
        if tools_s:
            sites = next((s for _, _, s in tools if s), "")
            add(uid, "safety", f"race detectors flag: {tools_s} at {sites or 'sites in CSV'}: "
                "guard shared state (mutex/lock_guard, std::atomic, scoped_lock for multi-lock); "
                "re-verify with TSan; if the unit deliberately demonstrates a race, say so in-source")

    # 4) emit report
    cats = ("safety", "robustness", "speed", "memory")
    flagged = {u: c for u, c in find.items() if c}
    L = [f"# Improvement report - C++ solution bank", f""]
    L += [f"Generated {DATE}. Objective: benchmark time + peak memory, audit stack/heap safety and "
          f"parallel races, and distill a concrete improvement perspective for the sources.", ""]
    L += ["## Summary", ""]
    L += [f"- units profiled: {len(ok)} OK / {sum(1 for r in pm if r['status'] != 'OK')} with issues"]
    L += [f"- flagged units: {len(flagged)}"]
    for c in cats:
        n = sum(1 for u in flagged.values() if c in u)
        L += [f"- {c}: {n} unit(s) with findings"]
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
    L += ["## Clean units", ""]
    clean = sorted(set(r["id"] for r in ok) - set(flagged))
    L += [f"{len(clean)} unit(s) with no findings: no sanitizer/memcheck/race flags, baseline RSS, "
          f"typical runtime.", ""]
    out = os.path.join(reports_dir, "IMPROVEMENT_REPORT.md")
    out_p = Path(out).resolve()
    if not out_p.is_relative_to(Path(ROOT).resolve()):
        sys.exit(f"error: report path escapes audit root: {out}")
    out_p.write_text("\n".join(L) + "\n")
    log(f"report: {len(flagged)} flagged of {len(ok)} OK units -> {os.path.relpath(out, ROOT)}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--massif", action="store_true", help="per-line heap attribution mode")
    ap.add_argument("--leaks", action="store_true", help="memcheck leak-shape mode")
    ap.add_argument("--races", action="store_true", help="helgrind+DRD mode (MT units only)")
    ap.add_argument("--san", action="store_true", help="ASan+UBSan+LSan hardened build mode")
    ap.add_argument("--tsan", action="store_true", help="ThreadSanitizer mode (MT units only)")
    ap.add_argument("--report", action="store_true", help="synthesize CSVs into IMPROVEMENT_REPORT.md")
    ap.add_argument("--only", help="comma-separated unit ids (debug)")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    mode = phase_report if a.report else phase_tsan if a.tsan else phase_san if a.san else \
        phase_races if a.races else (phase_leaks if a.leaks else (phase_massif if a.massif else phase_opts))
    mode(only)
