# Benchmarking Methodology

## Overview

This document defines precisely how TLS handshake performance is measured in this platform. Transparency about measurement methodology is essential for reproducible academic results.

---

## 1. What is Being Measured

### 1.1 Experiment Unit

Each **experiment** consists of:
- One or more **warmup runs** (discarded from statistics)
- N **measurement runs** (used for statistics)

Each **run** performs exactly one TLS handshake from a fresh TCP socket.

### 1.2 Handshake Latency

**Definition:** The elapsed wall-clock time from immediately before `ssl.wrap_socket()` is called until it returns successfully (indicating the TLS Finished message has been processed and session keys are derived).

**Timer used:** `time.monotonic()` — a high-resolution monotonic clock that never runs backward, making it safe for performance measurement. It is NOT affected by system clock adjustments (NTP, DST changes, etc.).

**Code:**
```python
t2 = time.monotonic()
ssl_sock = ssl_ctx.wrap_socket(
    raw_sock,
    server_hostname=sni,
    do_handshake_on_connect=True,   # blocks until TLS Finished
)
t3 = time.monotonic()
latency_ms = (t3 - t2) * 1000.0
```

**Precision:** Reported to 4 decimal places (0.0001 ms resolution).

### 1.3 What is Included in Handshake Latency

| Included? | Component |
|-----------|-----------|
| ✓ YES | TLS ClientHello construction and transmission |
| ✓ YES | Network round trip (client → server → client) |
| ✓ YES | ServerHello processing |
| ✓ YES | Key exchange computation (X25519 or ML-KEM) |
| ✓ YES | Certificate verification (if check_hostname=True) |
| ✓ YES | TLS Finished message exchange |
| ✗ NO | DNS resolution (performed before timing starts) |
| ✗ NO | TCP connection (timed separately as tcp_connect_ms) |
| ✗ NO | HTTP request/response after handshake |

### 1.4 TCP Connect Time

The TCP three-way handshake (SYN, SYN-ACK, ACK) is timed separately:
```python
t0 = time.monotonic()
raw_sock.connect((host, port))
t1 = time.monotonic()
tcp_connect_ms = (t1 - t0) * 1000.0
```

This is stored in the database but excluded from `latency_ms` and all statistical summaries. It is available in the individual `handshake_results` records if needed for analysis.

---

## 2. Byte Measurement

### 2.1 What We Can and Cannot Measure

Python's `ssl` module on OpenSSL 1.1.x does not expose TLS record-level byte counts through its public API. We therefore measure **application-layer bytes** only.

**bytes_sent:** Length (in bytes) of the HTTP GET request string sent after the handshake:
```
GET / HTTP/1.0\r\nHost: <host>\r\nConnection: close\r\n\r\n
```
This is approximately 40-60 bytes depending on the hostname length.

**bytes_received:** Length of the response data received (up to 4096 bytes).

### 2.2 What These Numbers Do NOT Represent

- **TLS record bytes** — TLS adds ~5 bytes of header per record; not included.
- **TCP/IP headers** — Not included.
- **Handshake-specific bytes** — The ClientHello, ServerHello, Certificate, and KeyShare messages are NOT captured by these counters.
- **Wire bytes** — Total bytes on the network wire would require packet capture (e.g., via `tcpdump` or Wireshark).

### 2.3 Implications

The byte measurements in this platform are useful for comparing relative overhead between modes within the same experimental setup, but should NOT be compared against published TLS record-level or packet-level measurements.

For accurate handshake byte sizes, refer to:
- TLS 1.3 RFC 8446 (classical handshake sizes)
- IETF drafts on hybrid key exchange handshake overhead
- Wireshark captures from controlled experiments

---

## 3. Statistical Summary

For each experiment, the following statistics are computed over successful measurement runs (warmup runs excluded):

| Statistic | Formula | Notes |
|-----------|---------|-------|
| Mean | `sum(x) / n` | Sensitive to outliers |
| Median | Middle value | Robust to outliers |
| Minimum | `min(x)` | Best-case latency |
| Maximum | `max(x)` | Worst-case latency |
| Standard deviation | `sqrt(Σ(x-mean)²/(n-1))` | Sample std (n-1 denominator) |
| Success rate | `successes / total × 100` | Includes warmup failures in denominator if they fail |

**Library:** Python's built-in `statistics` module (no third-party dependencies for basic stats).

---

## 4. Overhead Calculation

### 4.1 Formula (from project specification)

