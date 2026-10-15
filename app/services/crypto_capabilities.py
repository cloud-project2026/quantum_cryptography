"""
Cryptographic Capabilities Detection Service
============================================

This module probes the current Python/OpenSSL environment and reports
exactly which TLS modes are actually available. It never pretends a mode
works — if something is missing, we say so clearly.

How TLS key exchange works (beginner explanation):
─────────────────────────────────────────────────
When your browser connects to a server over TLS, before any data is sent,
both sides run a "handshake" to agree on a shared secret key. This is called
key exchange (or key establishment). Different algorithms do this step
differently:

  • Classical (X25519):    Uses elliptic curve math. Fast, widely deployed.
                           Vulnerable to quantum computers in the future.
  • Post-quantum (ML-KEM): Uses lattice math (much harder for quantum computers).
                           Standardised by NIST in 2024 (FIPS 203).
  • Hybrid:               Does BOTH at once — X25519 *and* ML-KEM. Even if one
                           is broken, the other still protects you.

ML-KEM only changes the KEY EXCHANGE step. The bulk encryption (AES-GCM etc.)
and authentication (certificates) stay the same unless you also upgrade those.

Environment reality on this machine:
  Python 3.10.11 ships with OpenSSL 1.1.1t, which predates PQC standardisation.
  ML-KEM / X25519MLKEM768 require OpenSSL 3.3+ with the oqs-provider plugin.
  We detect this accurately rather than faking support.

  IMPORTANT: On OpenSSL 1.1.x, set_ecdh_curve() does NOT accept 'x25519' by name
  (it is handled internally by OpenSSL 1.1.x as a special case, not as a named
  EC curve). Only NIST P-curves like prime256v1 are accepted by name.
  On OpenSSL 3.x with oqs-provider, PQC group names like 'mlkem768' are accepted.
"""

import ssl
import sys
import platform
import socket
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ── Known PQC group identifiers (for detection if oqs-provider is present) ────
# These are the group names OpenSSL/OQS provider uses in TLS.
# Source: https://github.com/open-quantum-safe/oqs-provider
PQC_GROUPS = {
    "mlkem512":        "ML-KEM-512 (post-quantum only)",
    "mlkem768":        "ML-KEM-768 (post-quantum only)",
    "mlkem1024":       "ML-KEM-1024 (post-quantum only)",
    "p256_mlkem512":   "P-256 + ML-KEM-512 (hybrid)",
    "x25519_mlkem512": "X25519 + ML-KEM-512 (hybrid)",
    "p384_mlkem768":   "P-384 + ML-KEM-768 (hybrid)",
    "x25519_mlkem768": "X25519MLKEM768 (hybrid) — IETF draft",
    "p521_mlkem1024":  "P-521 + ML-KEM-1024 (hybrid)",
}

# Classical groups: x25519 is special on OpenSSL 1.1.x — it cannot be set
# by name via set_ecdh_curve(). We check it differently (it's always available
# on any modern OpenSSL that supports TLS 1.3).
CLASSICAL_NAMED_CURVES = ["prime256v1", "secp384r1", "secp521r1"]

# X25519 is available in any OpenSSL that supports TLS 1.3 (1.1.1+)
# but cannot be probed via set_ecdh_curve on 1.1.x
X25519_TLS13_AVAILABLE = True  # Always true if TLS 1.3 is present


def get_openssl_version() -> Dict[str, Any]:
    """Return structured OpenSSL version info."""
    ver = ssl.OPENSSL_VERSION
    ver_info = ssl.OPENSSL_VERSION_INFO  # (major, minor, fix, patch, status)
    return {
        "string": ver,
        "major": ver_info[0],
        "minor": ver_info[1],
        "fix": ver_info[2],
        "full_tuple": list(ver_info),
        # OpenSSL 3.3+ required for native ML-KEM
        "supports_native_pqc": ver_info >= (3, 3, 0, 0, 0),
        # OpenSSL 3.x required for oqs-provider
        "supports_oqs_provider": ver_info >= (3, 0, 0, 0, 0),
    }


