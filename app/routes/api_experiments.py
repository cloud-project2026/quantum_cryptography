"""
Experiment API Routes
=====================

POST /api/experiments/run      — Start a new benchmark experiment
GET  /api/experiments/         — List all experiments
GET  /api/experiments/<id>     — Get one experiment (with all handshake results)
DELETE /api/experiments/<id>   — Delete one experiment

Input validation is strict. We never accept untrusted host targets
outside the allowed list to prevent SSRF attacks.
"""

import json
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from app.models.database import get_connection, rows_to_list, row_to_dict
from app.services.tls_benchmark import ExperimentConfig, run_experiment
from app.services.crypto_capabilities import get_mode_availability

logger = logging.getLogger(__name__)

experiments_bp = Blueprint("experiments", __name__)

VALID_MODES = {"classical", "pqc", "hybrid"}


def _validate_config(data: dict) -> tuple:
    """
    Validate experiment configuration from request JSON.

    Returns:
        (ExperimentConfig, None) on success
        (None, error_message) on validation failure
    """
    mode = data.get("mode", "").lower()
    if mode not in VALID_MODES:
        return None, f"Invalid mode '{mode}'. Choose: {sorted(VALID_MODES)}"

    # SSRF prevention: only allow hosts in the configured allowlist
    target_host = data.get("target_host", "localhost").strip().lower()
    allowed_hosts = [h.strip().lower() for h in current_app.config["ALLOWED_BENCHMARK_HOSTS"]]
    if target_host not in allowed_hosts:
        return None, (
            f"Target host '{target_host}' is not in the allowed list. "
            f"Allowed: {allowed_hosts}. "
            "This restriction prevents misuse of the benchmarking service. "
            "Add hosts to ALLOWED_BENCHMARK_HOSTS in .env to expand the list."
        )

    try:
        target_port = int(data.get("target_port", 443))
        if not (1 <= target_port <= 65535):
            raise ValueError()
    except (ValueError, TypeError):
        return None, "target_port must be an integer between 1 and 65535."

    try:
        repetitions = int(data.get("repetitions", 10))
        if not (1 <= repetitions <= current_app.config["MAX_REPETITIONS"]):
            raise ValueError()
    except (ValueError, TypeError):
        return None, (
            f"repetitions must be 1–{current_app.config['MAX_REPETITIONS']}."
        )

    try:
        concurrency = int(data.get("concurrency", 1))
        if not (1 <= concurrency <= current_app.config["MAX_CONCURRENCY"]):
            raise ValueError()
    except (ValueError, TypeError):
        return None, (
            f"concurrency must be 1–{current_app.config['MAX_CONCURRENCY']}."
        )

    try:
        warmup_runs = int(data.get("warmup_runs", 2))
        if not (0 <= warmup_runs <= 20):
            raise ValueError()
    except (ValueError, TypeError):
        return None, "warmup_runs must be 0–20."

    try:
        timeout_s = float(data.get("timeout_s", current_app.config["DEFAULT_TIMEOUT"]))
        if not (0.5 <= timeout_s <= 60.0):
            raise ValueError()
    except (ValueError, TypeError):
        return None, "timeout_s must be a number between 0.5 and 60."

    config = ExperimentConfig(
        mode=mode,
        target_host=target_host,
        target_port=target_port,
        repetitions=repetitions,
        concurrency=concurrency,
        warmup_runs=warmup_runs,
        timeout_s=timeout_s,
    )
    return config, None