```
overhead_pct = ((alternative_metric - baseline_metric) / baseline_metric) × 100
```

Where:
- `baseline_metric` = mean latency of the **classical** experiment
- `alternative_metric` = mean latency of the PQC or hybrid experiment

### 4.2 Interpretation

| Result | Interpretation |
|--------|---------------|
| `overhead > 0` | Alternative is **slower** than classical |
| `overhead = 0` | Same performance |
| `overhead < 0` | Alternative is **faster** (improvement) |
| `overhead = None` | Baseline is zero, None, or not yet run |

### 4.3 When Overhead is Meaningful

The overhead calculation is only valid when:
1. Both experiments were run against the **same target host and port**
2. Both experiments were run with the **same network conditions** (ideally back-to-back)
3. The baseline experiment has `success_rate = 100%` and `mean_latency_ms > 0`
4. The number of repetitions is sufficient (≥ 10 recommended)

A warning is displayed when comparing experiments from different targets.

---

## 5. Warmup Runs

### 5.1 Purpose

Warmup runs allow:
- OS network stack to "warm up" (socket buffer allocation, routing cache)
- Python's bytecode compiler to JIT any hot paths
- TLS session cache at the server side (for session resumption scenarios)
- Stabilisation of timer resolution on some operating systems

### 5.2 Implementation

Warmup runs execute identical to measurement runs but are flagged `is_warmup=1` in the database. They are excluded from all statistical summaries. They ARE included in individual `handshake_results` records for transparency.

### 5.3 Recommended Settings

| Environment | Recommended warmups |
|-------------|-------------------|
| Loopback (127.0.0.1) | 2 |
| LAN | 3 |
| Internet | 5 |

---

## 6. Concurrency

When `concurrency > 1`, a `ThreadPoolExecutor` with `max_workers = concurrency` is used. Each thread independently opens a TCP socket, performs the TLS handshake, and records results.

**Implications:**
- Concurrent runs may contend for CPU, network bandwidth, or server resources.
- Mean latency under concurrency ≠ sequential mean latency (may be higher due to resource contention, or similar on a lightly loaded server).
- For fair comparison, use the same concurrency setting for all three modes.
- Default concurrency = 1 (sequential) for the most reproducible results.

---

## 7. Controlled Experimental Variables

To make comparisons valid, keep these fixed across mode comparisons:

| Variable | Recommendation |
|----------|---------------|
| Target host | Same for all modes |
| Target port | Same for all modes |
| Repetitions | Same for all modes (≥ 10) |
| Concurrency | Same for all modes |
| Warmup runs | Same for all modes |
| Network conditions | Run experiments within the same session |
| Server load | Minimise background traffic |

---

## 8. Known Limitations and Threats to Validity

### 8.1 Loopback Measurements
Experiments against `127.0.0.1` have latency < 1ms — much faster than real-world network conditions. This is useful for isolating cryptographic computation time but cannot represent realistic deployment performance.

### 8.2 Python GIL
Python's Global Interpreter Lock means threads do not run Python bytecode truly simultaneously. However, I/O operations (socket read/write) release the GIL, so concurrent TLS handshakes DO run in parallel at the OS level.

### 8.3 TLS Session Resumption
Each handshake is a **full handshake** (no session ticket reuse). Real-world TLS performance often relies heavily on session resumption (PSK), which would show significantly lower latency for repeat connections.

### 8.4 Group Verification
On OpenSSL 1.1.x, Python's `ssl` module does not expose the negotiated key-exchange group name. The reported group is inferred (classical: from cipher suite + TLS version) or set explicitly by context configuration (PQC: only with oqs-provider).

### 8.5 Certificate Verification
For loopback benchmarks, certificate verification is disabled (`CERT_NONE`). This removes certificate validation time from measurements. Production measurements should use proper certificate verification.

### 8.6 Single-machine experiments
Running client and server on the same machine shares CPU resources. For isolated benchmarks, run client and server on separate VMs.

---

## 9. References

- RFC 8446 — The Transport Layer Security (TLS) Protocol Version 1.3
- NIST FIPS 203 — Module-Lattice-Based Key-Encapsulation Mechanism Standard (ML-KEM)
- IETF draft-ietf-tls-hybrid-design — Hybrid key exchange in TLS 1.3
- Paquin, C. et al. "Benchmarking Post-Quantum Cryptography in TLS" (2020)
- Python `ssl` module documentation: https://docs.python.org/3/library/ssl.html
- Open Quantum Safe project: https://openquantumsafe.org
