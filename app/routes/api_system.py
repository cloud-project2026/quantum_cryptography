"""
System Information API Routes
==============================

GET /api/system/capabilities   — OpenSSL version, TLS support, mode availability
GET /api/system/status         — Quick server status (used by dashboard header)
"""

import ssl
import sys
import platform
import logging
from flask import Blueprint, jsonify, current_app
from app.services.crypto_capabilities import get_full_capabilities

system_bp = Blueprint("system", __name__)
logger = logging.getLogger(__name__)

# Cache capabilities to avoid re-probing on every request
_capabilities_cache = None


@system_bp.route("/capabilities", methods=["GET"])
def get_capabilities():
    """
    Return a complete picture of what cryptographic modes are available.

    This is the source of truth the frontend uses to enable/disable
    the Mode B and Mode C selectors and show installation guidance.
    """
    global _capabilities_cache
    if _capabilities_cache is None:
        try:
            _capabilities_cache = get_full_capabilities()
        except Exception as exc:
            logger.exception("Error detecting capabilities")
            return jsonify({"error": str(exc)}), 500
    return jsonify(_capabilities_cache)


@system_bp.route("/status", methods=["GET"])
def get_status():
    """Quick status check used by the dashboard header."""
    from app.models.database import get_connection
    try:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
            latest = conn.execute(
                "SELECT mode, status, created_at, mean_latency_ms "
                "FROM experiments ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except Exception as exc:
        return jsonify({
            "server": "error",
            "database": str(exc),
            "total_experiments": 0,
        }), 500

    return jsonify({
        "server": "running",
        "version": current_app.config.get("VERSION", "unknown"),
        "openssl_version": ssl.OPENSSL_VERSION,
        "python_version": sys.version.split()[0],
        "platform": platform.system(),
        "total_experiments": total,
        "latest_experiment": dict(latest) if latest else None,
        "database": "ok",
    })
