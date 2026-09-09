# Makefile — Rust Service Hardening And Production Checklist

Source: <https://kerkour.com/rust-service-hardening-and-production-checklist>

There aren't many resources about how to actually deliver Rust projects to your users: workflows, security hardening and artifacts management, so here is the checklist I use to release backend services and CLI binaries.

## Makefile

I use a `Makefile` in 100% of my Rust projects. It's not that I'm lazy to type `cargo run` or `cargo build`, it's a way to codify the different workflows and tasks required to work and release the codebase.

Here are a few tasks that I always use:

- `make dev`: run the project with automatic reloading.
- `make build`: build the project in release mode.
- `make docker_build`: build the Docker image.
- `make docker_push`: push the Docker image.
- `make update_deps`: update dependencies.

Anyone can `git pull` my repositories, read the `Makefile` and know everything they need to work on the codebase.

## Use the lld linker

The `lld` linker from the [LLVM project](https://lld.llvm.org/) is faster than the default one used by Rust, sometimes accelerating development builds from 5+ seconds to less than 2 seconds.

Since Rust 1.90 lld is the default linker for the `x86_64-unknown-linux-gnu` target but not for the other targets, so I always configure Cargo to use it.

**.cargo/config.toml**

```toml
[build]
rustflags = ["-C", "target-cpu=native"]

# Using lld as the linker greatly improves compilation time.
# Since Rust 1.90 lld is the default linker on x86_64-unknown-linux-gnu
[target.x86_64-unknown-linux-musl]
rustflags = ["-C", "link-args=-fuse-ld=lld"]
[target.aarch64-unknown-linux-gnu]
rustflags = ["-C", "link-args=-fuse-ld=lld"]
[target.aarch64-unknown-linux-musl]
rustflags = ["-C", "link-args=-fuse-ld=lld"]
```

## Build static executables with the MUSL target

Because we want minimal Docker images and maximum compatibility across Linux distributions, I always build static executables using the `XX-unknown-linux-musl` targets.

## Replace the global allocator with jemalloc or mimalloc

Both MUSL's and glibc's malloc implementations are not great when you need high performance and low memory usage, due to, among other things, heap fragmentation (see _[High-performance Rust: Understanding and eliminating heap fragmentation](https://kerkour.com/rust-high-performance-memory-fragmentation-allocations)_).

That's why I always replace the default allocator with [mimalloc](https://github.com/microsoft/mimalloc) or [jemalloc](https://github.com/jemalloc/jemalloc).

```toml
[dependencies]
mimalloc = { version = "0.1", features = ["secure"] }
```

```rust
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;
```

_Example of memory fragmentation for a Rust service. The only thing that has changed in the second release is the allocator, from glibc's malloc to jemalloc._

![Memory fragmentation in Rust](https://kerkour.com/assets/2025/04/rust_memory_fragmentation.jpg)

Google and Cloudflare reportedly use [tcmalloc](https://github.com/google/tcmalloc), but I have no experience with it.

I always enable mimalloc's `secure` mode as the performance impact is negligible (-10% according to the documentation) compared to the cost of a hacked server. Rust is basically never the bottleneck (database or I/O are most of the time) so I see no reason not to enable it. Even if Rust is memory safe, production projects often use a few C-based dependencies such as `zstd`, `aws-lc-rs` or SQLite.

> Want to learn real-world Rust, security engineering and applied cryptography? Take a look at my book [Black Hat Rust](https://kerkour.com/black-hat-rust), where, from theory to practice, you will learn how to build crawlers, an end-to-end encrypted Remote Access Tool and exploits in Rust, and many other things to get your hands dirty.

## Drop your privileges with landlock

While all my Rust services are deployed in containers or [microvms](https://kerkour.com/firecracker-deep-dive-rust), I like to add an additional layer of security with landlock to limit the blast radius and potential privilege escalation vectors of a compromised service.

For that I use the [landlock](https://github.com/landlock-lsm/rust-landlock) crate to allowlist the very few files and directories touched by my services.

The idea is simple: after loading everything they need (config...), your services drop their own privileges to limit themselves to only what they really need to work.

I design my services (when possible) to never use the `/tmp` folder and only work in memory or directly write to object storage. This greatly simplifies sandboxing and deployment.

```rust
use landlock::{
    ABI, Access, AccessFs, AccessNet, NetPort, Ruleset, RulesetAttr, RulesetCreatedAttr, RulesetError, RulesetStatus,
    path_beneath_rules,
};

fn main() -> Result<(), RulesetError> {
    let abi = ABI::V7;
    let status = Ruleset::default()
        .handle_access(AccessNet::BindTcp)?
        .handle_access(AccessNet::ConnectTcp)?
        .handle_access(AccessFs::from_all(abi))?
        .create()?
        // Read-only access to /usr, /etc and /dev.
        .add_rules(path_beneath_rules(&["/usr", "/etc", "/dev"], AccessFs::from_read(abi)))?
        // Read-write access to /tmp.
        // .add_rules(path_beneath_rules(&["/tmp"], AccessFs::from_all(abi)))?
        // Only allow outbound connections to port 443 (HTTPS) and 53 (DNS)
        .add_rule(NetPort::new(443, AccessNet::ConnectTcp))?
        .add_rule(NetPort::new(53, AccessNet::ConnectTcp))?
        // Only allow inbound connections to port 8080
        .add_rule(NetPort::new(8080, AccessNet::BindTcp))?
        .restrict_self()?;

    match status.ruleset {
        RulesetStatus::FullyEnforced => println!("Fully sandboxed."),
        RulesetStatus::PartiallyEnforced => println!("Partially sandboxed."),
        RulesetStatus::NotEnforced => println!("Not sandboxed! Please update your kernel."),
    }

    Ok(())
}
```

## Replace bloated dependencies

Some crates, especially automatically-generated SDKs, are really, really bloated. Replacing `aws-sdk-s3` with the [object_store](https://github.com/apache/arrow-rs-object-store) crate reduced the compile time of a project from 25 to 20 minutes (especially the linking phase) and reduced the size of the final binary from ~25 MB to ~20 MB.

## Minimal Docker images

Deploying minimal containers is not only good for security by reducing the number of tools that can be used by attackers for lateral movements and privilege escalation, but also to accelerate your deployments. Small Docker images are faster to pull, uncompress, and run by servers.

I generally use a `FROM scratch` container and move to `alpine` if I really need a specific CLI tool. While I use `debian` images for my [dev containers](https://kerkour.com/rust-devcontainers), I prefer `alpine` for production because of the reduced attack surface and that the packages are up to date.

As you can see, I use the `rust:alpine` image to build the project in order to compile to the `musl` target without needing to specify `XX-unknown-linux-musl` for every platform that your program targets.

```dockerfile
####################################################################################################
## Build
####################################################################################################
FROM rust:alpine AS build

RUN apk update && \
    apk upgrade --no-cache && \
    apk add --no-cache lld mold musl musl-dev libc-dev cmake clang clang-dev openssl file \
        libressl-dev git make build-base bash curl wget zip gnupg coreutils gcc g++  zstd binutils ca-certificates upx

WORKDIR /myproject
COPY . ./
# or cargo build --release
RUN make build

####################################################################################################
## This stage is used to get the correct files into the final image
####################################################################################################
FROM alpine:latest AS files

# mailcap is used for content type (MIME type) detection
# tzdata is used for timezone info
RUN apk update && \
    apk upgrade --no-cache && \
    apk add --no-cache ca-certificates mailcap tzdata

RUN update-ca-certificates

ENV USER=myproject
ENV UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    "${USER}"

####################################################################################################
## Final image
####################################################################################################
FROM scratch

# /etc/nsswitch.conf may be used by some DNS resolvers
# /etc/mime.types may be used to detect the MIME type of files
COPY --from=files --chmod=444 \
    /etc/passwd \
    /etc/group \
    /etc/nsswitch.conf \
    /etc/mime.types \
    /etc/

COPY --from=files --chmod=444 /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=files --chmod=444 /usr/share/zoneinfo /usr/share/zoneinfo

# Copy our build
COPY --from=build /myproject/target/release/myproject /bin/myproject

# Use an unprivileged user.
USER myproject:myproject

# The scratch image doesn't have a /tmp folder, you may need it
# WORKDIR /tmp

WORKDIR /app

ENTRYPOINT ["/bin/myproject"]

# EXPOSE 8080
```

### Audit your dependencies

Rust's supply chain security [is not great](https://kerkour.com/rust-supply-chain-nightmare). Fortunately, there are a few tools you can use to reduce the likelihood of supply chain attacks:

[cargo-audit](https://github.com/rustsec/rustsec) which checks against a database if some of your dependencies contain known vulnerabilities or are abandoned.

[cargo-vet](https://github.com/mozilla/cargo-vet) to ensure that third-party Rust dependencies have been audited by trusted entities.

At least Google and Mozilla publicly publish the results of their audits so you can import them in `cargo-vet`: <https://github.com/google/rust-crate-audits> and <https://github.com/mozilla/supply-chain>

```text
$ cargo audit
    Fetching advisory database from `https://github.com/RustSec/advisory-db.git`
      Loaded 317 security advisories (from /usr/local/cargo/advisory-db)
    Updating crates.io index
    Scanning Cargo.lock for vulnerabilities (144 crate dependencies)
    ...
```

## Closing Thoughts

I will update this list as my workflow changes, so feel free to bookmark it and come back later :)

If you want to learn backend development with Rust, take a look at my article [Architecting and building medium-sized web services in Rust with Axum, SQLx and PostgreSQL](https://kerkour.com/rust-web-services-axum-sqlx-postgresql).

If you want to learn embedded development, take a look at [Introduction to embedded development with Rust: Overview of the ecosystem](https://kerkour.com/introduction-to-embedded-development-with-rust).

If you want to learn applied cryptography, start with [Cryptographic Right Answers: Post Quantum and Rust Edition](https://kerkour.com/post-quantum-cryptography-recommendations-rust).

Finally, if you want to learn from years of experience of software and security engineering, take a look at my books:

- [Blak Hat Rust](https://kerkour.com/black-hat-rust), where, from theory to practice, you will learn Rust, security engineering and applied cryptography, and build many projects such as multiple crawlers, an end-to-end encrypted Remote Access Tool (RAT), an evil-twin phishing access point, build shellcodes in Rust with `#![no_std]` instead of assembly and many more things to get your hands dirty.
- [Continuous Learning](https://kerkour.com/continuous-learning) where I share everything I've learned about learning to learn, which is the most important skill for any white collar evolving in a fast-changing world. Based on neuroscience, I've built a simple system that enables me to accumulate knowledge and use it to my advantage in the information age.

100% LLM-free and DRM-free, of course.
