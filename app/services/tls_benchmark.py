"""
TLS Benchmark Engine
====================

This is the heart of the project. It performs actual TLS handshakes and
measures how long they take.

How a TLS handshake works (beginner explanation):
─────────────────────────────────────────────────
When you visit https://example.com, before any page data flows, your browser
and the server run through a handshake:

  1. Client Hello  — "I speak TLS 1.3, here are my supported key-exchange groups"
  2. Server Hello  — "Great, let's use X25519 (or ML-KEM-768, etc.)"
  3. Key exchange  — Both sides compute the same shared secret without sending it
  4. Finished      — Authentication certificates verified, keys derived

This handshake takes 1–5 ms on a local network, 50–200 ms across the internet.
The key-exchange step is where classical vs. post-quantum algorithms differ.

What we measure:
  • Handshake latency  — time from ssl.wrap_socket() call to its completion
                         (TCP connect time is captured separately and excluded)
  • Bytes sent         — size of the HTTP request we send post-handshake
                         (Python ssl module does not expose TLS record bytes directly)
  • Negotiated TLS version — extracted from ssl.SSLSocket.version()
  • Negotiated group   — x25519 is inferred; PQC group only readable with oqs-provider

What is NOT included in handshake latency:
  • DNS resolution (we resolve the host before timing starts)
  • TCP three-way handshake (timed separately as tcp_connect_ms)
  • Application HTTP response time (we don't wait for a full response body)

OpenSSL 1.1.x note:
  - set_ecdh_curve('x25519') raises ValueError on 1.1.x (x25519 is built-in, not
    a named EC curve in that API). For classical mode we do NOT call set_ecdh_curve;
    X25519 is automatically used by OpenSSL 1.1.x for TLS 1.3 key exchange.
  - For PQC/hybrid modes we do call set_ecdh_curve with the OQS group name, and
    if that fails we raise a ValueError (no silent fallback).
"""

import ssl
import socket
import time
import threading
import logging
import statistics
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HandshakeResult:
    """Stores the outcome of one individual TLS handshake attempt."""
    run_index: int
    is_warmup: bool
    started_at: str            # ISO-8601 timestamp
    success: bool
    latency_ms: Optional[float] = None
    tcp_connect_ms: Optional[float] = None
    bytes_sent: Optional[int] = None
    bytes_received: Optional[int] = None
    tls_version: Optional[str] = None
    tls_group: Optional[str] = None
    cipher_suite: Optional[str] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentConfig:
    """Configuration for one benchmark run."""
    mode: str                          # 'classical', 'pqc', 'hybrid'
    target_host: str = "127.0.0.1"
    target_port: int = 54443
    repetitions: int = 10
    concurrency: int = 1
    warmup_runs: int = 2
    timeout_s: float = 10.0
    server_name: Optional[str] = None  # SNI; defaults to target_host

    def __post_init__(self):
        if self.server_name is None:
            self.server_name = self.target_host


@dataclass
class ExperimentSummary:
    """Aggregated results from all handshake attempts in one experiment."""
    config: ExperimentConfig
    results: List[HandshakeResult]
    openssl_version: str
    started_at: str
    finished_at: str
    status: str                        # 'completed', 'failed', 'partial'
    error_summary: Optional[str] = None

    # Aggregate stats (computed after runs finish)
    mean_latency_ms: Optional[float] = None
    median_latency_ms: Optional[float] = None
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    std_latency_ms: Optional[float] = None
    mean_bytes: Optional[float] = None
    median_bytes: Optional[float] = None
    success_count: int = 0
    failure_count: int = 0
    success_rate_pct: Optional[float] = None
    negotiated_tls_ver: Optional[str] = None
    negotiated_group: Optional[str] = None

    def compute_stats(self) -> None:
        """Calculate aggregate statistics from non-warmup results."""
        non_warmup = [r for r in self.results if not r.is_warmup]
        successes = [r for r in non_warmup if r.success]
        failures  = [r for r in non_warmup if not r.success]

        self.success_count = len(successes)
        self.failure_count = len(failures)
        total = len(non_warmup)
        self.success_rate_pct = (
            (self.success_count / total * 100) if total > 0 else None
        )

        latencies = [r.latency_ms for r in successes if r.latency_ms is not None]
        if latencies:
            self.mean_latency_ms   = statistics.mean(latencies)
            self.median_latency_ms = statistics.median(latencies)
            self.min_latency_ms    = min(latencies)
            self.max_latency_ms    = max(latencies)
            self.std_latency_ms    = (
                statistics.stdev(latencies) if len(latencies) > 1 else 0.0
            )

        all_bytes = []
        for r in successes:
            sent = r.bytes_sent or 0
            recv = r.bytes_received or 0
            if sent + recv > 0:
                all_bytes.append(sent + recv)
        if all_bytes:
            self.mean_bytes   = statistics.mean(all_bytes)
            self.median_bytes = statistics.median(all_bytes)

        # Pick negotiated TLS metadata from first successful result
        for r in successes:
            if r.tls_version and self.negotiated_tls_ver is None:
                self.negotiated_tls_ver = r.tls_version
            if r.tls_group and self.negotiated_group is None:
                self.negotiated_group = r.tls_group
            if self.negotiated_tls_ver and self.negotiated_group:
                break

    def to_dict(self) -> dict:
        return {
            "config": asdict(self.config),
            "openssl_version": self.openssl_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "error_summary": self.error_summary,
            "mean_latency_ms": self.mean_latency_ms,
            "median_latency_ms": self.median_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "std_latency_ms": self.std_latency_ms,
            "mean_bytes": self.mean_bytes,
            "median_bytes": self.median_bytes,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate_pct": self.success_rate_pct,
            "negotiated_tls_ver": self.negotiated_tls_ver,
            "negotiated_group": self.negotiated_group,
            "results": [r.to_dict() for r in self.results],
        }


