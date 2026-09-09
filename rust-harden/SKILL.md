---
name: rust-harden
description: This skill should be used when the user asks to "harden Rust code for production", "make Rust production-ready", "prevent Rust panics in production", "set up panic hooks", "configure panic = abort", "harden a Rust web service", "secure Rust Docker images", "add Landlock sandboxing", "drop privileges in Rust", "add circuit breakers", "set resource limits on Rust services", "add health checks and readiness probes", "graceful shutdown in Rust", "audit Rust dependencies", "use mimalloc secure allocator", "run Miri on Rust code", "test Rust release builds", "prevent stack overflows in Rust", or mentions production hardening, runtime resilience, failure modes, supply-chain security, or operational robustness for Rust programs. Use this skill whenever the user wants to make Rust code resilient at runtime, reduce its attack surface, or prepare it for production deployment.
---

# Rust-Harden — Hardening Rust Code For Production

## Overview

Production Rust is not the same as development Rust. Even valid, safe code can
fail at runtime in ways that are hard to predict and control: panics unwind (or
abort) across thread and FFI boundaries, debug and release builds behave
differently, unbounded resources become DoS vectors, and a compromised process
can reach anything the container mounts. This skill covers the full playbook for
making Rust code resilient at runtime and hardening it for production.

## When to Use This Skill

Use this skill when:

- Hardening a Rust service for production deployment
- Deciding panic strategy (unwind vs abort) and writing panic hooks
- Reducing runtime attack surface (minimal images, Landlock, least privilege)
- Setting resource limits (request body size, queue depth, timeouts)
- Adding health checks (liveness/readiness) and graceful shutdown
- Adding circuit breakers around external dependencies
- Auditing dependencies for vulnerabilities (cargo-audit, cargo-deny)
- Detecting undefined behavior with Miri
- Securing heap allocations (mimalloc secure mode)
- Testing release-vs-debug behavioral differences
- Preventing stack overflows from unbounded recursion
- Sanitizing sensitive data in panic messages / crash reports

## The Hardening Checklist

Work through these layers; each maps to a section in the reference:

