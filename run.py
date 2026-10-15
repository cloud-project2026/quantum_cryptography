"""
Application Entry Point
========================

Run with:
    python run.py                        # development server
    gunicorn -w 4 -b 0.0.0.0:5000 run:app  # production (Linux/Docker)

Environment variables (see .env.example):
    SECRET_KEY          — Flask secret key (set to something random in production)
    DATABASE_PATH       — SQLite database file path
    PORT                — Port to listen on (default: 5000)
    ENV                 — 'development' or 'production'
    START_LOOPBACK_SERVER — 'true' to start local TLS test server (default: true)
"""

import os
import sys
import logging

# Add project root to Python path so imports work whether run from project root
# or from a subdirectory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # type: ignore  # optional, graceful if missing

try:
    load_dotenv(".env")
except Exception:
    pass  # python-dotenv not installed; fall back to system env vars

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("ENV", "development") == "development"

    # Optionally start the local loopback TLS server for benchmarking
    # without internet access.
    if os.environ.get("START_LOOPBACK_SERVER", "true").lower() == "true":
        try:
            from app.services.tls_benchmark import start_loopback_server
            loopback_thread = start_loopback_server(host="127.0.0.1", port=54443)
            app.logger.info("Loopback TLS server started on 127.0.0.1:54443")
        except Exception as exc:
            app.logger.warning("Could not start loopback server: %s", exc)

    app.logger.info("Starting Flask on http://0.0.0.0:%d (debug=%s)", port, debug)

    # NOTE: Flask's built-in development server is NOT suitable for production.
    # In production (Docker/EC2) we use Gunicorn (see Dockerfile and docker-compose.yml).
    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug,
        use_reloader=False,   # Disable reloader to prevent double-starting the loopback server
    )
