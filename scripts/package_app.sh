#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
ARCHIVE="$DIST_DIR/opsmind-app.tar.gz"

mkdir -p "$DIST_DIR"
echo "Creating application archive at $ARCHIVE..."

tar -czf "$ARCHIVE" \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='infra' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='data' \
  --exclude='reports' \
  -C "$ROOT_DIR" \
  src config static templates requirements.txt README.md

echo "Archive created successfully: $(ls -lh "$ARCHIVE" | awk '{print $5}')"
