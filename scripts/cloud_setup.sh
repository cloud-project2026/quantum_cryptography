#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# scripts/cloud_setup.sh
#
# One-shot setup script for a fresh Ubuntu 22.04 EC2 instance.
# Run as: bash cloud_setup.sh
#
# This script:
#   1. Updates system packages
#   2. Installs Docker
#   3. Clones the repository (if not already present)
#   4. Creates a .env file with a generated secret key
#   5. Starts the application with docker compose
#
# After running this script, the application is available at:
#   http://<EC2-PUBLIC-IP>:5000
# ──────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Colour output
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

REPO_URL="${REPO_URL:-https://github.com/cloud-project2026/quantum_cryptography.git}"
APP_DIR="${APP_DIR:-/home/ubuntu/quantum_cryptography}"

log "=== PQC Migration Platform — Cloud Setup ==="
log "EC2 instance: $(curl -s http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null || echo 'unknown')"
log "Public IP: $(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo 'unknown')"

# ── Step 1: System update ────────────────────────────────────────────────
log "Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y git curl python3-pip --no-install-recommends

# ── Step 2: Install Docker ────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    sudo systemctl enable --now docker
    log "Docker installed. You may need to log out and back in for group changes."
else
    log "Docker already installed: $(docker --version)"
fi

# ── Step 3: Clone repository ──────────────────────────────────────────────
if [[ -d "$APP_DIR" ]]; then
    log "Repository already exists at $APP_DIR. Pulling latest..."
    git -C "$APP_DIR" pull
else
    log "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

# ── Step 4: Create .env file ──────────────────────────────────────────────
if [[ -f .env ]]; then
    warn ".env already exists — skipping creation (edit manually if needed)"
else
    log "Generating .env with random SECRET_KEY..."
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << EOF
SECRET_KEY=${SECRET_KEY}
ENV=production
PORT=5000
DATABASE_PATH=/app/results/experiments.db
START_LOOPBACK_SERVER=true
ALLOWED_BENCHMARK_HOSTS=localhost,127.0.0.1
MAX_REPETITIONS=200
MAX_CONCURRENCY=20
EOF
    log ".env created with generated SECRET_KEY"
fi

# ── Step 5: Start the application ─────────────────────────────────────────
log "Building and starting Docker container (this may take a few minutes)..."
sudo docker compose up -d --build

# ── Step 6: Health check ──────────────────────────────────────────────────
log "Waiting for application to start..."
sleep 10

HEALTH=$(curl -s http://localhost:5000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unreachable")

if [[ "$HEALTH" == "healthy" ]]; then
    PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<your-ec2-ip>")
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " ✓ Application is running!"
    echo ""
    echo "  Dashboard:  http://${PUBLIC_IP}:5000"
    echo "  Health:     http://${PUBLIC_IP}:5000/health"
    echo "  API:        http://${PUBLIC_IP}:5000/api/system/status"
    echo ""
    echo "  Logs:       docker compose logs -f"
    echo "  Stop:       docker compose down"
    echo ""
    echo "  ⚠ Remember to terminate the EC2 instance when done"
    echo "    to avoid unexpected charges!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    warn "Health check returned: $HEALTH"
    warn "Application may still be starting. Check: docker compose logs pqc-app"
fi
