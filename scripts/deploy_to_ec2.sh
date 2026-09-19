#!/usr/bin/env bash
# OpsMind EC2 Deployment Script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

EC2_HOST="${1:-98.94.112.228}"
SSH_USER="${2:-ubuntu}"

echo "=== Packaging OpsMind Application ==="
cd "$ROOT_DIR"
npm run build
chmod +x scripts/package_app.sh
./scripts/package_app.sh

echo "=== Uploading Package to EC2 ($EC2_HOST) ==="
scp -o StrictHostKeyChecking=no "$ROOT_DIR/dist/opsmind-app.tar.gz" "${SSH_USER}@${EC2_HOST}:/tmp/opsmind-app.tar.gz"

echo "=== Deploying and Restarting Services on EC2 ==="
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${EC2_HOST}" "
  sudo tar -xzf /tmp/opsmind-app.tar.gz -C /opt/opsmind
  cd /opt/opsmind
  sudo /opt/opsmind/.venv/bin/pip install --no-cache-dir -r requirements.txt
  sudo systemctl restart opsmind opsmind-worker
  sleep 3
  curl -f http://localhost:8000/healthz
"

echo "=== Deployment Successfully Completed ==="
echo "Dashboard: http://${EC2_HOST}:8000/dashboard"