# ─────────────────────────────────────────────────────────────────────────────
# TLS Context Builder
# ─────────────────────────────────────────────────────────────────────────────

# Map mode names to OpenSSL group strings.
MODE_GROUPS = {
    "classical": "x25519",          # Built-in to TLS 1.3 on all modern OpenSSL
    "pqc":       "mlkem768",        # ML-KEM-768 alone — requires oqs-provider
    "hybrid":    "x25519_mlkem768", # Hybrid X25519 + ML-KEM-768 — requires oqs-provider
}

# OpenSSL version info (computed once at module load)
_SSL_VERSION_INFO = ssl.OPENSSL_VERSION_INFO


def _build_ssl_context(mode: str, timeout_s: float) -> Tuple[ssl.SSLContext, str]:
    """
    Create an SSLContext configured for the requested cryptographic mode.

    Returns:
        (context, group_name_requested)

    Raises:
        ValueError: if the mode is unknown or the PQC/hybrid group cannot be configured.

    Key design decision — NO silent fallback:
        For PQC and hybrid modes, if set_ecdh_curve() fails we raise a ValueError.
        This ensures the caller knows the mode was NOT actually configured.
        For classical mode we do NOT call set_ecdh_curve at all on OpenSSL 1.1.x,
        because 'x25519' is not a named curve in that API — it is used automatically
        by the TLS 1.3 state machine.
    """
    desired_group = MODE_GROUPS.get(mode)
    if desired_group is None:
        raise ValueError(
            f"Unknown mode '{mode}'. Valid modes are: {sorted(MODE_GROUPS)}"
        )

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Enforce TLS 1.3 only (prevents fallback to 1.2 with RSA key exchange)
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    except AttributeError:
        pass  # Very old Python — TLSVersion not available

    if mode == "classical":
        # On OpenSSL 1.1.x: do NOT call set_ecdh_curve('x25519').
        # X25519 is the default preferred group for TLS 1.3 and is used automatically.
        # On OpenSSL 3.x (with or without oqs-provider): same behaviour —
        # we let the implementation choose x25519 as the preferred classical group.
        pass

    else:
        # PQC and hybrid modes: MUST set the group, or fail loudly.
        try:
            ctx.set_ecdh_curve(desired_group)
        except (ssl.SSLError, OSError, ValueError) as exc:
            raise ValueError(
                f"Cannot configure TLS group '{desired_group}' for mode '{mode}'. "
                f"Error: {exc}. "
                f"This mode requires OpenSSL 3.x with oqs-provider installed and loaded. "
                f"Current OpenSSL: {ssl.OPENSSL_VERSION}. "
                "See docs/setup.md for PQC installation instructions."
            ) from exc

    return ctx, desired_group


# ─────────────────────────────────────────────────────────────────────────────
# Single handshake measurement
# ─────────────────────────────────────────────────────────────────────────────

