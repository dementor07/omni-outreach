# Stage 1: Build
FROM rust:1.78-slim-bookworm as builder

# Install build dependencies
RUN apt-get update && apt-get install -y pkg-config libssl-dev cmake && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY . .

# Build for release
RUN cargo build --release

# Stage 2: Runtime
FROM debian:bookworm-slim

# Install runtime dependencies (OpenSSL is needed for HTTPS)
RUN apt-get update && apt-get install -y libssl3 ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/app
COPY --from=builder /usr/src/app/target/release/execution-engine .

CMD ["./execution-engine"]
