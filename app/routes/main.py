"""
Main Routes — HTML page serving and health check.

These routes serve the single-page dashboard (index.html) and the
/health endpoint used by Docker, load balancers, and monitoring tools.
"""

import time
import ssl
import logging
from flask import Blueprint, render_template, jsonify, current_app

main_bp = Blueprint("main", __name__)
logger = logging.getLogger(__name__)

# Track app start time for uptime reporting
_app_start_time = time.time()


@main_bp.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")


@main_bp.route("/health")
def health():
    """
    Health check endpoint.

    Used by:
    - Docker HEALTHCHECK instruction
    - AWS ALB / ELB health checks
    - Monitoring systems (Uptime Robot, etc.)

    Returns HTTP 200 with a JSON body if the app is healthy.
    Returns HTTP 503 if something critical is broken.
    """
    try:
        # Verify database is accessible
        from app.models.database import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
        db_error = None
    except Exception as exc:
        db_ok = False
        db_error = str(exc)
        logger.error("Health check: database error: %s", exc)

    uptime_s = round(time.time() - _app_start_time, 1)
    healthy = db_ok

    payload = {
        "status": "healthy" if healthy else "degraded",
        "version": current_app.config.get("VERSION", "unknown"),
        "uptime_seconds": uptime_s,
        "openssl_version": ssl.OPENSSL_VERSION,
        "database_ok": db_ok,
        "database_error": db_error,
    }

    return jsonify(payload), (200 if healthy else 503)
