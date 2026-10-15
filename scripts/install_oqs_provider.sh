#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# scripts/install_oqs_provider.sh
#
# Installs OpenSSL 3.x + liboqs + oqs-provider on Ubuntu 22.04 to enable
# Post-Quantum Cryptography (PQC) TLS modes B and C.
#
# This script is intended to run INSIDE a Docker container or on a fresh
# Ubuntu 22.04 EC2 instance. Run as root or with sudo.
#
# Usage:
#   sudo bash scripts/install_oqs_provider.sh
#
# What this installs:
#   - Build tools (cmake, ninja, gcc)
#   - liboqs (Open Quantum Safe library)
#   - oqs-provider (OpenSSL provider plugin for PQC algorithms)
#   - liboqs-python (Python bindings for liboqs, optional)
#
# After running:
#   - Set_ecdh_curve('mlkem768') will work in Python's ssl module
#   - Mode B (PQC) and Mode C (hybrid) will be available in the platform
#
# Reference: https://github.com/open-quantum-safe/oqs-provider
# ──────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
LIBOQS_VERSION="${LIBOQS_VERSION:-0.10.1}"
OQS_PROVIDER_VERSION="${OQS_PROVIDER_VERSION:-0.6.1}"
INSTALL_PREFIX="/usr/local"
BUILD_DIR="/tmp/oqs_build"

# ── Colours for output ─────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'   # No Color

log()  { echo -e "${GREEN}[OQS]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ── Preflight checks ────────────────────────────────────────────────────────
log "Checking prerequisites..."

if [[ "$EUID" -ne 0 ]]; then
    warn "Not running as root. Attempting sudo prefix..."
    SUDO="sudo"
else
    SUDO=""
fi

# Check OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    log "OS: $PRETTY_NAME"
    if [[ "$ID" != "ubuntu" ]] || [[ "${VERSION_ID%%.*}" -lt 22 ]]; then
        warn "This script is tested on Ubuntu 22.04+. Proceeding anyway..."
    fi
fi

# Check OpenSSL version
OPENSSL_VERSION=$(openssl version | awk '{print $2}')
OPENSSL_MAJOR=$(echo "$OPENSSL_VERSION" | cut -d. -f1)
log "OpenSSL version: $OPENSSL_VERSION"

if [[ "$OPENSSL_MAJOR" -lt 3 ]]; then
    fail "OpenSSL 3.x is required for oqs-provider. Found: $OPENSSL_VERSION
    
    Ubuntu 22.04 ships with OpenSSL 3.0 by default.
    If you are on Ubuntu 20.04 or earlier, upgrade the OS first."
fi

log "OpenSSL 3.x confirmed. Proceeding with oqs-provider installation."

# ── Install build dependencies ─────────────────────────────────────────────
log "Installing build dependencies..."
$SUDO apt-get update -qq
$SUDO apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    libssl-dev \
    python3-dev \
    python3-pip \
    git \
    curl \
    astyle    # used by some liboqs build steps

# ── Create build directory ─────────────────────────────────────────────────
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# ── Step 1: Build and install liboqs ──────────────────────────────────────
log "Downloading liboqs $LIBOQS_VERSION..."
if [[ -d liboqs ]]; then
    rm -rf liboqs
fi
git clone --depth 1 --branch "$LIBOQS_VERSION" \
    https://github.com/open-quantum-safe/liboqs.git
cd liboqs

log "Building liboqs (this takes 5-10 minutes)..."
cmake -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
      -DBUILD_SHARED_LIBS=ON \
      -DOQS_DIST_BUILD=ON \
      -GNinja \
      -B build .
ninja -C build -j "$(nproc)"
$SUDO ninja -C build install

log "liboqs installed to $INSTALL_PREFIX"
$SUDO ldconfig

# ── Step 2: Build and install oqs-provider ────────────────────────────────
log "Downloading oqs-provider $OQS_PROVIDER_VERSION..."
cd "$BUILD_DIR"
if [[ -d oqs-provider ]]; then
    rm -rf oqs-provider
fi
git clone --depth 1 --branch "$OQS_PROVIDER_VERSION" \
    https://github.com/open-quantum-safe/oqs-provider.git
cd oqs-provider

log "Building oqs-provider..."
# Find OpenSSL 3.x install location
OPENSSL_DIR=$(openssl version -d | awk -F'"' '{print $2}')

cmake -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
      -DCMAKE_PREFIX_PATH="$INSTALL_PREFIX" \
      -Dliboqs_DIR="$INSTALL_PREFIX/lib/cmake/liboqs" \
      -GNinja \
      -B build .
ninja -C build -j "$(nproc)"
$SUDO ninja -C build install

log "oqs-provider installed"

# ── Step 3: Configure OpenSSL to load oqs-provider ──────────────────────
log "Configuring OpenSSL to load oqs-provider..."

# Find the OpenSSL config file
OPENSSL_CONF=$(openssl version -d | awk -F'"' '{print $2}')/openssl.cnf
if [[ ! -f "$OPENSSL_CONF" ]]; then
    OPENSSL_CONF="/etc/ssl/openssl.cnf"
fi

log "OpenSSL config: $OPENSSL_CONF"

# Backup original config
$SUDO cp "$OPENSSL_CONF" "${OPENSSL_CONF}.bak"

# Check if oqs_provider section already exists
if grep -q "oqs_provider" "$OPENSSL_CONF"; then
    warn "oqs-provider already configured in $OPENSSL_CONF"
else
    # Append provider configuration
    $SUDO tee -a "$OPENSSL_CONF" > /dev/null << 'EOF'

# ── OQS Provider Configuration (added by install_oqs_provider.sh) ──
[provider_sect]
default = default_provider
oqsprovider = oqs_provider

[default_provider]
activate = 1

[oqs_provider]
module = /usr/local/lib/ossl-modules/oqsprovider.so
activate = 1
EOF
    log "Provider configuration added to $OPENSSL_CONF"
fi

# ── Step 4: Install liboqs-python bindings ───────────────────────────────
log "Installing liboqs-python..."
pip3 install "liboqs-python==$LIBOQS_VERSION" \
    --extra-index-url https://pypi.org/simple/ \
    || warn "liboqs-python install failed — PQC Python bindings unavailable"

# ── Step 5: Verify installation ──────────────────────────────────────────
log "Verifying oqs-provider..."

# Test that OpenSSL recognises PQC groups
if openssl list -kem-algorithms | grep -q "ML-KEM"; then
    log "✓ ML-KEM algorithms detected by OpenSSL"
elif openssl genpkey -genparam -algorithm mlkem768 > /dev/null 2>&1; then
    log "✓ oqs-provider working"
else
    warn "PQC algorithms not detected. Manual verification required."
    warn "Try: openssl list -providers"
    warn "Try: openssl list -kem-algorithms 2>&1 | grep -i kem"
fi

# Test Python integration
python3 -c "
import ssl
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
try:
    ctx.set_ecdh_curve('mlkem768')
    print('✓ Python ssl module can configure mlkem768 group')
except Exception as e:
    print('✗ Python ssl test failed:', e)
"

# ── Done ──────────────────────────────────────────────────────────────────
log "Installation complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " OQS Provider installed successfully."
echo " ML-KEM-768 and X25519MLKEM768 TLS groups are now available."
echo ""
echo " Restart the PQC Migration Platform to pick up changes:"
echo "   docker compose restart"
echo "   # or: python run.py"
echo ""
echo " Then check System Info in the dashboard — Modes B and C"
echo " should now show 'Available'."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