1. **Panic semantics** — Decide unwind vs abort (`[profile.release] panic = "abort"`). Know that stack overflows and OOM always abort. Be explicit about whether a panic kills a task, thread, or process.
2. **Panic hooks** — Set a `panic::set_hook` for observability: log, report, and clean up. Sanitize secrets. Never rely on hooks for correctness (they don't run on abort).
3. **Stack safety** — Don't let recursion depth depend on untrusted input. Rewrite iteratively or bound the depth. TCO is not guaranteed on stable.
4. **Release vs debug** — Integer overflow wraps in release, `debug_assert!` is stripped, UB can surface only under the optimizer. Run `cargo test --release` in CI for arithmetic/unsafe/FFI-heavy code.
5. **Supply chain** — Run `cargo-audit` and `cargo-deny` in CI. Add `cargo-vet` and import Google's/Mozilla's published audits. Replace bloated/auto-generated SDK crates (e.g. swap `aws-sdk-s3` → `object_store`) to cut compile time and binary size.
6. **Secure allocator** — `mimalloc` with `features = ["secure"]` as `#[global_allocator]` for defense-in-depth and lower fragmentation (esp. with unsafe/FFI/C deps like zstd, aws-lc-rs, SQLite). `jemalloc`/`tcmalloc` are alternatives.
7. **Minimal runtime** — distroless `:nonroot` images via cargo-chef; or static musl + `FROM scratch` (drop to `alpine` only if a CLI tool is truly needed). Don't mix glibc-linked binaries with musl images. Prefer MUSL static binaries for max compatibility.
8. **Filesystem + network sandboxing** — Landlock (Linux 5.13+) restricts the process to explicitly-allowed paths *and* ports (`NetPort`: e.g. allow bind 8080, connect only 443/53). Apply early in `main`, after enumerating needed paths; prefer designing the service to avoid `/tmp` entirely. Also defense-in-depth inside containers/microvms.
9. **Drop privileges** — Don't run as root; prefer high ports or `CAP_NET_BIND_SERVICE`; drop startup-only caps before serving.
10. **Miri** — `cargo +nightly miri test` to catch UB, data races, and aliasing violations.
11. **Graceful shutdown** — Listen for `SIGTERM`/`SIGINT`, stop accepting work, drain in-flight, exit. (e.g. `tokio-graceful-shutdown`.)
12. **Circuit breakers** — Trip on repeated downstream failures (`recloser`, `failsafe`).
13. **Resource limits** — Bound everything: request body size, queue depth (`mpsc::channel(N)`), connect/request timeouts, pool sizes, concurrency.
14. **Health checks** — Separate liveness (process alive) and readiness (deps up; Healthy/Degraded/Unhealthy) endpoints, mapped to K8s probes.

### Build & release workflow (from the Kerkour checklist)

- **Makefile** — Codify `make dev|build|docker_build|docker_push|update_deps` so anyone can `git pull` and work.
- **`lld` linker** — Add `-C link-args=-fuse-ld=lld` in `.cargo/config.toml` for non-`x86_64-unknown-linux-gnu` targets (default since Rust 1.90 on that target). Cuts dev builds from 5s+ to <2s.

## Runtime Hardening Tooling (quick reference)

| Tool | Purpose |
|------|---------|
| `cargo-audit` | Known-vuln advisory scan |
| `cargo-deny` | License / advisory / ban policy |
| `cargo-fuzz` / `honggfuzz` | Fuzz testing |
| `cargo-geiger` | Detect `unsafe` usage |
| `cargo-valgrind` | Memory error detection |
| `cargo-vet` | Verify deps audited by trusted entities (import Google/Mozilla audits) |
| `cargo-llvm-cov` | Source-based coverage (good default) |
| `cargo-tarpaulin` | Older coverage tool, strong Cargo/CI ergonomics |
| `mimalloc` (`secure`) | Hardened global allocator (alt: `jemalloc`, `tcmalloc`) |
| `Miri` (nightly) | UB / data-race detection at runtime |
| `lld` / `mold` | Faster linkers (config via `.cargo/config.toml`) |

## Detailed References

Two complementary sources back this skill. Load the one matching the task:

**See: [hardening-rust.md](references/hardening-rust.md)** — the corrode.dev deep
dive. Complete runnable code for panic hooks, the Landlock sandbox, the
distroless Dockerfile, Miri CI, graceful shutdown, circuit breakers, resource
limits, and the K8s health-check probes. The panic-strategy tradeoffs in depth,
plus the supply-chain/sandboxing rationale.

**See: [kerkour-production-checklist.md](references/kerkour-production-checklist.md)** —
the Kerkour release checklist. The battle-tested workflow side: `Makefile`
tasks, `lld`/`.cargo/config.toml`, MUSL static builds, the allocator-fragmentation
rationale, the network-scoped Landlock example (`NetPort` for bind/connect), the
`scratch`/`alpine` Dockerfile with an unprivileged user, and `cargo-vet`.

## External Resources

- corrode.dev source: <https://corrode.dev/blog/hardening-rust/>
- Kerkour checklist source: <https://kerkour.com/rust-service-hardening-and-production-checklist>
- Companion post (defensive programming): <https://corrode.dev/blog/defensive-programming>
- Rustonomicon (unwinding / FFI): <https://doc.rust-lang.org/nomicon/unwinding.html>
- Miri: <https://github.com/rust-lang/miri>
- mimalloc: <https://github.com/microsoft/mimalloc>
- Landlock (kernel docs): <https://docs.kernel.org/userspace-api/landlock.html>
- distroless: <https://github.com/GoogleContainerTools/distroless>
- Google crate audits (for `cargo-vet`): <https://github.com/google/rust-crate-audits>

Load the references as needed when working on specific hardening topics.
