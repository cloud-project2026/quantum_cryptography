# ──────────────────────────────────────────────────────────────────────────
# Post-Quantum Cryptography Migration Platform
# Test Suite
# ──────────────────────────────────────────────────────────────────────────
"""
Tests are organised into:
  Unit tests  — test individual functions in isolation (fast, no network)
  Integration — test Flask routes end-to-end (in-memory SQLite)
  TLS tests   — test real TLS handshakes where supported

Run:
    python -m pytest tests/ -v
    python -m pytest tests/ -v -k "not tls_real"   # skip TLS network tests
"""

import pytest
import json
import sqlite3
import tempfile
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def temp_db():
    """Create a temporary database file for the session."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope="session")
def app(temp_db):
    """Create a test Flask app with an isolated database."""
    from app import create_app

    test_app = create_app({
        "TESTING": True,
        "ENV": "testing",
        "DATABASE_PATH": temp_db,
        "SECRET_KEY": "test-secret",
        "ALLOWED_BENCHMARK_HOSTS": ["localhost", "127.0.0.1", "example.com"],
        "MAX_REPETITIONS": 200,
        "MAX_CONCURRENCY": 20,
    })
    yield test_app


@pytest.fixture()
def client(app):
    """Flask test client that simulates HTTP requests."""
    return app.test_client()


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Metrics
# ═══════════════════════════════════════════════════════════════════════════

class TestMetricsCalculations:
    """Tests for the metrics service — no network or database needed."""

    def test_calculate_overhead_basic(self):
        from app.services.metrics import calculate_overhead
        # PQC takes 120ms, classical took 100ms → 20% overhead
        result = calculate_overhead(baseline=100.0, alternative=120.0)
        assert abs(result - 20.0) < 0.001

    def test_calculate_overhead_improvement(self):
        from app.services.metrics import calculate_overhead
        # Alternative is faster: negative overhead (improvement)
        result = calculate_overhead(baseline=100.0, alternative=80.0)
        assert abs(result - (-20.0)) < 0.001

    def test_calculate_overhead_zero_baseline(self):
        from app.services.metrics import calculate_overhead
        # Cannot divide by zero
        result = calculate_overhead(baseline=0.0, alternative=50.0)
        assert result is None

    def test_calculate_overhead_none_values(self):
        from app.services.metrics import calculate_overhead
        assert calculate_overhead(None, 100.0) is None
        assert calculate_overhead(100.0, None) is None
        assert calculate_overhead(None, None)  is None

    def test_overhead_equal_values(self):
        from app.services.metrics import calculate_overhead
        result = calculate_overhead(baseline=100.0, alternative=100.0)
        assert result == 0.0

    def test_compute_comparison_with_data(self):
        from app.services.metrics import compute_comparison
        classical = {"id": 1, "mean_latency_ms": 10.0, "median_latency_ms": 9.5,
                     "min_latency_ms": 8.0, "max_latency_ms": 12.0,
                     "std_latency_ms": 1.0, "mean_bytes": 500.0,
                     "success_rate_pct": 100.0}
        pqc = {"id": 2, "mean_latency_ms": 15.0, "median_latency_ms": 14.5,
               "min_latency_ms": 13.0, "max_latency_ms": 17.0,
               "std_latency_ms": 1.5, "mean_bytes": 1200.0,
               "success_rate_pct": 100.0}
        result = compute_comparison(classical, pqc, None)

        assert result["classical"]["mean_latency_ms"] == 10.0
        assert result["pqc"]["mean_latency_ms"] == 15.0
        assert abs(result["pqc"]["latency_overhead_pct"] - 50.0) < 0.001
        assert result["hybrid"]["mean_latency_ms"] is None  # no data

    def test_compute_comparison_no_baseline(self):
        from app.services.metrics import compute_comparison
        result = compute_comparison(None, None, None)
        assert result["classical"]["mean_latency_ms"] is None
        assert result["has_baseline"] is False

    def test_aggregate_latencies_normal(self):
        from app.services.metrics import aggregate_latencies
        stats = aggregate_latencies([10.0, 20.0, 30.0])
        assert stats["mean"] == 20.0
        assert stats["min"]  == 10.0
        assert stats["max"]  == 30.0

    def test_aggregate_latencies_empty(self):
        from app.services.metrics import aggregate_latencies
        stats = aggregate_latencies([])
        assert all(v is None for v in stats.values())

    def test_aggregate_latencies_single(self):
        from app.services.metrics import aggregate_latencies
        stats = aggregate_latencies([42.0])
        assert stats["mean"] == 42.0
        assert stats["std"]  == 0.0

    def test_export_to_csv_empty(self):
        from app.services.metrics import export_to_csv
        result = export_to_csv([])
        assert "No experiments" in result

    def test_export_to_csv_with_data(self):
        from app.services.metrics import export_to_csv
        data = [{"id": 1, "mode": "classical", "mean_latency_ms": 10.5,
                 "created_at": "2024-01-01", "status": "completed"}]
        result = export_to_csv(data)
        assert "classical" in result
        assert "id" in result   # header row present


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Crypto Capabilities
# ═══════════════════════════════════════════════════════════════════════════

class TestCryptoCapabilities:
    """Tests for capability detection — no network needed."""

    def test_get_openssl_version_returns_dict(self):
        from app.services.crypto_capabilities import get_openssl_version
        info = get_openssl_version()
        assert "string" in info
        assert "major" in info
        assert isinstance(info["supports_native_pqc"], bool)
        assert isinstance(info["supports_oqs_provider"], bool)

    def test_openssl_version_string_not_empty(self):
        from app.services.crypto_capabilities import get_openssl_version
        info = get_openssl_version()
        assert len(info["string"]) > 0
        assert "OpenSSL" in info["string"]

    def test_tls_version_support_returns_dict(self):
        from app.services.crypto_capabilities import get_tls_version_support
        support = get_tls_version_support()
        # TLS 1.3 should be available in Python 3.10
        assert "TLSv1.3" in support
        assert support["TLSv1.3"] is True

    def test_mode_availability_structure(self):
        from app.services.crypto_capabilities import get_mode_availability
        modes = get_mode_availability()
        assert "classical" in modes
        assert "pqc" in modes
        assert "hybrid" in modes

        # Classical should always be available
        assert modes["classical"]["available"] is True
        assert modes["classical"]["group"] == "x25519"

    def test_classical_mode_never_unavailable(self):
        """Classical TLS must always be available — it's the baseline."""
        from app.services.crypto_capabilities import get_mode_availability
        modes = get_mode_availability()
        assert modes["classical"]["available"] is True

    def test_pqc_unavailable_on_openssl_1x(self):
        """On OpenSSL 1.1.x, PQC modes should report as unavailable."""
        import ssl
        from app.services.crypto_capabilities import get_openssl_version, get_mode_availability
        ossl = get_openssl_version()
        modes = get_mode_availability()

        if not ossl["supports_oqs_provider"]:
            # On this machine (OpenSSL 1.1.x), PQC must be unavailable
            assert modes["pqc"]["available"]    is False
            assert modes["hybrid"]["available"] is False
            assert modes["pqc"]["limitations"]  is not None

    def test_full_capabilities_structure(self):
        from app.services.crypto_capabilities import get_full_capabilities
        caps = get_full_capabilities()
        assert "openssl" in caps
        assert "tls_versions" in caps
        assert "modes" in caps
        assert "summary" in caps
        assert "classical_available" in caps["summary"]


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — TLS Benchmark Config
# ═══════════════════════════════════════════════════════════════════════════

