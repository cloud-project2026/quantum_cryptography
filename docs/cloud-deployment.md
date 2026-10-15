# Cloud Deployment Guide — AWS EC2

This guide walks you through deploying the PQC Migration Platform on an AWS EC2 instance using Docker.

> **Important:** This guide describes deployment steps you must perform manually. Cloud resources are not created automatically by the application.

---

## Prerequisites

- An AWS account with EC2 permissions
- AWS CLI installed and configured: `aws configure`
- Your public IP address (for SSH restriction): find at https://checkip.amazonaws.com
- A registered domain name (optional, for HTTPS with Let's Encrypt)

---

## Step 1: Launch an EC2 Instance

### Via AWS Console
1. Go to **EC2 → Launch Instance**
2. Select: **Ubuntu Server 22.04 LTS (HVM), SSD Volume Type**
3. Instance type: **t3.small** (2 vCPU, 2 GB RAM) or larger
4. Key pair: Create or select an existing key pair (you'll need the `.pem` file)
5. Security group: Create new with these rules:

| Type | Protocol | Port | Source | Purpose |
|------|----------|------|--------|---------|
| SSH | TCP | 22 | Your IP/32 | Admin access |
| HTTP | TCP | 80 | 0.0.0.0/0 | HTTP (redirect to HTTPS) |
| HTTPS | TCP | 443 | 0.0.0.0/0 | Application |
| Custom | TCP | 5000 | Your IP/32 | Direct Flask access (testing) |

6. Storage: 20 GB gp3 (enough for SQLite + logs)
7. Launch instance

### Via AWS CLI
```bash
# Create security group
aws ec2 create-security-group \
  --group-name pqc-lab-sg \
  --description "PQC Lab security group"

# Add rules (replace YOUR_IP)
aws ec2 authorize-security-group-ingress --group-name pqc-lab-sg \
  --protocol tcp --port 22 --cidr YOUR_IP/32
aws ec2 authorize-security-group-ingress --group-name pqc-lab-sg \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-name pqc-lab-sg \
  --protocol tcp --port 443 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-name pqc-lab-sg \
  --protocol tcp --port 5000 --cidr YOUR_IP/32

# Launch instance
aws ec2 run-instances \
  --image-id ami-0c7217cdde317cfec \  # Ubuntu 22.04 LTS us-east-1
  --instance-type t3.small \
  --key-name your-key-pair-name \
  --security-groups pqc-lab-sg \
  --count 1 \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pqc-lab}]'
```

---

## Step 2: SSH and Initial Setup

```bash
# SSH into your instance (replace with your public IP and key path)
ssh -i ~/.ssh/your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Once inside the instance:
# Update system packages
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker   # apply group change without logout

# Verify Docker is running
docker run hello-world
```

---

## Step 3: Deploy the Application

```bash
# Clone your repository
git clone https://github.com/<your-username>/post-quantum-migration.git
cd post-quantum-migration

# Create your .env file
cp .env.example .env
nano .env   # Edit with a strong SECRET_KEY
```

**Edit `.env`:**
```bash
SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
ENV=production
PORT=5000
DATABASE_PATH=/app/results/experiments.db
ALLOWED_BENCHMARK_HOSTS=localhost,127.0.0.1
START_LOOPBACK_SERVER=true
```

```bash
# Build and start the container
docker compose up -d --build

# Verify it's running
docker compose ps
docker compose logs -f   # watch logs (Ctrl+C to stop)

# Test health endpoint
curl http://localhost:5000/health
```

---

## Step 4: Set Up Nginx Reverse Proxy (HTTPS)

```bash
# Install Nginx and Certbot
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Create Nginx config
sudo nano /etc/nginx/sites-available/pqc-lab
```

Paste this Nginx configuration:
```nginx
server {
    listen 80;
    server_name your-domain.com;   # or EC2 public IP

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # allow time for long experiments
    }
}
```

```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/pqc-lab /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Get HTTPS certificate (requires domain name pointing to this IP)
sudo certbot --nginx -d your-domain.com
```

---

## Step 5: Enable Post-Quantum Modes (Optional)

To enable Modes B and C, install oqs-provider on Ubuntu 22.04:

```bash
# Run the automated setup script
bash scripts/install_oqs_provider.sh

# Restart the application
docker compose restart

# Verify PQC available
curl http://localhost:5000/api/system/capabilities | python3 -m json.tool | grep pqc
```

---

## Updating the Deployment

```bash
cd post-quantum-migration

# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build

# Verify
curl http://localhost:5000/health
```

---

## Viewing Logs

```bash
# Application logs
docker compose logs -f pqc-app

# Last 100 lines
docker compose logs --tail=100 pqc-app

# Nginx logs
sudo tail -f /var/log/nginx/access.log
```

---

## Backing Up the Database

The SQLite database is stored in a Docker volume. To back it up:

```bash
# Copy DB from container
docker compose exec pqc-app cat /app/results/experiments.db > backup_$(date +%Y%m%d).db

# Or directly from the volume
docker run --rm -v pqc-migration_pqc-results:/data alpine \
  tar czf - /data > results_backup_$(date +%Y%m%d).tar.gz
```

---

## Teardown — Avoiding Unexpected Charges

> ⚠ **Always stop or terminate your EC2 instance when not in use.** A `t3.small` running 24/7 costs approximately $15-20/month.

```bash
# Stop the application (keeps the instance running)
docker compose down

# Terminate the EC2 instance (PERMANENT — all data lost unless backed up)
aws ec2 terminate-instances --instance-ids <your-instance-id>

# Release Elastic IP if allocated (costs money even when not attached)
aws ec2 release-address --allocation-id <eipalloc-id>

# Delete security group (after instance is terminated)
aws ec2 delete-security-group --group-name pqc-lab-sg
```

**To just stop (not terminate) — cheaper but still costs a little:**
```bash
aws ec2 stop-instances --instance-ids <your-instance-id>
```

---

## Cost Estimate

| Resource | Monthly Cost (approx) |
|----------|----------------------|
| t3.small (running 24/7) | ~$15 |
| t3.small (8h/day) | ~$5 |
| 20 GB gp3 storage | ~$1.60 |
| Data transfer (first 100GB free) | $0 |
| **Total (typical student project)** | **~$7-17** |

Using **AWS Free Tier** (new accounts): t3.micro is free for 750 hours/month for the first year. Note t3.micro has 1GB RAM which may be tight for the build step.

---

## Architecture Note: What TLS is Being Measured?

```
Browser → (HTTPS via Nginx) → Flask application → (TLS 1.3) → Loopback server
                                    ↑ THIS is what we measure ↑

NOT:
Browser → (HTTPS) → Flask application
    ↑ NOT measured — this is user-to-app encryption
```

The measured TLS connection is the internal connection from the Flask benchmark client to the loopback TLS server (or any other configured test server). This is the connection whose cryptographic mode (X25519, ML-KEM, hybrid) is being benchmarked.
