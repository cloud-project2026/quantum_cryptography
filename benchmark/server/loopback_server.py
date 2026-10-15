"""
Loopback TLS Server for Local Benchmarking
==========================================

This creates a minimal TLS 1.3 server that listens on localhost.
It lets us run benchmarks without internet access and without depending
on external servers that might be slow or unreliable.

Self-signed certificate explanation:
  A real TLS certificate is signed by a trusted Certificate Authority (CA)
  like Let's Encrypt. For LOCAL TESTING ONLY, we generate our own "self-signed"
  certificate — it provides encryption but any client would normally refuse it
  because it's not signed by a trusted CA.
  
  In our benchmark, we disable certificate verification (ctx.verify_mode = CERT_NONE)
  because we're only measuring handshake PERFORMANCE, not testing certificate trust.
  Never do this in production code.
"""

import ssl
import socket
import threading
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)


def _generate_self_signed_cert() -> tuple:
    """
    Generate a self-signed TLS certificate and private key for local testing.

    Uses the cryptography library (installed as a dependency).
    Returns (cert_path, key_path) — paths to PEM files written to a temp directory.
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    import datetime

    # Generate an EC private key (P-256 curve — compact and fast)
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

    # Build a minimal self-signed certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PQC Benchmark Lab"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # Write to temp files
    tmp_dir = tempfile.mkdtemp(prefix="pqc_bench_")
    cert_path = os.path.join(tmp_dir, "server.crt")
    key_path = os.path.join(tmp_dir, "server.key")

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )

    logger.info("Self-signed cert generated at %s", tmp_dir)
    return cert_path, key_path


_server_cert_path: str = None
_server_key_path: str = None
_server_running: bool = False


def run_loopback_server(host: str = "127.0.0.1", port: int = 54443) -> None:
    """
    Run a blocking TLS 1.3 echo server on host:port.

    Each accepted connection:
      1. Completes the TLS handshake.
      2. Reads an HTTP GET request.
      3. Sends back a minimal HTTP 200 response.
      4. Closes the connection.

    This is intentionally minimal — we only care about the handshake,
    not the application data exchange.
    """
    global _server_cert_path, _server_key_path, _server_running

    # Generate cert once
    if _server_cert_path is None:
        try:
            _server_cert_path, _server_key_path = _generate_self_signed_cert()
        except Exception as exc:
            logger.error("Failed to generate self-signed cert: %s", exc)
            return

    # Build server SSL context
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(_server_cert_path, _server_key_path)

    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    except Exception:
        pass  # Older OpenSSL may not support minimum_version

    # Create a listening socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw_server:
        raw_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            raw_server.bind((host, port))
        except OSError as exc:
            logger.error("Cannot bind loopback server to %s:%d — %s", host, port, exc)
            return

        raw_server.listen(50)
        raw_server.settimeout(1.0)  # so we can check _server_running flag
        _server_running = True
        logger.info("Loopback TLS server listening on %s:%d", host, port)

        while _server_running:
            try:
                client_raw, addr = raw_server.accept()
            except socket.timeout:
                continue  # check _server_running again
            except Exception:
                break

            # Handle each client in its own thread
            t = threading.Thread(
                target=_handle_client,
                args=(ctx, client_raw, addr),
                daemon=True,
            )
            t.start()


def _handle_client(
    ctx: ssl.SSLContext,
    raw_sock: socket.socket,
    addr: tuple,
) -> None:
    """Handle one client connection: TLS handshake → read → respond → close."""
    ssl_sock = None
    try:
        ssl_sock = ctx.wrap_socket(raw_sock, server_side=True)
        ssl_sock.settimeout(5.0)

        # Read the request (we don't care about content)
        data = ssl_sock.recv(2048)

        # Send a minimal HTTP response
        response = (
            "HTTP/1.0 200 OK\r\n"
            "Content-Type: text/plain\r\n"
            "Content-Length: 2\r\n"
            "Connection: close\r\n"
            "\r\n"
            "OK"
        ).encode()
        ssl_sock.sendall(response)

    except ssl.SSLError as exc:
        logger.debug("SSL error with client %s: %s", addr, exc)
    except Exception as exc:
        logger.debug("Client %s error: %s", addr, exc)
    finally:
        if ssl_sock:
            try:
                ssl_sock.close()
            except Exception:
                pass
        else:
            try:
                raw_sock.close()
            except Exception:
                pass


def stop_loopback_server() -> None:
    """Signal the loopback server to stop."""
    global _server_running
    _server_running = False