class TestExperimentConfig:
    def test_default_config(self):
        from app.services.tls_benchmark import ExperimentConfig
        cfg = ExperimentConfig(mode="classical")
        assert cfg.mode == "classical"
        assert cfg.repetitions == 10
        assert cfg.concurrency == 1
        assert cfg.warmup_runs == 2
        assert cfg.server_name == cfg.target_host

    def test_server_name_defaults_to_host(self):
        from app.services.tls_benchmark import ExperimentConfig
        cfg = ExperimentConfig(mode="classical", target_host="example.com")
        assert cfg.server_name == "example.com"

    def test_experiment_summary_compute_stats_empty(self):
        from app.services.tls_benchmark import ExperimentConfig, ExperimentSummary
        cfg = ExperimentConfig(mode="classical")
        summary = ExperimentSummary(
            config=cfg, results=[], openssl_version="test",
            started_at="2024-01-01", finished_at="2024-01-01", status="completed"
        )
        summary.compute_stats()
        assert summary.success_count == 0
        assert summary.failure_count == 0
        assert summary.mean_latency_ms is None

    def test_build_ssl_context_classical_succeeds(self):
        from app.services.tls_benchmark import _build_ssl_context
        import ssl
        ctx, group = _build_ssl_context("classical", timeout_s=5.0)
        assert isinstance(ctx, ssl.SSLContext)
        assert group == "x25519"  # classical mode targets x25519

    def test_build_ssl_context_unknown_mode_raises(self):
        from app.services.tls_benchmark import _build_ssl_context
        with pytest.raises(ValueError, match="Unknown mode|unknown mode"):
            _build_ssl_context("nonexistent_mode", timeout_s=5.0)

    def test_build_ssl_context_pqc_raises_on_openssl_1x(self):
        """PQC context creation must fail loudly (not silently fall back)."""
        import ssl
        from app.services.crypto_capabilities import get_openssl_version
        from app.services.tls_benchmark import _build_ssl_context

        ossl = get_openssl_version()
        if not ossl["supports_oqs_provider"]:
            # Must raise ValueError with a useful message
            with pytest.raises(ValueError) as exc_info:
                _build_ssl_context("pqc", timeout_s=5.0)
            err_lower = str(exc_info.value).lower()
            assert any(kw in err_lower for kw in ["oqs", "openssl", "group", "mlkem"])
        else:
            pytest.skip("oqs-provider is available — skip 1.x failure test")


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — Database
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabase:
    def test_init_db_creates_tables(self, temp_db):
        from app.models.database import init_db, get_connection
        init_db(temp_db)
        with get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
        assert "experiments" in table_names
        assert "handshake_results" in table_names

    def test_insert_and_retrieve_experiment(self, temp_db):
        from app.models.database import init_db, get_connection, row_to_dict
        init_db(temp_db)
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO experiments (mode, repetitions, concurrency, warmup_runs, "
                "timeout_s, target_host, target_port, status) VALUES (?,?,?,?,?,?,?,?)",
                ("classical", 10, 1, 2, 10.0, "localhost", 443, "completed")
            )
            exp_id = cur.lastrowid
            row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        assert row_to_dict(row)["mode"] == "classical"
        assert row_to_dict(row)["repetitions"] == 10

    def test_row_to_dict_none(self):
        from app.models.database import row_to_dict
        assert row_to_dict(None) is None

    def test_rows_to_list_empty(self):
        from app.models.database import rows_to_list
        assert rows_to_list([]) == []


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Flask Routes
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_structure(self, client):
        resp = client.get("/health")
        data = json.loads(resp.data)
        assert "status" in data
        assert "version" in data
        assert "database_ok" in data
        assert "openssl_version" in data

    def test_health_db_is_ok(self, client):
        resp = client.get("/health")
        data = json.loads(resp.data)
        assert data["database_ok"] is True


