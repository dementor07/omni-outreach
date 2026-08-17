# Stage 1: Build
# RUST-001: pinned STABLE toolchain (matches rust-toolchain.toml channel 1.89.0)
# instead of `nightly`. nightly let transitive deps float forward and broke
# clean rebuilds. --locked below enforces the committed Cargo.lock so the image
# resolves exactly the audited dependency tree.
FROM rust:1.89-bookworm as builder

ARG BUILD_SHA=unknown

# Install build dependencies
RUN apt-get update && apt-get install -y pkg-config libssl-dev build-essential zlib1g-dev libsasl2-dev libzstd-dev librdkafka-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY . .

# Build for release against the committed lockfile (fails if Cargo.lock is
# missing or out of sync, rather than silently re-resolving).
RUN cargo build --release --locked

# Stage 2: Runtime
FROM debian:bookworm-slim

ARG BUILD_SHA=unknown
LABEL org.opencontainers.image.revision="${BUILD_SHA}"
ENV BUILD_SHA="${BUILD_SHA}"

# Install runtime dependencies (OpenSSL is needed for HTTPS)
RUN apt-get update && apt-get install -y libssl3 ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/app
COPY --from=builder /usr/src/app/target/release/execution-engine .

CMD ["./execution-engine"]
