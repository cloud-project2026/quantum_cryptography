"""
Post-Quantum Cryptography Migration Platform
Flask Application Factory

This module creates and configures the Flask app. We use the "factory pattern"
which means instead of creating the app directly at module level, we define a
function (create_app) that creates and returns it. This makes testing easier
because each test can get its own fresh app instance.
"""

import os
import logging
from flask import Flask
from flask_cors import CORS


def create_app(config_override: dict = None) -> Flask:
    """
    Application factory function.

    Args:
        config_override: Optional dictionary of config values to override defaults.
                         Used primarily in tests.

    Returns:
        A configured Flask application instance.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # ── Base configuration ────────────────────────────────────────────────────
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-in-production"),
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH",
            os.path.join(os.path.dirname(__file__), "..", "results", "experiments.db"),
        ),
        # Security limits — prevents abuse of the benchmark endpoint
        MAX_REPETITIONS=int(os.environ.get("MAX_REPETITIONS", "200")),
        MAX_CONCURRENCY=int(os.environ.get("MAX_CONCURRENCY", "20")),
        DEFAULT_TIMEOUT=float(os.environ.get("DEFAULT_TIMEOUT", "10.0")),
        # Allowed benchmark targets (SSRF prevention — never allow arbitrary hosts)
        ALLOWED_BENCHMARK_HOSTS=os.environ.get(
            "ALLOWED_BENCHMARK_HOSTS",
            "localhost,127.0.0.1,httpbin.org,example.com",
        ).split(","),
        ENV=os.environ.get("ENV", "development"),
        VERSION="1.0.0",
    )

    if config_override:
        app.config.update(config_override)

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Cross-Origin Resource Sharing lets the browser's JS call our API.
    # In production this should be restricted to your actual domain.
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level = logging.DEBUG if app.config["ENV"] == "development" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.logger.setLevel(log_level)

    # ── Database initialisation ───────────────────────────────────────────────
    # We import here (inside the function) to avoid circular imports.
    from app.models.database import init_db

    with app.app_context():
        init_db(app.config["DATABASE_PATH"])

    # ── Register blueprints (route groups) ───────────────────────────────────
    # Blueprints let us split routes into separate files for each feature area.
    from app.routes.main import main_bp
    from app.routes.api_experiments import experiments_bp
    from app.routes.api_system import system_bp
    from app.routes.api_results import results_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(experiments_bp, url_prefix="/api/experiments")
    app.register_blueprint(system_bp, url_prefix="/api/system")
    app.register_blueprint(results_bp, url_prefix="/api/results")

    app.logger.info(
        "PQC Migration Platform started. ENV=%s", app.config["ENV"]
    )
    return app
