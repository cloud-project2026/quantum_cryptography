# Architecture: Post-Quantum Cryptography Migration Platform

## System Overview

This document describes the architecture of the PQC Migration Platform — a cloud-ready benchmarking application that compares classical, post-quantum, and hybrid TLS key-exchange algorithms.

---

## Architecture Diagram

```mermaid
flowchart TD
    Browser["🌐 Browser\n(HTML/CSS/JS + Chart.js)"]

    subgraph Flask["Flask Application (run.py)"]
        direction TB
        MainBP["Main Blueprint\n/ → index.html\n/health → JSON"]
        ExpBP["Experiments API\nPOST /api/experiments/run\nGET /api/experiments/"]
        SysBP["System API\nGET /api/system/capabilities\nGET /api/system/status"]
        ResBP["Results API\nGET /api/results/compare\nGET /api/results/export"]
    end

    subgraph Services["Services Layer"]
        direction TB
        BenchEng["TLS Benchmark Engine\ntls_benchmark.py\n• ExperimentConfig\n• run_experiment()\n• _build_ssl_context()\n• _perform_single_handshake()"]
        CryptoCap["Crypto Capabilities\ncrypto_capabilities.py\n• OpenSSL version probe\n• PQC group detection\n• Mode availability"]
        Metrics["Metrics Service\nmetrics.py\n• compute_comparison()\n• calculate_overhead()\n• export_to_csv()"]
    end

    subgraph Storage["Storage"]
        DB[(SQLite\nexperiments.db\nhandshake_results)]
    end

    subgraph Benchmark["Benchmark Infrastructure"]
        Loopback["Loopback TLS Server\n127.0.0.1:54443\nSelf-signed cert\nTLS 1.3"]
        ExtServer["External TLS Server\nexample.com:443\n(internet, classical only)"]
    end

    Browser -->|HTTP GET /| MainBP
    Browser -->|REST API calls| ExpBP
    Browser -->|REST API calls| SysBP
    Browser -->|REST API calls| ResBP

    ExpBP --> BenchEng
    ExpBP --> CryptoCap
    SysBP --> CryptoCap
    ResBP --> Metrics
    ResBP --> DB

    BenchEng -->|ssl.wrap_socket()| Loopback
    BenchEng -->|ssl.wrap_socket()| ExtServer
    BenchEng --> DB
    Metrics --> DB
```

---

## Component Descriptions

### 1. Browser Frontend

**Files:** `app/templates/index.html`, `app/static/css/main.css`, `app/static/js/app.js`

A single-page application with six sections:
- **Overview** — server status, mode availability, latest experiment summary
- **Run Experiment** — mode selector, configuration form, live progress indicator
- **Compare Results** — side-by-side table, four Chart.js charts, overhead calculation
- **History** — paginated experiment list with detail modal, delete, and filter
- **System Info** — OpenSSL version, mode availability, setup instructions
- **Learn** — beginner-friendly explanations of TLS, PQC, ML-KEM, hybrid KEX

The frontend communicates exclusively through the REST API. It never performs TLS handshakes directly.

### 2. Flask Routes (Blueprints)

**Files:** `app/routes/`

Blueprints group related routes:

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `main_bp` | `/` | Serve HTML, `/health` endpoint |
| `experiments_bp` | `/api/experiments` | CRUD for experiments + run trigger |
| `system_bp` | `/api/system` | Capabilities + status |
| `results_bp` | `/api/results` | Comparison + export |

All API endpoints return JSON. Input validation is strict — invalid modes, out-of-range values, and SSRF-blocked hosts return `4xx` errors with descriptive messages.

### 3. TLS Benchmark Engine

**File:** `app/services/tls_benchmark.py`

The core measurement component. Key design decisions:

- **Monotonic timer** (`time.monotonic()`) for latency measurement — immune to system clock adjustments.
- **Timing scope**: TLS handshake only (TCP connect time measured separately and excluded).
- **No silent fallback**: if the requested TLS group cannot be configured, we raise `ValueError` and the experiment is recorded as failed.
- **Concurrent mode**: uses `ThreadPoolExecutor` — each thread opens its own socket and SSL connection independently.
- **Warmup runs**: discarded from statistics to exclude JIT compilation and cache cold-start effects.

**What is timed:**
```
t2 = time.monotonic()
ssl_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=sni, do_handshake_on_connect=True)
t3 = time.monotonic()
latency_ms = (t3 - t2) * 1000
```

