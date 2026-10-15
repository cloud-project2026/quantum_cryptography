"""
Results API Routes
==================

GET  /api/results/compare          — Comparison across the three modes
GET  /api/results/export?fmt=csv   — Export all results as CSV or JSON
GET  /api/results/summary          — High-level stats for dashboard cards
"""

import json
import logging
from flask import Blueprint, request, jsonify, Response
from app.models.database import get_connection, rows_to_list
from app.services.metrics import compute_comparison, export_to_csv

results_bp = Blueprint("results", __name__)
logger = logging.getLogger(__name__)


def _get_aggregated_for_mode(conn, mode: str):
    """
    Aggregate ALL completed experiments for a given mode into a single
    averaged summary row — so the comparison graphs reflect the full
    experiment history, not just the most recent run.

    Falls back to a synthetic 'failed' record (for hybrid without oqs-provider)
    so the mode still appears in charts with 0% success rate.
    """
    import statistics as _stats

    rows = conn.execute(
        "SELECT * FROM experiments WHERE mode=? AND status='completed' ORDER BY id",
        (mode,),
    ).fetchall()

    if not rows:
        # Check if there are any failed runs (e.g. hybrid without oqs-provider)
        failed = conn.execute(
            "SELECT * FROM experiments WHERE mode=? ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()
        return dict(failed) if failed else None

    dicts = [dict(r) for r in rows]

    def _avg(key):
        vals = [d[key] for d in dicts if d.get(key) is not None]
        return _stats.mean(vals) if vals else None

    def _first(key):
        for d in dicts:
            if d.get(key) is not None:
                return d[key]
        return None

    total_success = sum(d.get("success_count") or 0 for d in dicts)
    total_failure = sum(d.get("failure_count") or 0 for d in dicts)
    total_all = total_success + total_failure
    agg_success_rate = (total_success / total_all * 100) if total_all > 0 else None

    return {
        "id":                 None,          # aggregated — no single ID
        "mode":               mode,
        "status":             "completed",
        "repetitions":        sum(d.get("repetitions") or 0 for d in dicts),
        "experiment_count":   len(dicts),
        "mean_latency_ms":    _avg("mean_latency_ms"),
        "median_latency_ms":  _avg("median_latency_ms"),
        "min_latency_ms":     min((d["min_latency_ms"] for d in dicts if d.get("min_latency_ms") is not None), default=None),
        "max_latency_ms":     max((d["max_latency_ms"] for d in dicts if d.get("max_latency_ms") is not None), default=None),
        "std_latency_ms":     _avg("std_latency_ms"),
        "mean_bytes":         _avg("mean_bytes"),
        "median_bytes":       _avg("median_bytes"),
        "success_count":      total_success,
        "failure_count":      total_failure,
        "success_rate_pct":   agg_success_rate,
        "negotiated_tls_ver": _first("negotiated_tls_ver"),
        "negotiated_group":   _first("negotiated_group"),
        "openssl_version":    _first("openssl_version"),
    }


def _get_single_experiment(conn, exp_id: int, mode: str):
    """Get one specific experiment by ID."""
    row = conn.execute(
        "SELECT * FROM experiments WHERE id=? AND mode=?",
        (exp_id, mode),
    ).fetchone()
    return dict(row) if row else None


@results_bp.route("/compare", methods=["GET"])
def compare_results():
    """
    Return a side-by-side comparison of classical vs. PQC vs. hybrid.

    By default, aggregates ALL completed experiments per mode so the
    graphs reflect the full history.

    Optional query params to pin a specific experiment:
      classical_id=<int>
      pqc_id=<int>
      hybrid_id=<int>
    """
    with get_connection() as conn:
        def _get_by_id_or_aggregated(mode: str, param_name: str):
            id_param = request.args.get(param_name)
            if id_param:
                try:
                    return _get_single_experiment(conn, int(id_param), mode)
                except (ValueError, TypeError):
                    pass
            return _get_aggregated_for_mode(conn, mode)

        classical = _get_by_id_or_aggregated("classical", "classical_id")
        pqc       = _get_by_id_or_aggregated("pqc",       "pqc_id")
        hybrid    = _get_by_id_or_aggregated("hybrid",    "hybrid_id")

    comparison = compute_comparison(classical, pqc, hybrid)
    # Annotate with experiment counts for the frontend info panel
    for mode_key, exp in [("classical", classical), ("pqc", pqc), ("hybrid", hybrid)]:
        if exp and comparison.get(mode_key):
            comparison[mode_key]["experiment_count"] = exp.get("experiment_count", 1)
    return jsonify(comparison)


@results_bp.route("/export", methods=["GET"])
def export_results():
    """
    Export all (or filtered) experiment results.

    Query params:
      fmt=csv|json        (default: json)
      mode=classical|pqc|hybrid   (optional filter)
      limit=<int>         (default: 1000)
    """
    fmt = request.args.get("fmt", "json").lower()
    mode = request.args.get("mode")
    limit = min(int(request.args.get("limit", 1000)), 5000)

    with get_connection() as conn:
        if mode and mode in {"classical", "pqc", "hybrid"}:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE mode=? ORDER BY id DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM experiments ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    data = rows_to_list(rows)

    if fmt == "csv":
        csv_content = export_to_csv(data)
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=pqc_experiments.csv"},
        )
    else:
        return Response(
            json.dumps({"experiments": data, "count": len(data)}, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=pqc_experiments.json"},
        )


@results_bp.route("/summary", methods=["GET"])
def summary():
    """Dashboard summary cards: total counts, average latencies per mode."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        by_mode = conn.execute(
            """SELECT mode,
                      COUNT(*) as count,
                      AVG(mean_latency_ms) as avg_latency,
                      SUM(success_count) as total_successes,
                      SUM(failure_count) as total_failures
               FROM experiments
               WHERE status='completed'
               GROUP BY mode"""
        ).fetchall()

        recent = conn.execute(
            "SELECT id, mode, status, created_at, mean_latency_ms "
            "FROM experiments ORDER BY id DESC LIMIT 5"
        ).fetchall()

    return jsonify({
        "total_experiments": total,
        "by_mode": rows_to_list(by_mode),
        "recent": rows_to_list(recent),
    })
