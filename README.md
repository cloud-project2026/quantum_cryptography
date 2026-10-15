# Post-Quantum Cryptography Migration: A Cloud-Based TLS Performance Evaluation Platform

> **Academic research project** — Second-year CS coursework  
> Compares classical, post-quantum, and hybrid TLS key-exchange algorithms through real TLS handshake benchmarking.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Problem Statement](#problem-statement)
3. [Objectives](#objectives)
4. [Architecture](#architecture)
5. [Technology Stack](#technology-stack)
6. [Prerequisites](#prerequisites)
7. [Local Setup](#local-setup)
8. [Running the Application](#running-the-application)
9. [Running Experiments](#running-experiments)
10. [Interpreting Results](#interpreting-results)
11. [Cloud Deployment](#cloud-deployment)
12. [Troubleshooting](#troubleshooting)
13. [Current Limitations](#current-limitations)
14. [Project Structure](#project-structure)

---

## Project Overview

This platform benchmarks TLS 1.3 handshake performance across three cryptographic modes:

| Mode | Algorithm | Quantum Resistant? | Status on this machine |
|------|-----------|-------------------|------------------------|
| **Mode A — Classical** | X25519 ECDH | ✗ Vulnerable | ✅ Always available |
| **Mode B — Post-Quantum** | ML-KEM-768 (NIST FIPS 203) | ✓ Yes | ⚠ Requires oqs-provider |
| **Mode C — Hybrid** | X25519 + ML-KEM-768 | ✓ Yes | ⚠ Requires oqs-provider |

Results are stored in SQLite, visualised with Chart.js charts, and exportable as CSV or JSON.

---

## Problem Statement

Current internet encryption relies on algorithms (RSA, ECDH) that quantum computers can break using Shor's algorithm. Even today, adversaries can record encrypted traffic and decrypt it later once quantum computers mature — the **"Harvest Now, Decrypt Later"** threat.

Organisations need real performance data to plan migration to post-quantum algorithms without introducing unacceptable latency or compatibility issues.

---

## Objectives

1. Build a real TLS benchmarking platform (not a simulation).
2. Measure handshake latency, byte overhead, and success rates.
3. Compare classical vs. post-quantum vs. hybrid modes.
4. Calculate migration overhead using the formula: `((PQC - Classical) / Classical) × 100%`.
5. Deploy in a cloud-ready Docker container.
6. Provide honest reporting — never claim PQC works without verifying it.

---

## Architecture

```
Browser
  │
  ▼
Flask Dashboard (HTML/CSS/JS + Chart.js)
  │
  ▼
Flask REST API  (/api/experiments, /api/results, /api/system)
  │
  ├── TLS Benchmark Engine  ──► Loopback TLS Server (127.0.0.1:54443)
  │      (real ssl.wrap_socket()       (self-signed cert, TLS 1.3)
  │       with monotonic timer)
  │
  ├── Crypto Capabilities Detector
  │      (probes OpenSSL, oqs-provider)
  │
  └── SQLite Database  (results/experiments.db)
```

See `docs/architecture.md` for the Mermaid diagram and full component descriptions.

---

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend | Python + Flask | 3.10.11 + 3.0.3 |
| Frontend | HTML/CSS/JavaScript | Vanilla |
| Charts | Chart.js | 4.4.4 (CDN) |
| Crypto | Python ssl + OpenSSL | 1.1.1t (local) |
| Post-Quantum | oqs-provider (optional) | Requires OpenSSL 3.x |
| Database | SQLite | Built-in |
| Container | Docker + Ubuntu 22.04 | — |
| WSGI Server | Gunicorn | 22.0.0 |
| Testing | pytest | 8.3.3 |

---

## Prerequisites

**Local development (Windows/Mac/Linux):**
- Python 3.10 or later
- pip
- Git

**Cloud deployment:**
- Docker Engine 24+
- An AWS EC2 instance (Ubuntu 22.04 LTS, t3.small or larger)
- AWS CLI configured with appropriate permissions

**For PQC modes (Modes B and C):**
- Ubuntu 22.04 or later (or Docker)
- OpenSSL 3.x (default on Ubuntu 22.04)
- OQS Provider installed (see `docs/setup.md`)

---

## Local Setup

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd post-quantum-migration

# 2. Create and activate a virtual environment (recommended)
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env if needed (defaults work for local development)

# 5. Ensure the results directory exists
mkdir -p results
```

---

## Running the Application

```bash
# Start the app (development mode)
python run.py
```

You should see:
```
INFO: Loopback TLS server started on 127.0.0.1:54443
INFO: Starting Flask on http://0.0.0.0:5000
```

Open your browser at: **http://localhost:5000**

### Health check
```bash
curl http://localhost:5000/health
```
Expected response: `{"status": "healthy", "database_ok": true, ...}`

---

## Running Experiments

### Via the Dashboard
1. Open http://localhost:5000
2. Click **Run Experiment** in the sidebar
3. Select **Mode A — Classical** (always available)
4. Set target host to `127.0.0.1`, port `54443` (the built-in loopback server)
5. Set repetitions to 10, warmup to 2
6. Click **Start Benchmark**
7. View results in **Compare Results**

### Via the API
```bash
# Run a classical TLS experiment
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

# Check results
curl http://localhost:5000/api/results/compare

# Export as CSV
curl http://localhost:5000/api/results/export?fmt=csv -o results.csv
```

### Enabling PQC Modes
PQC and hybrid modes require OpenSSL 3.x + oqs-provider. On this Windows machine with OpenSSL 1.1.1t, they will correctly report as **Unsupported**. See `docs/setup.md` for the Ubuntu/Docker setup procedure.

---

## Interpreting Results

### Latency (ms)
- **Mean latency**: average TLS handshake time across all measurement runs
- **Std deviation**: how consistent the measurements are (lower = more stable)
- Loopback measurements will be < 1ms; internet measurements will be 20-200ms

### Handshake Overhead (%)
```
Overhead = ((PQC_latency - Classical_latency) / Classical_latency) × 100
```
- **Positive %** = PQC/hybrid is slower (expected for larger key material)
- **Negative %** = PQC/hybrid is faster (improvement)
- Values of 5-30% overhead for ML-KEM are typical in published literature

### Negotiated Group
- `x25519 (inferred)` — X25519 was used (inferred from TLS 1.3 cipher; Python's ssl module on OpenSSL 1.1.x does not expose the exact group name via API)
- `mlkem768` — confirmed ML-KEM-768 (only when oqs-provider is loaded)
- `x25519_mlkem768` — confirmed hybrid (only when oqs-provider is loaded)

### What the platform does NOT measure
- Post-quantum authentication (certificates are still classical RSA/ECDSA)
- Wire-level byte counts (we measure application-layer bytes)
- DNS resolution time (excluded from latency)

---

## Cloud Deployment

### Quick start (AWS EC2)
```bash
# 1. Launch Ubuntu 22.04 t3.small EC2 instance
# 2. SSH into the instance
ssh -i your-key.pem ubuntu@<ec2-public-ip>

# 3. Run the cloud setup script
curl -sSL https://raw.githubusercontent.com/<your-repo>/main/scripts/cloud_setup.sh | bash

# 4. Start the application
cd post-quantum-migration
docker compose up -d

# 5. Verify
curl http://<ec2-public-ip>:5000/health
```

See `docs/cloud-deployment.md` for the complete guide including security groups, HTTPS setup, and teardown.

---

## Troubleshooting

### App won't start
- Check Python version: `python --version` (must be 3.10+)
- Check pip packages: `pip install -r requirements.txt`
- Check port conflict: `netstat -ano | findstr :5000` (Windows)

### "Mode not available" for PQC/hybrid
- Expected on OpenSSL 1.1.x — see **System Info** page in the dashboard
- Fix: use Docker/Ubuntu 22.04 and install oqs-provider

### Loopback server not responding
- The loopback server starts automatically with `python run.py`
- If port 54443 is in use, set `START_LOOPBACK_SERVER=false` in `.env` and use an external server

### All handshakes fail
- Check that `127.0.0.1` is in `ALLOWED_BENCHMARK_HOSTS` in `.env`
- Verify the loopback server started (check console logs)

### ImportError: No module named 'app'
- Run from the project root directory: `cd post-quantum-migration && python run.py`

See `docs/troubleshooting.md` for more.

---

## Current Limitations

1. **PQC modes require additional setup** — OpenSSL 1.1.x (bundled with Python on Windows) does not support ML-KEM. A Linux VM or Docker container with oqs-provider is needed.

2. **Group name not verified on OpenSSL 1.1.x** — Python's `ssl` module does not expose the negotiated TLS key-exchange group name via its public API on this OpenSSL version. The group is inferred, not confirmed.

3. **Loopback measurements are sub-millisecond** — Benchmarks against `127.0.0.1` are unrealistically fast. For meaningful comparisons, deploy a separate TLS server on a cloud VM.

4. **No post-quantum authentication** — Only key exchange is post-quantised. Certificate signatures use classical RSA/ECDSA. Full PQC authentication would require post-quantum signature algorithms (FIPS 204/205).

5. **Synchronous experiment execution** — The API blocks while the experiment runs. Large experiments (200 reps × 20 concurrency) may trigger browser timeouts. A task queue (Celery/RQ) would fix this for production.

6. **No TLS session resumption** — Each handshake is a full handshake. Real-world TLS often uses session tickets/PSK resumption, which would show different latency profiles.

---

## Project Structure

```
post-quantum-migration/
├── app/                          # Flask application
│   ├── __init__.py               # App factory
│   ├── routes/
│   │   ├── main.py               # Index + /health
│   │   ├── api_experiments.py    # POST/GET /api/experiments
│   │   ├── api_results.py        # GET /api/results
│   │   └── api_system.py         # GET /api/system
│   ├── services/
│   │   ├── tls_benchmark.py      # TLS handshake engine ★
│   │   ├── crypto_capabilities.py# OpenSSL/PQC detection ★
│   │   └── metrics.py            # Stats + overhead calculations ★
│   ├── models/
│   │   └── database.py           # SQLite schema + connection
│   └── templates/
│       └── index.html            # Single-page dashboard
├── benchmark/
│   └── server/
│       └── loopback_server.py    # Local TLS 1.3 test server
├── tests/
│   └── test_platform.py          # 55 tests (unit + integration + TLS)
├── docs/                         # Documentation
├── scripts/
│   └── cloud_setup.sh            # EC2/Ubuntu setup script
├── results/                      # SQLite DB (gitignored)
├── Dockerfile                    # Ubuntu 22.04 based
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── run.py                        # Entry point
└── README.md
```
