# ──────────────────────────────────────────────────────────────────────────
# Dockerfile for Post-Quantum Cryptography Migration Platform
# ──────────────────────────────────────────────────────────────────────────
#
# Build: docker build -t pqc-lab .
# Run:   docker run -p 5000:5000 --env-file .env pqc-lab
#
# Base image: Ubuntu 22.04 (ships with Python 3.10 and OpenSSL 3.x)
# Why Ubuntu 22.04?
#   - OpenSSL 3.0.x ships by default (required for oqs-provider)
#   - LTS support until April 2027
#   - Same environment as typical AWS EC2 instance
#
# Post-quantum note:
#   This Dockerfile installs the base application. To enable PQC modes
#   (Mode B and Mode C), you also need to install oqs-provider.
#   See the commented section at the bottom and docs/cloud-deployment.md.
# ──────────────────────────────────────────────────────────────────────────

FROM ubuntu:22.04

LABEL maintainer="PQC Lab" \
      description="Post-Quantum Cryptography TLS Benchmarking Platform" \
      version="1.0.0"

# Prevent interactive prompts during apt-get
ENV DEBIAN_FRONTEND=noninteractive

# ── System dependencies ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    python3-venv \
    openssl \
    libssl-dev \
    ca-certificates \
    curl \
    git \
    build-essential \
    cmake \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Verify OpenSSL version (should be 3.x on Ubuntu 22.04)
RUN openssl version

# ── Create non-root user (security best practice) ─────────────────────────
# Running as root inside containers is a security risk.
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# ── Application directory ─────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────
# Copy requirements first so Docker caches this layer when code changes
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────
COPY --chown=appuser:appuser . .

# Create directories that need write access
RUN mkdir -p /app/results && chown appuser:appuser /app/results

# ── !! Optional PQC section ── Uncomment to enable Modes B & C ────────────
# Install Open Quantum Safe liboqs and oqs-provider.
# This adds ~800 MB and 10-15 minutes to the build.
# See docs/cloud-deployment.md for the full PQC setup procedure.
#
# ARG OQS_VERSION=0.10.1
# RUN bash /app/scripts/install_oqs_provider.sh ${OQS_VERSION}
# ── End optional section ──────────────────────────────────────────────────

# ── Switch to non-root user ───────────────────────────────────────────────
USER appuser

# ── Environment defaults ──────────────────────────────────────────────────
ENV PORT=5000 \
    ENV=production \
    START_LOOPBACK_SERVER=true \
    DATABASE_PATH=/app/results/experiments.db

# ── Health check ──────────────────────────────────────────────────────────
# Docker will call /health every 30 seconds.
# After 3 consecutive failures, the container is marked unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# ── Expose port ───────────────────────────────────────────────────────────
EXPOSE ${PORT}

# ── Start Gunicorn (production WSGI server) ───────────────────────────────
# Gunicorn is a robust Python WSGI server. Never use Flask's dev server in production.
# -w 4     = 4 worker processes
# -b       = bind address
# --timeout = kill workers that take too long
# --access-logfile - = log to stdout (captured by Docker/CloudWatch)
CMD ["sh", "-c", \
     "python3 run.py"]

# Note: For true production, replace the CMD with:
# CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000",
#      "--timeout", "120", "--access-logfile", "-", "run:app"]
# Gunicorn doesn't call __main__ so START_LOOPBACK_SERVER won't fire.
# Use supervisord or a separate container for the loopback server in production.
