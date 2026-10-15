# Setup Guide

## Local Development Setup (Windows / Mac / Linux)

### 1. Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.10 | 3.11+ |
| pip | 23.x | latest |
| RAM | 512 MB | 1 GB |
| Disk | 200 MB | 500 MB |
| OS | Any | Ubuntu 22.04 for PQC |

### 2. Clone and Install

```bash
git clone <your-repo-url>
cd post-quantum-migration

# Create virtual environment (isolates dependencies from your system Python)
python -m venv venv

# Activate it
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Windows CMD:
.\venv\Scripts\activate.bat
# Linux / Mac:
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy the example file
cp .env.example .env
```

The defaults in `.env.example` work for local development. You only need to change:
- `SECRET_KEY` — for any deployment that others can reach
- `ALLOWED_BENCHMARK_HOSTS` — add more hosts if you want to benchmark external servers

### 4. Run the Application

```bash
python run.py
```

Expected output:
```
INFO: Database initialised at results/experiments.db
INFO: Self-signed cert generated at C:\...\pqc_bench_xxxx
INFO: Loopback TLS server listening on 127.0.0.1:54443
INFO: Loopback TLS server started on 127.0.0.1:54443
INFO: PQC Migration Platform started. ENV=development
INFO: Starting Flask on http://0.0.0.0:5000
 * Running on http://127.0.0.1:5000
```

Open **http://localhost:5000** in your browser.

### 5. Run Tests

```bash
# All tests (unit + integration + real TLS)
python -m pytest tests/ -v

# Just unit tests (no network required)
python -m pytest tests/ -v -k "not TLS and not RoundTrip"

# With coverage report
pip install pytest-cov
python -m pytest tests/ --cov=app --cov-report=html
```

Expected result: **55 passed** in ~2 seconds.

---

## What Works on Windows (OpenSSL 1.1.x)

| Feature | Works? | Notes |
|---------|--------|-------|
| Mode A — Classical TLS | ✅ Yes | X25519 via TLS 1.3 |
| Mode B — PQC TLS | ❌ No | Requires oqs-provider (Linux/Docker) |
| Mode C — Hybrid TLS | ❌ No | Requires oqs-provider (Linux/Docker) |
| Dashboard UI | ✅ Yes | Fully functional |
| History & export | ✅ Yes | CSV/JSON download |
| System info page | ✅ Yes | Shows what's available |
| Real TLS 1.3 handshakes | ✅ Yes | Against loopback server |
| All 55 tests passing | ✅ Yes | |

Modes B and C correctly display **"Not Available"** with setup instructions. This is the honest, expected behaviour — not a bug.

---

## Enabling PQC Modes (Ubuntu 22.04 / Docker)

### Option A: Use Docker (recommended — easiest)

The Docker container is based on Ubuntu 22.04 which ships with OpenSSL 3.0. After running the oqs-provider setup script inside the container, all three modes become available.

```bash
# Build and run
docker compose up --build

# Once running, exec into the container
docker compose exec pqc-app bash

# Install oqs-provider (takes ~10 minutes)
bash /app/scripts/install_oqs_provider.sh

# Restart the app
exit
docker compose restart pqc-app
```

### Option B: Ubuntu 22.04 VM / WSL2

```bash
# Check your OpenSSL version first
openssl version   # should be 3.0.x or later

# Run the install script
sudo bash scripts/install_oqs_provider.sh

# Verify
openssl list -providers
# Should show: oqsprovider

# Run the platform
python run.py
```

### Option C: WSL2 on Windows

Windows Subsystem for Linux with Ubuntu 22.04 works well:

```bash
# In WSL2 Ubuntu 22.04
sudo apt update
git clone <your-repo>
cd post-quantum-migration

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install oqs-provider
sudo bash scripts/install_oqs_provider.sh

python3 run.py
```

Access via http://localhost:5000 — WSL2 forwards ports to Windows automatically.

---

## Understanding OpenSSL Versions

This is a common source of confusion for students, so here is a clear explanation:

### Why does the OpenSSL version matter?

Python's `ssl` module is a thin wrapper around the system's OpenSSL library. The algorithms available depend entirely on which OpenSSL is installed — not Python itself.

```
Python 3.10 (Windows) → ssl module → OpenSSL 1.1.1t (built into Python)
Python 3.10 (Ubuntu 22.04) → ssl module → OpenSSL 3.0.x (system library)
```

### What each version supports

| OpenSSL Version | TLS 1.3 | X25519 | ML-KEM (native) | oqs-provider |
|----------------|---------|--------|-----------------|-------------|
| 1.0.x | ❌ | ❌ | ❌ | ❌ |
| 1.1.1 | ✅ | ✅ | ❌ | ❌ |
| 3.0.x | ✅ | ✅ | ❌ | ✅ Supported |
| 3.3.x | ✅ | ✅ | ✅ Native | ✅ Supported |

### Why Python on Windows uses OpenSSL 1.1.1

The Windows Python installer bundles its own copy of OpenSSL 1.1.1 for portability. It does not use the system's OpenSSL (if any). This means PQC is not available on Windows Python without additional setup.

The `get_openssl_version()` function in our platform reads `ssl.OPENSSL_VERSION_INFO` to detect this accurately.

---

## Project Dependency Explanations

| Package | Purpose | Why we need it |
|---------|---------|----------------|
| `flask` | Web framework | Handles HTTP requests, routing, templating |
| `flask-cors` | CORS headers | Allows browser JS to call the API |
| `python-dotenv` | .env file loading | Reads environment variables from .env |
| `cryptography` | TLS cert generation | Creates self-signed cert for loopback server |
| `gunicorn` | Production WSGI server | Replaces Flask dev server in production |
| `requests` | HTTP client | Used in testing and health checks |
| `psutil` | System metrics | Used in status endpoint for system info |
| `pytest` | Testing | Runs the test suite |
| `pytest-asyncio` | Async test support | Needed for async test fixtures |

All dependencies are pure Python except `cryptography` which has compiled C extensions (pre-built wheels available for all platforms via pip).

---

## File Structure Quick Reference

```
post-quantum-migration/
├── app/                    ← Flask application code
│   ├── __init__.py         ← App factory (create_app)
│   ├── routes/             ← URL handlers
│   ├── services/           ← Business logic
│   ├── models/             ← Database code
│   ├── templates/          ← HTML templates
│   └── static/             ← CSS, JS, images
├── benchmark/
│   └── server/
│       └── loopback_server.py   ← Built-in TLS test server
├── tests/
│   └── test_platform.py    ← 55 tests
├── docs/                   ← This documentation
├── scripts/
│   └── install_oqs_provider.sh  ← PQC enablement script
├── results/                ← SQLite database (gitignored)
├── run.py                  ← Start here
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```
