#!/usr/bin/env bash
# OpsMind EC2 deployment script.
#
# Usage: scripts/deploy_to_ec2.sh <host> [ssh-user] [app-port]
#
# The target host is required rather than defaulted, so no environment's
# address is committed to this repository.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

EC2_HOST="${1:-${OPSMIND_DEPLOY_HOST:-}}"
SSH_USER="${2:-${OPSMIND_SSH_USER:-ubuntu}}"
APP_PORT="${3:-${OPSMIND_APP_PORT:-8000}}"
REMOTE_DIR="${OPSMIND_REMOTE_DIR:-/opt/opsmind}"

if [ -z "$EC2_HOST" ]; then
  echo "error: target host is required." >&2
  echo "usage: scripts/deploy_to_ec2.sh <host> [ssh-user] [app-port]" >&2
  echo "       or set OPSMIND_DEPLOY_HOST" >&2
  exit 1
fi

echo "=== Packaging OpsMind application ==="
cd "$ROOT_DIR"
npm run build
chmod +x scripts/package_app.sh
./scripts/package_app.sh

echo "=== Uploading package to $EC2_HOST ==="
scp -o StrictHostKeyChecking=no \
  "$ROOT_DIR/dist/opsmind-app.tar.gz" \
  "${SSH_USER}@${EC2_HOST}:/tmp/opsmind-app.tar.gz"

echo "=== Deploying and restarting services ==="
# Single-quoted body so expansions run on the remote host, with the few
# values we do want substituted passed in as positional arguments.
ssh -o StrictHostKeyChecking=no "${SSH_USER}@${EC2_HOST}" \
  'bash -s' -- "$REMOTE_DIR" "$APP_PORT" <<'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
APP_PORT="$2"

sudo tar -xzf /tmp/opsmind-app.tar.gz -C "$REMOTE_DIR"
sudo "$REMOTE_DIR/.venv/bin/pip" install --no-cache-dir -r "$REMOTE_DIR/requirements.txt"
sudo systemctl restart opsmind opsmind-worker

for _ in $(seq 1 15); do
  if curl -sf "http://127.0.0.1:${APP_PORT}/healthz" > /dev/null; then
    echo "service healthy"
    exit 0
  fi
  sleep 2
done
echo "error: service did not become healthy" >&2
exit 1
REMOTE

echo "=== Deployment completed ==="
echo "Dashboard: http://${EC2_HOST}:${APP_PORT}/dashboard"
