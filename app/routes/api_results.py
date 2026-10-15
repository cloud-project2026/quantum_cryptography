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


def _get_latest_for_mode(conn, mode: str):
    """Get the most recently completed experiment for a given mode."""
    row = conn.execute(
        "SELECT * FROM experiments WHERE mode=? AND status='completed' "
        "ORDER BY id DESC LIMIT 1",
        (mode,),
    ).fetchone()
    return dict(row) if row else None


@results_bp.route("/compare", methods=["GET"])
def compare_results():
    """
    Return a side-by-side comparison of classical vs. PQC vs. hybrid.

    Optional query params:
      classical_id=<int>  — use a specific experiment (default: latest completed)
      pqc_id=<int>
      hybrid_id=<int>
    """
    with get_connection() as conn:
        def _get_by_id_or_latest(mode: str, param_name: str):
            id_param = request.args.get(param_name)
            if id_param:
                try:
                    exp_id = int(id_param)
                    row = conn.execute(
                        "SELECT * FROM experiments WHERE id=? AND mode=?",
                        (exp_id, mode),
                    ).fetchone()
                    return dict(row) if row else None
                except (ValueError, TypeError):
                    return None
            return _get_latest_for_mode(conn, mode)

        classical = _get_by_id_or_latest("classical", "classical_id")
        pqc = _get_by_id_or_latest("pqc", "pqc_id")
        hybrid = _get_by_id_or_latest("hybrid", "hybrid_id")

    comparison = compute_comparison(classical, pqc, hybrid)
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