def get_tls_version_support() -> Dict[str, bool]:
    """Probe which TLS protocol versions are compiled in."""
    return {
        "TLSv1.0": hasattr(ssl, "PROTOCOL_TLSv1"),
        "TLSv1.1": hasattr(ssl, "PROTOCOL_TLSv1_1"),
        "TLSv1.2": hasattr(ssl, "PROTOCOL_TLSv1_2"),
        "TLSv1.3": (
            hasattr(ssl, "TLSVersion")
            and hasattr(ssl.TLSVersion, "TLSv1_3")
        ),
    }


def get_available_ciphers() -> List[str]:
    """Return cipher suite names supported by this OpenSSL build."""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return [c["name"] for c in ctx.get_ciphers()]
    except Exception as exc:
        logger.warning("Could not enumerate ciphers: %s", exc)
        return []


def _try_set_curve(group_name: str) -> bool:
    """
    Try to set a named group/curve on an SSL context.
    Returns True only if accepted without error.

    NOTE: On OpenSSL 1.1.x, 'x25519' is NOT accepted by set_ecdh_curve()
    even though the algorithm is fully supported. Only P-curves (prime256v1 etc.)
    and PQC groups (via oqs-provider on OpenSSL 3.x) work with this call.
    """
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ecdh_curve(group_name)
        return True
    except (ssl.SSLError, OSError, ValueError):
        return False


def detect_pqc_support() -> Dict[str, Any]:
    """
    Attempt to determine whether PQC key-exchange groups are available.

    Strategy:
    1. Check OpenSSL version.
    2. Try importing the 'oqs' Python bindings (liboqs-python).
    3. Try setting a PQC group name via set_ecdh_curve (only works with oqs-provider).

    We do NOT claim support unless we can actually verify it.
    """
    oqs_ver_info = get_openssl_version()

    result = {
        "liboqs_python_available": False,
        "liboqs_python_version": None,
        "oqs_provider_configured": False,
        "native_mlkem_possible": oqs_ver_info["supports_native_pqc"],
        "pqc_groups_detected": [],
        "details": [],
    }

    # ── Check liboqs Python bindings ──────────────────────────────────────
    try:
        import oqs  # type: ignore
        result["liboqs_python_available"] = True
        result["liboqs_python_version"] = getattr(oqs, "__version__", "unknown")
        enabled_kems = (
            oqs.get_enabled_KEM_mechanisms()
            if hasattr(oqs, "get_enabled_KEM_mechanisms")
            else []
        )
        result["details"].append(
            f"liboqs-python available. Enabled KEMs: {len(enabled_kems)}"
        )
        for kem in ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024", "Kyber512", "Kyber768"]:
            if kem in enabled_kems:
                result["pqc_groups_detected"].append(kem)
    except ImportError:
        result["details"].append(
            "liboqs-python not installed. "
            "Install it with: pip install liboqs-python  (requires liboqs native library)"
        )

    # ── Check OpenSSL version for oqs-provider compatibility ─────────────
    if not oqs_ver_info["supports_oqs_provider"]:
        result["details"].append(
            f"OpenSSL {oqs_ver_info['string']} is version 1.x — "
            "oqs-provider requires OpenSSL 3.0+. "
            "PQC TLS groups (mlkem768, x25519_mlkem768) are unavailable on this system. "
            "See docs/setup.md for upgrade instructions."
        )
    else:
        result["details"].append(
            "OpenSSL 3.x detected — oqs-provider CAN be installed "
            "(but check if it is actually loaded)."
        )
        # Try a PQC group name — only works if oqs-provider is loaded
        if _try_set_curve("mlkem768"):
            result["oqs_provider_configured"] = True
            result["pqc_groups_detected"].append("mlkem768")
            result["details"].append(
                "oqs-provider IS active — mlkem768 group accepted."
            )
            if _try_set_curve("x25519_mlkem768"):
                result["pqc_groups_detected"].append("x25519_mlkem768")
        else:
            result["details"].append(
                "oqs-provider NOT active (or not installed). "
                "mlkem768 group was not accepted by OpenSSL."
            )

    return result