@experiments_bp.route("/run", methods=["POST"])
def run_experiment_endpoint():
    """
    Start a TLS benchmark experiment.

    Request JSON body:
      {
        "mode": "classical" | "pqc" | "hybrid",
        "target_host": "example.com",
        "target_port": 443,
        "repetitions": 10,
        "concurrency": 1,
        "warmup_runs": 2,
        "timeout_s": 10.0
      }

    Response: the saved experiment record.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    config, err = _validate_config(data)
    if err:
        return jsonify({"error": err}), 400

    # Check if the requested mode is available on this machine
    mode_status = get_mode_availability()
    mode_info = mode_status.get(config.mode)
    if mode_info and not mode_info["available"]:
        return jsonify({
            "error": "mode_unsupported",
            "mode": config.mode,
            "message": f"Mode '{config.mode}' is not available on this system.",
            "details": mode_info.get("limitations"),
            "suggestion": "See /api/system/capabilities for available modes and setup instructions.",
        }), 422

    logger.info(
        "Experiment request: mode=%s host=%s reps=%d",
        config.mode, config.target_host, config.repetitions
    )

    # ── Create a 'pending' record in the database ────────────────────────
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO experiments
               (mode, repetitions, concurrency, warmup_runs, timeout_s,
                target_host, target_port, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (config.mode, config.repetitions, config.concurrency,
             config.warmup_runs, config.timeout_s,
             config.target_host, config.target_port, "running"),
        )
        exp_id = cur.lastrowid

    # ── Run the experiment ────────────────────────────────────────────────
    # Note: this runs synchronously. For a production app you'd use Celery/RQ.
    # For this academic project, synchronous is fine — timeouts bound the wait.
    try:
        summary = run_experiment(config)
    except Exception as exc:
        logger.exception("Unexpected error running experiment %d", exp_id)
        with get_connection() as conn:
            conn.execute(
                "UPDATE experiments SET status=?, error_summary=? WHERE id=?",
                ("failed", str(exc)[:500], exp_id),
            )
        return jsonify({"error": "Internal error running experiment.", "detail": str(exc)[:200]}), 500

    # ── Persist results ───────────────────────────────────────────────────
    with get_connection() as conn:
        conn.execute(
            """UPDATE experiments SET
               status=?, mean_latency_ms=?, median_latency_ms=?,
               min_latency_ms=?, max_latency_ms=?, std_latency_ms=?,
               mean_bytes=?, median_bytes=?,
               success_count=?, failure_count=?, success_rate_pct=?,
               negotiated_tls_ver=?, negotiated_group=?,
               error_summary=?, openssl_version=?
               WHERE id=?""",
            (
                summary.status,
                summary.mean_latency_ms,
                summary.median_latency_ms,
                summary.min_latency_ms,
                summary.max_latency_ms,
                summary.std_latency_ms,
                summary.mean_bytes,
                summary.median_bytes,
                summary.success_count,
                summary.failure_count,
                summary.success_rate_pct,
                summary.negotiated_tls_ver,
                summary.negotiated_group,
                summary.error_summary,
                summary.openssl_version,
                exp_id,
            ),
        )
        # Store individual handshake results
        for r in summary.results:
            conn.execute(
                """INSERT INTO handshake_results
                   (experiment_id, run_index, is_warmup, started_at,
                    latency_ms, bytes_sent, bytes_received,
                    tls_version, tls_group, cipher_suite,
                    success, error_type, error_detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    exp_id, r.run_index, int(r.is_warmup), r.started_at,
                    r.latency_ms, r.bytes_sent, r.bytes_received,
                    r.tls_version, r.tls_group, r.cipher_suite,
                    int(r.success), r.error_type, r.error_detail,
                ),
            )

        # Fetch the saved record to return
        row = conn.execute(
            "SELECT * FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        result = row_to_dict(row)

    return jsonify({"experiment": result, "summary": summary.to_dict()}), 201


@experiments_bp.route("/", methods=["GET"])
def list_experiments():
    """List all experiments, newest first."""
    limit = min(int(request.args.get("limit", 50)), 200)
    mode_filter = request.args.get("mode")

    with get_connection() as conn:
        if mode_filter and mode_filter in VALID_MODES:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE mode=? ORDER BY id DESC LIMIT ?",
                (mode_filter, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM experiments ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    return jsonify({"experiments": rows_to_list(rows), "count": len(rows)})


@experiments_bp.route("/<int:exp_id>", methods=["GET"])
def get_experiment(exp_id: int):
    """Get one experiment record and its individual handshake results."""
    with get_connection() as conn:
        exp_row = conn.execute(
            "SELECT * FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        if not exp_row:
            return jsonify({"error": f"Experiment {exp_id} not found."}), 404

        hs_rows = conn.execute(
            "SELECT * FROM handshake_results WHERE experiment_id=? ORDER BY run_index",
            (exp_id,),
        ).fetchall()

    return jsonify({
        "experiment": row_to_dict(exp_row),
        "handshake_results": rows_to_list(hs_rows),
    })


@experiments_bp.route("/<int:exp_id>", methods=["DELETE"])
def delete_experiment(exp_id: int):
    """Delete an experiment and its handshake results."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM experiments WHERE id=?", (exp_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": f"Experiment {exp_id} not found."}), 404
        conn.execute("DELETE FROM handshake_results WHERE experiment_id=?", (exp_id,))
        conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))

    return jsonify({"deleted": exp_id})
