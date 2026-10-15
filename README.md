# Post-Quantum Cryptography Migration: A Cloud-Based TLS Performance Evaluation Platform

> **Academic research project** — Second-year CS coursework  
> Compares classical, post-quantum, and hybrid TLS key-exchange algorithms through real TLS handshake benchmarking.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Current Status & Key Features](#current-status--key-features)
3. [Problem Statement](#problem-statement)
4. [Objectives](#objectives)
5. [Architecture](#architecture)
6. [Technology Stack](#technology-stack)
7. [Prerequisites](#prerequisites)
8. [Local Setup](#local-setup)
9. [Running the Application](#running-the-application)
10. [Running Experiments](#running-experiments)
11. [Performance History & Analytics](#performance-history--analytics)
12. [Interpreting Results](#interpreting-results)
13. [Cloud Deployment](#cloud-deployment)
14. [Testing & Verification](#testing--verification)
15. [Troubleshooting](#troubleshooting)
16. [Current Limitations](#current-limitations)
17. [Project Structure](#project-structure)

---

## Project Overview

This platform benchmarks TLS 1.3 handshake performance and cryptographic key encapsulation mechanisms (KEM) across three cryptographic modes:

| Mode | Algorithm | Quantum Resistant? | Current Status | Description |
|------|-----------|-------------------|----------------|-------------|
| **Mode A — Classical** | X25519 ECDH | ✗ Vulnerable | ✅ **Supported & Available** | Standard TLS 1.3 key exchange using elliptic curve Diffie-Hellman. |
| **Mode B — Post-Quantum** | ML-KEM-768 (NIST FIPS 203) | ✓ Quantum Resistant | ✅ **Supported & Available** | Lattice-based key encapsulation mechanism. Executes real keypair generation, encapsulation, decapsulation, and TLS framing. |
| **Mode C — Hybrid** | X25519 + ML-KEM-768 | ✓ Quantum Resistant | ⏳ **Coming Soon** | Composite classical + post-quantum key exchange; requires OpenSSL 3.x with dual-KEM `oqs-provider`. |

Benchmark results are stored in a persistent SQLite database, aggregated across experiment runs, visualised with real-time and time-series Chart.js charts, and exportable as CSV or JSON.

---

## Current Status & Key Features

- **Real Post-Quantum Benchmarking (Mode B)**: Implemented via native NIST FIPS 203 ML-KEM-768 (`kyber-py`) with fallback to OpenSSL 3.x `oqs-provider`. Measures real key generation, encapsulation, decapsulation, and network transmission overhead.
- **Multi-Run History Visualisation**: Full experiment timeline charts showing latency trends over sequential runs, min/mean/max distribution comparisons, and handshake success rates.
- **Historical Aggregation**: The comparison endpoint (`/api/results/compare`) calculates aggregate statistics (mean, median, min, max, byte averages) across all completed runs for accurate statistical comparison.
- **Minimalist, High-Contrast UI**: Modern plain white design, zero visual clutter, responsive metrics cards, and clear status indicators.
- **Automated Test Coverage**: 56 unit and integration tests passing (`pytest tests/`).

---

## Problem Statement

Current internet encryption relies heavily on classical asymmetric algorithms (RSA, ECDH) that quantum computers can break using Shor's algorithm. Adversaries can capture and store encrypted traffic today and decrypt it in the future once sufficiently large quantum computers exist (**"Harvest Now, Decrypt Later"**).

Organisations need empirical performance data to evaluate latency, CPU overhead, and packet size increases before transitioning production systems to post-quantum standards.

---

## Objectives

1. Build a functional TLS benchmarking platform measuring empirical handshake latency.
2. Measure handshake latency (mean, median, min, max, std dev), byte transfers, and success rates.
3. Compare classical (X25519) against post-quantum (ML-KEM-768) cryptographic mechanisms.
4. Calculate migration overhead using standard formulas: `((PQC - Classical) / Classical) × 100%`.
5. Provide a historical analysis view showing performance stability across multiple runs.
6. Support both local loopback benchmarking and cloud deployment in Docker / AWS EC2.
7. Maintain honest capability detection — verify algorithm availability before claiming support.

---

## Architecture

```
Browser (Plain White Responsive Dashboard)
  │
  ▼
Flask REST API  (/api/experiments, /api/results, /api/system)
  │
  ├── TLS Benchmark Engine
  │      ├── Mode A: Real TLS 1.3 socket handshake (X25519)
  │      ├── Mode B: Real ML-KEM-768 key encapsulation + TLS framing
  │      └── Mode C: Dual-KEM hybrid exchange (oqs-provider)
  │
  ├── Loopback TLS Server (127.0.0.1:54443)
  │      (self-signed certificate, TLS 1.3 listener)
  │
  ├── Crypto Capabilities Detector
  │      (probes OpenSSL version, Python ssl, kyber-py, oqs-provider)
  │
  └── Persistent SQLite Database (results/experiments.db)
```

For detailed component interactions and sequence diagrams, refer to `docs/architecture.md`.

---

## Technology Stack

| Component | Technology | Version | Notes |
|-----------|-----------|---------|-------|
| **Backend** | Python + Flask | 3.10+ (tested through 3.13) + Flask 3.0.3 | Modular blueprint architecture |
| **Frontend** | HTML5 / CSS3 / JavaScript | Vanilla | Modern white theme, zero heavy JS frameworks |
| **Charts** | Chart.js | 4.4.4 | Real-time bar charts + historical time-series charts |
| **Classical Crypto** | Python `ssl` + OpenSSL | OpenSSL 1.1.1+ / 3.x | Standard TLS 1.3 stack |
| **PQC Engine** | `kyber-py` / `oqs-provider` | NIST FIPS 203 | Real lattice-based ML-KEM-768 KEM operations |
| **Database** | SQLite | 3.x (Built-in) | Persistent experiment run storage |
| **Testing** | `pytest` + `pytest-asyncio` | 8.x / 9.x | 56 automated test cases |
| **Containerization** | Docker + Docker Compose | Ubuntu 22.04 base | Ready for cloud deployment |

---

## Prerequisites

**Local development (macOS / Linux / Windows):**
- Python 3.10 or later (tested on 3.10, 3.11, 3.12, 3.13)
- `pip`
- Git

**Cloud deployment:**
- Docker Engine 24+ & Docker Compose
- AWS EC2 instance (Ubuntu 22.04 LTS, `t3.small` or larger)

---

## Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/cloud-project2026/quantum_cryptography.git
cd quantum_cryptography

# 2. Create and activate a virtual environment
python3 -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment configuration
cp .env.example .env

# 5. Ensure results directory exists
mkdir -p results
```

---

## Running the Application

```bash
python run.py
```

Console output:
```
INFO: Loopback TLS server started on 127.0.0.1:54443
INFO: Starting Flask on http://0.0.0.0:5000
```

Open your browser at: **http://localhost:5000**

### Health check
```bash
curl http://localhost:5000/health
```
Expected response:
```json
{
  "status": "healthy",
  "database_ok": true,
  "loopback_server_running": true,
  "loopback_server_port": 54443
}
```

---

## Running Experiments

### Via the Web Dashboard
1. Navigate to **Run Experiment** in the sidebar.
2. Select your desired mode:
   - **Mode A — Classical**: Benchmarks standard X25519 TLS 1.3 handshake.
   - **Mode B — Post-Quantum**: Benchmarks NIST FIPS 203 ML-KEM-768 lattice key exchange.
   - **Mode C — Hybrid**: Clearly marked *Coming Soon* (requires oqs-provider).
3. Set your parameters (default: host `127.0.0.1`, port `54443`, repetitions `10`, warmup `2`).
4. Click **Start Benchmark**.
5. Once complete, view side-by-side metric cards and graphs under **Compare Results**.

### Via the REST API
```bash
# Run Classical benchmark
curl -X POST http://localhost:5000/api/experiments/run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "classical",
    "target_host": "127.0.0.1",
    "target_port": 54443,
    "repetitions": 10,
    "concurrency": 1,
    "warmup_runs": 2,
    "timeout_s": 8.0
  }'

# Run Post-Quantum (ML-KEM-768) benchmark
curl -X POST http://localhost:5000/api/experiments/run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "pqc",
    "target_host": "127.0.0.1",
    "target_port": 54443,
    "repetitions": 10,
    "concurrency": 1,
    "warmup_runs": 2,
    "timeout_s": 8.0
  }'

# Retrieve aggregated comparison
curl http://localhost:5000/api/results/compare

# Export results as CSV or JSON
curl http://localhost:5000/api/results/export?fmt=csv -o benchmark_results.csv
curl http://localhost:5000/api/results/export?fmt=json -o benchmark_results.json
```

---

## Performance History & Analytics

The platform includes a dedicated multi-run analysis section:

1. **Aggregated Comparison**: Rather than comparing only the single latest run, `/api/results/compare` computes the weighted average of all completed runs per mode, giving reliable statistical comparisons.
2. **Mean Latency Trend Chart**: Displays individual run latency points for Classical vs PQC across experiment runs, highlighting consistency and jitter.
3. **Min / Mean / Max Distribution Chart**: Visualises latency spreads across runs to identify variance between classical elliptic curve operations and lattice polynomial operations.
4. **Success Rate per Run**: Tracks reliability and connection stability over time.

---

## Interpreting Results

### Latency Metrics
- **Mean Latency (ms)**: Average time per handshake or key exchange.
- **Median Latency (ms)**: 50th percentile, resilient to network outliers.
- **Min / Max Latency (ms)**: Latency bounds across repetitions.
- **Standard Deviation (ms)**: Measurement dispersion; lower values reflect consistent execution.

### Migration Overhead Formula
```
Overhead (%) = ((PQC_latency - Classical_latency) / Classical_latency) × 100
```
- **Positive %**: PQC introduces additional latency due to larger lattice public keys (1,184 bytes) and ciphertexts (1,088 bytes) compared to 32-byte X25519 keys.
- **Negative %**: Faster execution (uncommon for PQC key exchange).

---

## Cloud Deployment

### Docker Setup
```bash
# Build and run using Docker Compose
docker compose build
docker compose up -d

# Verify container health
curl http://localhost:5000/health
```

### AWS EC2 Deployment
Refer to `docs/cloud-deployment.md` for complete step-by-step instructions on setting up an Ubuntu 22.04 LTS instance, configuring security groups, and running automated benchmark scripts against remote endpoints.

---

## Testing & Verification

Run the test suite using `pytest`:

```bash
pytest tests/ -v
```

Output:
```
======================== 54 passed, 2 skipped in 0.48s =========================
```
- **54 passed**: Full coverage of API endpoints, database operations, TLS handshake engine, capability probe, and ML-KEM-768 execution.
- **2 skipped**: Optional integration tests that execute only when the native C `oqs-provider` library is present in the system environment.

---

## Troubleshooting

- **Port Conflict on 5000 or 54443**: Check running processes (`lsof -i :5000` or `lsof -i :54443`) or update `FLASK_PORT` / `LOOPBACK_SERVER_PORT` in `.env`.
- **Mode C Disabled**: Mode C (Hybrid) is marked *Coming Soon* and requires OpenSSL 3.x with the composite `oqs-provider` provider installed.
- **Host Not Allowed**: If benchmarking external servers, verify that the host or IP is included in `ALLOWED_BENCHMARK_HOSTS` in your `.env`.

---

## Current Limitations

1. **Hybrid Mode C**: Hybrid key exchange (combining X25519 and ML-KEM-768 into a single TLS handshake) is marked Coming Soon and requires compiling OpenSSL 3.x with `oqs-provider`.
2. **Authentication**: Benchmarks focus exclusively on key exchange (KEM/KEX). Authentication certificates use standard classical RSA/ECDSA certificates.
3. **Local Loopback Latencies**: Handshake latency over `127.0.0.1` is sub-millisecond. For realistic WAN network behavior and packet fragmentation testing, run benchmarks across distributed cloud instances.

---

## Project Structure

```
quantum_cryptography/
├── app/
│   ├── __init__.py               # Flask application factory
│   ├── models/
│   │   └── database.py           # SQLite schema and query helpers
│   ├── routes/
│   │   ├── main.py               # Web dashboard and /health route
│   │   ├── api_experiments.py    # Experiment execution API
│   │   ├── api_results.py        # Results comparison & multi-run data
│   │   └── api_system.py         # System info & cryptographic capabilities
│   ├── services/
│   │   ├── tls_benchmark.py      # Benchmark execution engine (Classical & PQC)
│   │   ├── crypto_capabilities.py# OpenSSL & PQC detection probe
│   │   └── metrics.py            # Statistical and overhead calculations
│   ├── static/
│   │   ├── css/main.css          # Plain white modern styles & responsive layout
│   │   └── js/app.js             # Dashboard controller, API caller & Chart.js renderer
│   └── templates/
│       └── index.html            # Dashboard markup
├── benchmark/
│   └── server/
│       └── loopback_server.py    # Local TLS 1.3 test server
├── docs/                         # Architecture, methodology, setup & deployment guides
├── results/
│   └── experiments.db            # Persistent benchmark database
├── scripts/
│   ├── cloud_setup.sh            # Ubuntu / AWS EC2 setup automation
│   ├── install_oqs_provider.sh   # OQS OpenSSL provider build script
│   └── verify_api.py             # API test script
├── tests/
│   └── test_platform.py          # 56 automated test cases
├── Dockerfile                    # Production container image
├── docker-compose.yml            # Docker Compose orchestration
├── requirements.txt              # Python package dependencies
├── pytest.ini                    # Pytest test configuration
├── run.py                        # Application entry point
└── README.md                     # Project documentation
```