def get_classical_group_support() -> Dict[str, bool]:
    """
    Check which classical elliptic-curve groups are available via set_ecdh_curve.

    On OpenSSL 1.1.x:
      - 'x25519' is handled internally and CANNOT be set by name. We report it
        as available if TLS 1.3 is supported (which requires X25519 support).
      - P-curves (prime256v1, etc.) CAN be probed by name.

    On OpenSSL 3.x + oqs-provider:
      - All classical and PQC groups can be probed by name.
    """
    tls13 = get_tls_version_support().get("TLSv1.3", False)
    support = {
        # X25519 is available whenever TLS 1.3 is available
        "x25519": tls13,
    }
    for group in CLASSICAL_NAMED_CURVES:
        support[group] = _try_set_curve(group)
    return support


def get_mode_availability() -> Dict[str, Dict[str, Any]]:
    """
    Return a comprehensive status for each of the three experiment modes.

    This is what the frontend 'System Information' page displays and what
    the benchmark engine reads before starting a run.
    """
    oqs_info = get_openssl_version()
    pqc = detect_pqc_support()
    classical_groups = get_classical_group_support()
    tls13_ok = get_tls_version_support().get("TLSv1.3", False)

    # Mode A: Classical TLS — available whenever TLS 1.3 / X25519 is present
    mode_a = {
        "name": "Mode A — Classical TLS (X25519)",
        "available": tls13_ok,  # X25519 is mandatory in TLS 1.3
        "group": "x25519",
        "description": (
            "TLS 1.3 handshake using X25519 elliptic-curve Diffie-Hellman. "
            "This is the current internet standard. Fast and widely supported. "
            "Note: X25519 is built into OpenSSL's TLS 1.3 stack and is always "
            "available when TLS 1.3 is compiled in."
        ),
        "limitations": None if tls13_ok else "TLS 1.3 not available on this system.",
    }

    # Mode B: Post-quantum only TLS
    pqc_available = pqc["oqs_provider_configured"] or pqc["liboqs_python_available"]
    mode_b = {
        "name": "Mode B — Post-Quantum TLS (ML-KEM-768)",
        "available": pqc_available,
        "group": "mlkem768" if pqc_available else None,
        "description": (
            "TLS 1.3 key exchange using ML-KEM-768 only (no classical fallback). "
            "ML-KEM is the NIST FIPS 203 standard lattice-based KEM. "
            "Provides key establishment security against quantum adversaries. "
            "(Note: certificate authentication remains classical RSA/ECDSA "
            "unless upgraded separately.)"
        ),
        "limitations": (
            None
            if pqc_available
            else (
                "Requires OpenSSL 3.0+ WITH oqs-provider installed, "
                f"OR liboqs-python bindings. "
                f"Current OpenSSL: {oqs_info['string']}. "
                "See docs/setup.md for installation instructions."
            )
        ),
    }

    # Mode C: Hybrid TLS
    mode_c = {
        "name": "Mode C — Hybrid TLS (X25519 + ML-KEM-768)",
        "available": pqc_available,
        "group": "x25519_mlkem768" if pqc_available else None,
        "description": (
            "Combines X25519 (classical) with ML-KEM-768 (post-quantum) in a single "
            "key exchange. Both algorithms must be broken for the session to be "
            "compromised. Recommended migration strategy — provides quantum resistance "
            "while maintaining backward compatibility signalling."
        ),
        "limitations": (
            None
            if pqc_available
            else (
                "Same requirements as Mode B. "
                "oqs-provider must be installed and loaded in OpenSSL 3.x."
            )
        ),
    }

    return {
        "classical": mode_a,
        "pqc": mode_b,
        "hybrid": mode_c,
    }


def get_full_capabilities() -> Dict[str, Any]:
    """Master function that assembles all capability info for the API."""
    openssl = get_openssl_version()
    tls_ver = get_tls_version_support()
    pqc = detect_pqc_support()
    modes = get_mode_availability()
    classical_groups = get_classical_group_support()

    return {
        "openssl": openssl,
        "python_version": sys.version,
        "platform": platform.platform(),
        "tls_versions": tls_ver,
        "classical_groups": classical_groups,
        "pqc_detection": pqc,
        "modes": modes,
        "summary": {
            "classical_available": modes["classical"]["available"],
            "pqc_available": modes["pqc"]["available"],
            "hybrid_available": modes["hybrid"]["available"],
            "any_pqc": modes["pqc"]["available"] or modes["hybrid"]["available"],
        },
    }