def _perform_single_handshake(
    config: ExperimentConfig,
    ssl_ctx: ssl.SSLContext,
    run_index: int,
    is_warmup: bool,
    inferred_group: str,
) -> HandshakeResult:
    """
    Perform exactly one TLS handshake and measure its latency.

    Timing methodology:
      t0 = just before socket.connect()
      t1 = just after socket.connect()    → tcp_connect_ms = (t1-t0)*1000
      t2 = just before ssl.wrap_socket()
      t3 = just after ssl.wrap_socket()   → tls_handshake_ms = (t3-t2)*1000

    We report tls_handshake_ms as `latency_ms`.

    Bytes measurement:
      We send a minimal HTTP GET after the handshake and record bytes_sent
      as the length of that request (application-layer bytes, NOT wire bytes).
      Python's ssl module on 1.1.x does not expose TLS record-level byte counts.
      See docs/benchmarking-methodology.md for full discussion.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    raw_sock = None
    ssl_sock = None

    try:
        # ── Step 1: TCP connection (timed but excluded from reported latency) ──
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(config.timeout_s)

        t0 = time.monotonic()
        raw_sock.connect((config.target_host, config.target_port))
        t1 = time.monotonic()
        tcp_ms = (t1 - t0) * 1000.0

        # ── Step 2: TLS handshake (this is what we measure) ──────────────────
        t2 = time.monotonic()
        ssl_sock = ssl_ctx.wrap_socket(
            raw_sock,
            server_hostname=config.server_name,
            do_handshake_on_connect=True,  # blocks until TLS Finished received
        )
        t3 = time.monotonic()
        tls_ms = (t3 - t2) * 1000.0

        # ── Step 3: Extract negotiated parameters ─────────────────────────────
        tls_version = ssl_sock.version()       # e.g. "TLSv1.3"
        cipher_info = ssl_sock.cipher()        # (name, protocol, bits)
        cipher_name = cipher_info[0] if cipher_info else None

        # Group name: Python's ssl module doesn't expose this directly on 1.1.x.
        # For classical mode we infer x25519 from TLSv1.3 + the cipher name.
        # For PQC modes this would need oqs-provider's extended API.
        tls_group = _infer_group(ssl_sock, inferred_group)

        # ── Step 4: Minimal data exchange for byte measurement ────────────────
        minimal_request = (
            f"GET / HTTP/1.0\r\n"
            f"Host: {config.server_name}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")

        try:
            ssl_sock.sendall(minimal_request)
            response_data = ssl_sock.recv(4096)
            bytes_recv = len(response_data)
        except (socket.timeout, OSError):
            bytes_recv = None

        return HandshakeResult(
            run_index=run_index,
            is_warmup=is_warmup,
            started_at=started_at,
            success=True,
            latency_ms=round(tls_ms, 4),    # 4 decimal places for sub-ms loopback precision
            tcp_connect_ms=round(tcp_ms, 4),
            bytes_sent=len(minimal_request),
            bytes_received=bytes_recv,
            tls_version=tls_version,
            tls_group=tls_group,
            cipher_suite=cipher_name,
        )

    except ssl.SSLError as exc:
        return HandshakeResult(
            run_index=run_index, is_warmup=is_warmup, started_at=started_at,
            success=False, error_type="ssl_error",
            error_detail=str(exc)[:500],
        )
    except socket.timeout:
        return HandshakeResult(
            run_index=run_index, is_warmup=is_warmup, started_at=started_at,
            success=False, error_type="timeout",
            error_detail=f"Timed out after {config.timeout_s}s",
        )
    except ConnectionRefusedError:
        return HandshakeResult(
            run_index=run_index, is_warmup=is_warmup, started_at=started_at,
            success=False, error_type="connection_refused",
            error_detail=f"Connection refused to {config.target_host}:{config.target_port}",
        )
    except OSError as exc:
        return HandshakeResult(
            run_index=run_index, is_warmup=is_warmup, started_at=started_at,
            success=False, error_type="os_error",
            error_detail=str(exc)[:500],
        )
    except Exception as exc:
        logger.exception("Unexpected error during handshake run %d", run_index)
        return HandshakeResult(
            run_index=run_index, is_warmup=is_warmup, started_at=started_at,
            success=False, error_type="unexpected_error",
            error_detail=str(exc)[:500],
        )
    finally:
        for s in [ssl_sock, raw_sock]:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass


def _infer_group(ssl_sock: ssl.SSLSocket, configured_group: str) -> Optional[str]:
    """
    Attempt to determine the negotiated key-exchange group.

    On OpenSSL 1.1.x the ssl module has no API to read the negotiated group.
    We return the configured group name as a best-effort label, with a note
    that this is what was requested rather than what was verified.

    On OpenSSL 3.x + oqs-provider, the group name can be read via
    ssl.SSLObject.get_channel_binding or private attributes — not yet
    standardised in Python's ssl module as of 3.12.
    """
    try:
        tls_ver = ssl_sock.version()
        if tls_ver and "1.3" in tls_ver and configured_group == "x25519":
            # TLS 1.3 + no PQC group configured → x25519 was used
            # (This is an inference, not a verified read)
            return "x25519 (inferred)"
        return configured_group if configured_group else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main benchmark runner
# ─────────────────────────────────────────────────────────────────────────────

def run_experiment(config: ExperimentConfig) -> ExperimentSummary:
    """
    Run the full TLS benchmark experiment.

    Steps:
      1. Validate the mode and build the SSL context (fail loudly if unsupported).
      2. Run warmup handshakes (discarded from statistics).
      3. Run measurement handshakes, possibly concurrently.
      4. Compute aggregate statistics.
      5. Return the complete ExperimentSummary.
    """
    openssl_ver = ssl.OPENSSL_VERSION
    started_at  = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Starting experiment: mode=%s host=%s:%d reps=%d concurrency=%d",
        config.mode, config.target_host, config.target_port,
        config.repetitions, config.concurrency,
    )

    # ── Build SSL context ─────────────────────────────────────────────────
    try:
        ssl_ctx, actual_group = _build_ssl_context(config.mode, config.timeout_s)
    except ValueError as exc:
        finished_at = datetime.now(timezone.utc).isoformat()
        logger.warning("Mode '%s' unsupported: %s", config.mode, exc)
        return ExperimentSummary(
            config=config,
            results=[],
            openssl_version=openssl_ver,
            started_at=started_at,
            finished_at=finished_at,
            status="failed",
            error_summary=str(exc),
            success_count=0,
            failure_count=config.repetitions,
            success_rate_pct=0.0,
        )

    all_results: List[HandshakeResult] = []

    # ── Warmup runs (discarded from statistics) ───────────────────────────
    for i in range(config.warmup_runs):
        r = _perform_single_handshake(
            config, ssl_ctx, run_index=i, is_warmup=True,
            inferred_group=actual_group,
        )
        all_results.append(r)
        logger.debug("Warmup %d: success=%s latency=%.1fms",
                     i, r.success, r.latency_ms or 0)

    # ── Measurement runs ──────────────────────────────────────────────────
    if config.concurrency <= 1:
        # Sequential: simple and deterministic
        for i in range(config.repetitions):
            r = _perform_single_handshake(
                config, ssl_ctx, run_index=i, is_warmup=False,
                inferred_group=actual_group,
            )
            all_results.append(r)
            logger.debug("Run %d/%d: success=%s latency=%.1fms",
                         i + 1, config.repetitions, r.success, r.latency_ms or 0)
    else:
        # Concurrent: thread pool simulates multiple simultaneous clients
        measurement_results: List[Optional[HandshakeResult]] = [None] * config.repetitions
        with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
            future_map = {
                pool.submit(
                    _perform_single_handshake,
                    config, ssl_ctx, i, False, actual_group,
                ): i
                for i in range(config.repetitions)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    measurement_results[idx] = future.result()
                except Exception as exc:
                    measurement_results[idx] = HandshakeResult(
                        run_index=idx,
                        is_warmup=False,
                        started_at=datetime.now(timezone.utc).isoformat(),
                        success=False,
                        error_type="thread_error",
                        error_detail=str(exc)[:500],
                    )
        all_results.extend([r for r in measurement_results if r is not None])

    finished_at = datetime.now(timezone.utc).isoformat()

    # ── Build and compute summary ─────────────────────────────────────────
    summary = ExperimentSummary(
        config=config,
        results=all_results,
        openssl_version=openssl_ver,
        started_at=started_at,
        finished_at=finished_at,
        status="completed",
    )
    summary.compute_stats()

    if summary.success_count == 0 and config.repetitions > 0:
        summary.status = "failed"
        errors = {r.error_type for r in all_results if r.error_type}
        summary.error_summary = (
            f"All {config.repetitions} measurement runs failed. "
            f"Error types: {', '.join(sorted(errors))}. "
            "Check that the target host is reachable and the loopback server is running."
        )

    logger.info(
        "Experiment complete: mode=%s success=%d/%d mean=%.1fms",
        config.mode, summary.success_count, config.repetitions,
        summary.mean_latency_ms or 0,
    )
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Loopback server launcher
# ─────────────────────────────────────────────────────────────────────────────

def start_loopback_server(host: str = "127.0.0.1", port: int = 54443) -> threading.Thread:
    """
    Start a minimal TLS 1.3 server on localhost for local benchmarking.
    Returns the server thread (daemon=True).
    """
    from benchmark.server.loopback_server import run_loopback_server
    t = threading.Thread(
        target=run_loopback_server,
        args=(host, port),
        daemon=True,
        name=f"loopback-tls-{port}",
    )
    t.start()
    # Give the server a moment to bind and start listening
    time.sleep(0.3)
    logger.info("Loopback TLS server started on %s:%d", host, port)
    return t