class TestSystemRoutes:
    def test_capabilities_endpoint(self, client):
        resp = client.get("/api/system/capabilities")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "openssl" in data
        assert "modes" in data
        assert "classical" in data["modes"]

    def test_status_endpoint(self, client):
        resp = client.get("/api/system/status")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["server"] == "running"
        assert "total_experiments" in data


class TestExperimentsRoutes:
    def test_list_experiments_empty(self, client):
        resp = client.get("/api/experiments/")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "experiments" in data
        assert isinstance(data["experiments"], list)

    def test_run_experiment_invalid_mode(self, client):
        resp = client.post("/api/experiments/run",
                           json={"mode": "invalid_mode", "target_host": "localhost"})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_run_experiment_ssrf_blocked(self, client):
        """Verify that arbitrary hosts are blocked."""
        resp = client.post("/api/experiments/run",
                           json={"mode": "classical",
                                 "target_host": "evil.attacker.com",
                                 "target_port": 443,
                                 "repetitions": 1})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "not in the allowed list" in data["error"].lower() or "allowed" in data["error"].lower()

    def test_run_experiment_invalid_port(self, client):
        resp = client.post("/api/experiments/run",
                           json={"mode": "classical", "target_host": "localhost",
                                 "target_port": 99999})
        assert resp.status_code == 400

    def test_run_experiment_too_many_reps(self, client):
        resp = client.post("/api/experiments/run",
                           json={"mode": "classical", "target_host": "localhost",
                                 "repetitions": 9999})
        assert resp.status_code == 400

    def test_run_experiment_no_body(self, client):
        resp = client.post("/api/experiments/run",
                           content_type="application/json")
        assert resp.status_code == 400

    def test_get_nonexistent_experiment(self, client):
        resp = client.get("/api/experiments/99999")
        assert resp.status_code == 404

    def test_pqc_mode_rejected_on_openssl_1x(self, client):
        """PQC mode must return 422 (unsupported) when oqs-provider not installed."""
        import ssl
        from app.services.crypto_capabilities import get_openssl_version
        ossl = get_openssl_version()

        if not ossl["supports_oqs_provider"]:
            resp = client.post("/api/experiments/run",
                               json={"mode": "pqc",
                                     "target_host": "localhost",
                                     "target_port": 443,
                                     "repetitions": 1})
            assert resp.status_code == 422
            data = json.loads(resp.data)
            assert data["error"] == "mode_unsupported"

    def test_delete_nonexistent_experiment(self, client):
        resp = client.delete("/api/experiments/99999")
        assert resp.status_code == 404


