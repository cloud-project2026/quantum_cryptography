"""
Metrics Calculation Service
============================

Calculates comparison metrics between experiment modes, including the
percentage overhead formula specified in the project requirements.

Overhead formula (from project spec):
  percentage_overhead = ((alternative - classical) / classical) * 100

Negative overhead means the alternative is FASTER (an improvement).
"""

import statistics
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def calculate_overhead(baseline: Optional[float], alternative: Optional[float]) -> Optional[float]:
    """
    Calculate percentage overhead of alternative vs. baseline.

    Returns:
        Percentage overhead (negative = improvement, positive = slower).
        None if either value is missing or baseline is zero.
    """
    if baseline is None or alternative is None:
        return None
    if baseline == 0:
        logger.warning("Baseline is zero — overhead calculation not meaningful.")
        return None
    return ((alternative - baseline) / baseline) * 100.0


def compute_comparison(
    classical_exp: Optional[Dict],
    pqc_exp: Optional[Dict],
    hybrid_exp: Optional[Dict],
) -> Dict[str, Any]:
    """
    Build a comparison table between the three modes.

    Each experiment dict should have keys like:
        mean_latency_ms, median_latency_ms, mean_bytes, success_rate_pct

    Returns a dictionary ready to be serialised as JSON for the frontend.
    """

    def extract(exp: Optional[Dict], key: str) -> Optional[float]:
        if exp is None:
            return None
        val = exp.get(key)
        return float(val) if val is not None else None

    base_latency = extract(classical_exp, "mean_latency_ms")
    base_bytes = extract(classical_exp, "mean_bytes")

    comparison = {
        "classical": {
            "mode": "classical",
            "label": "Mode A — Classical TLS (X25519)",
            "mean_latency_ms": extract(classical_exp, "mean_latency_ms"),
            "median_latency_ms": extract(classical_exp, "median_latency_ms"),
            "min_latency_ms": extract(classical_exp, "min_latency_ms"),
            "max_latency_ms": extract(classical_exp, "max_latency_ms"),
            "std_latency_ms": extract(classical_exp, "std_latency_ms"),
            "mean_bytes": extract(classical_exp, "mean_bytes"),
            "success_rate_pct": extract(classical_exp, "success_rate_pct"),
            "latency_overhead_pct": None,   # baseline has no overhead vs itself
            "bytes_overhead_pct": None,
            "negotiated_tls_ver": classical_exp.get("negotiated_tls_ver") if classical_exp else None,
            "negotiated_group": classical_exp.get("negotiated_group") if classical_exp else None,
            "experiment_id": classical_exp.get("id") if classical_exp else None,
        },
        "pqc": {
            "mode": "pqc",
            "label": "Mode B — Post-Quantum TLS (ML-KEM-768)",
            "mean_latency_ms": extract(pqc_exp, "mean_latency_ms"),
            "median_latency_ms": extract(pqc_exp, "median_latency_ms"),
            "min_latency_ms": extract(pqc_exp, "min_latency_ms"),
            "max_latency_ms": extract(pqc_exp, "max_latency_ms"),
            "std_latency_ms": extract(pqc_exp, "std_latency_ms"),
            "mean_bytes": extract(pqc_exp, "mean_bytes"),
            "success_rate_pct": extract(pqc_exp, "success_rate_pct"),
            "latency_overhead_pct": calculate_overhead(
                base_latency, extract(pqc_exp, "mean_latency_ms")
            ),
            "bytes_overhead_pct": calculate_overhead(
                base_bytes, extract(pqc_exp, "mean_bytes")
            ),
            "negotiated_tls_ver": pqc_exp.get("negotiated_tls_ver") if pqc_exp else None,
            "negotiated_group": pqc_exp.get("negotiated_group") if pqc_exp else None,
            "experiment_id": pqc_exp.get("id") if pqc_exp else None,
        },
        "hybrid": {
            "mode": "hybrid",
            "label": "Mode C — Hybrid TLS (X25519 + ML-KEM-768)",
            "mean_latency_ms": extract(hybrid_exp, "mean_latency_ms"),
            "median_latency_ms": extract(hybrid_exp, "median_latency_ms"),
            "min_latency_ms": extract(hybrid_exp, "min_latency_ms"),
            "max_latency_ms": extract(hybrid_exp, "max_latency_ms"),
            "std_latency_ms": extract(hybrid_exp, "std_latency_ms"),
            "mean_bytes": extract(hybrid_exp, "mean_bytes"),
            "success_rate_pct": extract(hybrid_exp, "success_rate_pct"),
            "latency_overhead_pct": calculate_overhead(
                base_latency, extract(hybrid_exp, "mean_latency_ms")
            ),
            "bytes_overhead_pct": calculate_overhead(
                base_bytes, extract(hybrid_exp, "mean_bytes")
            ),
            "negotiated_tls_ver": hybrid_exp.get("negotiated_tls_ver") if hybrid_exp else None,
            "negotiated_group": hybrid_exp.get("negotiated_group") if hybrid_exp else None,
            "experiment_id": hybrid_exp.get("id") if hybrid_exp else None,
        },
        "has_baseline": base_latency is not None,
        "note": (
            "Overhead formula: ((alternative - baseline) / baseline) × 100. "
            "Negative overhead = improvement. "
            "Comparison only valid when experiments run against the same target."
        ),
    }

    return comparison


def aggregate_latencies(latencies: List[float]) -> Dict[str, Optional[float]]:
    """
    Compute all summary statistics for a list of latency values.
    Safe for empty or single-element lists.
    """
    if not latencies:
        return {k: None for k in ["mean", "median", "min", "max", "std"]}
    return {
        "mean": statistics.mean(latencies),
        "median": statistics.median(latencies),
        "min": min(latencies),
        "max": max(latencies),
        "std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    }


def export_to_csv(experiments: List[Dict]) -> str:
    """
    Convert a list of experiment records to CSV string.
    Suitable for download from the dashboard.
    """
    import csv
    import io

    if not experiments:
        return "No experiments to export.\n"

    # Determine columns from first experiment
    fieldnames = [
        "id", "created_at", "mode", "repetitions", "concurrency", "warmup_runs",
        "timeout_s", "target_host", "target_port", "status",
        "mean_latency_ms", "median_latency_ms", "min_latency_ms", "max_latency_ms",
        "std_latency_ms", "mean_bytes", "success_count", "failure_count",
        "success_rate_pct", "negotiated_tls_ver", "negotiated_group",
        "openssl_version", "error_summary",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(experiments)
    return output.getvalue()