**What is NOT timed:** DNS resolution, TCP SYN-ACK, HTTP response body.

### 4. Crypto Capabilities Detector

**File:** `app/services/crypto_capabilities.py`

Probes the live OpenSSL environment:
- Reads `ssl.OPENSSL_VERSION_INFO` to detect OpenSSL major version.
- Attempts `import oqs` to detect liboqs-python.
- Calls `ctx.set_ecdh_curve(group_name)` and catches errors to probe PQC group support.
- On OpenSSL 1.1.x: `x25519` is NOT set via `set_ecdh_curve` (it raises `ValueError`). X25519 availability is inferred from TLS 1.3 support instead.

### 5. Metrics Service

**File:** `app/services/metrics.py`

Pure functions (no database access) for:
- `calculate_overhead(baseline, alternative)` — returns percentage overhead, or `None` if baseline is zero/missing.
- `compute_comparison(classical, pqc, hybrid)` — builds the comparison JSON structure.
- `aggregate_latencies(list)` — mean, median, min, max, std.
- `export_to_csv(experiments)` — CSV string for download.

### 6. Database Layer

**File:** `app/models/database.py`

SQLite with two tables:
- `experiments` — one row per benchmark run (aggregated metrics)
- `handshake_results` — one row per individual TLS handshake

WAL (Write-Ahead Logging) mode enables concurrent reads while a write is in progress.

### 7. Loopback TLS Server

**File:** `benchmark/server/loopback_server.py`

A minimal TLS 1.3 server on `127.0.0.1:54443`. Generates a self-signed certificate at startup (using the `cryptography` library). Each accepted connection completes the TLS handshake, reads a GET request, sends an HTTP 200, and closes.

This server is separate from the Flask application, even though both run in the same process. The benchmark engine connects to it as a real TCP client — this ensures we measure a genuine TLS handshake, not a function call.

---

## Data Flow: Running an Experiment

```
1. User clicks "Start Benchmark" in the browser
2. Browser POSTs to /api/experiments/run with mode/config JSON
3. Flask validates: mode ∈ {classical, pqc, hybrid},
                   host ∈ ALLOWED_BENCHMARK_HOSTS, reps ≤ 200, etc.
4. Capability check: is the requested mode available on this OpenSSL?
   → If not: return HTTP 422 with error_summary
5. SSL context built: _build_ssl_context(mode)
   → Classical: context uses TLS 1.3, no explicit group set (x25519 default)
   → PQC/hybrid: set_ecdh_curve(group) — raises ValueError if oqs-provider absent
6. Warmup runs execute (discarded from statistics)
7. Measurement runs execute (sequential or thread-pooled)
8. Results aggregated: mean/median/min/max/std/success_rate
9. Persisted to SQLite (experiments + handshake_results tables)
10. JSON response returned to browser (HTTP 201)
11. Browser updates result grid and shows success/error alert
```

---

## Security Design

| Concern | Mitigation |
|---------|-----------|
| SSRF | Only hosts in `ALLOWED_BENCHMARK_HOSTS` are accepted as targets |
| Credential exposure | Secrets via env vars only; never in code or git |
| Arbitrary code execution | All inputs validated; no `eval`/`exec` |
| DoS (repetitions) | `MAX_REPETITIONS=200`, `MAX_CONCURRENCY=20` limits |
| Container security | Non-root user in Dockerfile |
| Production server | Gunicorn (not Flask dev server) in production |

---

## Deployment Architecture (Cloud)

```
Internet
   │
   ▼
AWS Security Group (port 443 open)
   │
   ▼
EC2 Ubuntu 22.04
   │
   ├── Nginx reverse proxy (HTTPS termination + Let's Encrypt)
   │     │
   │     ▼
   │   Docker container (pqc-lab)
   │     ├── Gunicorn (4 workers)
   │     ├── Flask application
   │     ├── Loopback TLS server (127.0.0.1:54443)
   │     └── SQLite volume mount
   │
   └── (Optional) Separate Docker container for PQC test server
         with OQS-enabled OpenSSL
```

The TLS benchmarking connection is from the Flask application **to** the loopback server inside the same container — not from the browser to Flask. This means the measured TLS connection is the one whose cryptographic mode is being tested, not the browser-to-Flask connection.