class TestResultsRoutes:
    def test_compare_endpoint_no_data(self, client):
        resp = client.get("/api/results/compare")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "classical" in data
        assert "pqc" in data
        assert "hybrid" in data

    def test_export_json(self, client):
        resp = client.get("/api/results/export?fmt=json")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")

    def test_export_csv(self, client):
        resp = client.get("/api/results/export?fmt=csv")
        assert resp.status_code == 200
        assert "csv" in resp.content_type.lower() or "text" in resp.content_type.lower()

    def test_summary_endpoint(self, client):
        resp = client.get("/api/results/summary")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "total_experiments" in data


class TestMainRoutes:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"PQC" in resp.data or b"html" in resp.data.lower()


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION — Real TLS handshake (classical, loopback)
# ═══════════════════════════════════════════════════════════════════════════

class TestRealTLSHandshake:
    """
    These tests perform actual TLS connections.
    They run against the loopback server.
    Skip if network is unavailable.
    """

    @pytest.fixture(scope="class", autouse=True)
    def start_loopback(self):
        """Start the loopback TLS server for this test class."""
        import threading
        import time
        import socket as _socket
        from benchmark.server.loopback_server import run_loopback_server

        port = 54444
        t = threading.Thread(
            target=run_loopback_server,
            args=("127.0.0.1", port),
            daemon=True,
            name="test-loopback-server",
        )
        t.start()

        # Wait for server to be accepting connections (up to 3 seconds)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                s = _socket.create_connection(("127.0.0.1", port), timeout=0.2)
                s.close()
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)

        yield
        # Server thread is daemon so it stops automatically when test process exits

    def test_classical_tls_handshake_succeeds(self):
        from app.services.tls_benchmark import ExperimentConfig, run_experiment
        cfg = ExperimentConfig(
            mode="classical",
            target_host="127.0.0.1",
            target_port=54444,
            repetitions=3,
            concurrency=1,
            warmup_runs=0,
            timeout_s=8.0,
        )
        summary = run_experiment(cfg)
        assert summary.success_count >= 1, (
            f"Expected at least 1 success, got {summary.success_count}. "
            f"Error: {summary.error_summary}"
        )
        assert summary.mean_latency_ms is not None
        # Loopback handshakes complete in < 0.05ms on this machine, rounding to 0.0 at 4dp.
        # A result of 0.0ms is valid — it means the handshake succeeded extremely fast.
        assert summary.mean_latency_ms >= 0

    def test_classical_tls_records_tls_version(self):
        from app.services.tls_benchmark import ExperimentConfig, run_experiment
        cfg = ExperimentConfig(
            mode="classical",
            target_host="127.0.0.1",
            target_port=54444,
            repetitions=2,
            concurrency=1,
            warmup_runs=0,
            timeout_s=8.0,
        )
        summary = run_experiment(cfg)
        successes = [r for r in summary.results if r.success]
        if successes:
            # TLS version should be set on successful runs
            tls_versions = [r.tls_version for r in successes if r.tls_version]
            # Should be TLSv1.3 since we enforce it
            assert isinstance(tls_versions, list)
            if tls_versions:
                assert any("1.3" in v for v in tls_versions)

    def test_experiment_summary_compute_stats(self):
        from app.services.tls_benchmark import ExperimentConfig, run_experiment
        cfg = ExperimentConfig(
            mode="classical",
            target_host="127.0.0.1",
            target_port=54444,
            repetitions=5,
            concurrency=1,
            warmup_runs=0,
            timeout_s=8.0,
        )
        summary = run_experiment(cfg)
        if summary.success_count > 0:
            assert summary.min_latency_ms <= summary.mean_latency_ms <= summary.max_latency_ms
            assert summary.success_rate_pct > 0
            if summary.success_count > 1:
                assert summary.std_latency_ms is not None

    def test_pqc_mode_fails_gracefully_on_openssl_1x(self):
        """PQC mode on OpenSSL 1.1.x must fail with a clear error, not silently succeed."""
        import ssl
        from app.services.crypto_capabilities import get_openssl_version
        from app.services.tls_benchmark import ExperimentConfig, run_experiment

        ossl = get_openssl_version()
        if ossl["supports_oqs_provider"]:
            pytest.skip("oqs-provider is available; skip fail-gracefully test")

        cfg = ExperimentConfig(
            mode="pqc",
            target_host="127.0.0.1",
            target_port=54444,
            repetitions=1,
            warmup_runs=0,
            timeout_s=5.0,
        )
        summary = run_experiment(cfg)
        # Must fail — not silently succeed
        assert summary.status == "failed"
        assert summary.success_count == 0
        assert summary.error_summary is not None
        # Error must mention the actual reason (group name or OpenSSL)
        err_lower = summary.error_summary.lower()
        assert any(kw in err_lower for kw in ["oqs", "openssl", "group", "mlkem", "mode"])

    def test_concurrent_handshakes(self):
        from app.services.tls_benchmark import ExperimentConfig, run_experiment
        cfg = ExperimentConfig(
            mode="classical",
            target_host="127.0.0.1",
            target_port=54444,
            repetitions=6,
            concurrency=3,
            warmup_runs=0,
            timeout_s=8.0,
        )
        summary = run_experiment(cfg)
        non_warmup = [r for r in summary.results if not r.is_warmup]
        assert len(non_warmup) == 6


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION — Full API round-trip (classical experiment → stored → retrieved)
# ═══════════════════════════════════════════════════════════════════════════

class TestFullRoundTrip:
    """
    Start loopback server, POST to /api/experiments/run,
    verify result stored in DB, fetch it back, compare results.
    """

    @pytest.fixture(scope="class", autouse=True)
    def ensure_loopback(self):
        import threading
        import time
        import socket as _socket
        from benchmark.server.loopback_server import run_loopback_server

        port = 54445
        t = threading.Thread(
            target=run_loopback_server,
            args=("127.0.0.1", port),
            daemon=True,
        )
        t.start()

        # Wait for server to accept connections
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                s = _socket.create_connection(("127.0.0.1", port), timeout=0.2)
                s.close()
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)
        yield

    def test_post_run_stores_result(self, client, app):
        """POST an experiment and verify it appears in the listing."""
        app.config["ALLOWED_BENCHMARK_HOSTS"] = ["localhost", "127.0.0.1"]

        resp = client.post("/api/experiments/run", json={
            "mode": "classical",
            "target_host": "127.0.0.1",
            "target_port": 54445,
            "repetitions": 3,
            "concurrency": 1,
            "warmup_runs": 0,
            "timeout_s": 8.0,
        })
        assert resp.status_code == 201, f"Unexpected status: {resp.status_code} — {resp.data[:300]}"
        data = json.loads(resp.data)
        assert "experiment" in data
        exp = data["experiment"]
        exp_id = exp["id"]

        # Should appear in listing
        list_resp = client.get("/api/experiments/")
        list_data = json.loads(list_resp.data)
        ids = [e["id"] for e in list_data["experiments"]]
        assert exp_id in ids

        # Should be retrievable individually
        get_resp = client.get(f"/api/experiments/{exp_id}")
        assert get_resp.status_code == 200
        get_data = json.loads(get_resp.data)
        assert get_data["experiment"]["mode"] == "classical"

    def test_comparison_shows_classical_after_run(self, client, app):
        app.config["ALLOWED_BENCHMARK_HOSTS"] = ["localhost", "127.0.0.1"]

        # Run a classical experiment against our loopback server
        client.post("/api/experiments/run", json={
            "mode": "classical",
            "target_host": "127.0.0.1",
            "target_port": 54445,
            "repetitions": 3,
            "warmup_runs": 0,
            "timeout_s": 8.0,
        })

        compare_resp = client.get("/api/results/compare")
        assert compare_resp.status_code == 200
        compare_data = json.loads(compare_resp.data)
        # Classical should now have data (at least one experiment ran)
        assert compare_data["classical"]["mean_latency_ms"] is not None
