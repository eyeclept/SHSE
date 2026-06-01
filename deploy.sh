#!/usr/bin/env bash
# deploy.sh — sync local codebase to the app VM and rebuild containers.
#
# Usage:
#   ./deploy.sh            # sync + rebuild + restart (default)
#   ./deploy.sh --sync     # rsync only, no rebuild
#   ./deploy.sh --rebuild  # rebuild + restart only, no rsync
#
# The .env file on the app VM is never overwritten.

set -euo pipefail

APP_VM="eyeclept@172.27.72.56"
REMOTE_DIR="~/shse"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)/"
COMPOSE_FILE="docker-compose.app.yml"
SERVICES="flask celery_worker celery_beat"

DO_SYNC=true
DO_REBUILD=true

for arg in "$@"; do
  case "$arg" in
    --sync)    DO_REBUILD=false ;;
    --rebuild) DO_SYNC=false ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [--sync|--rebuild]"
      exit 1
      ;;
  esac
done

if $DO_SYNC; then
  echo "==> Syncing codebase to $APP_VM:$REMOTE_DIR"
  rsync -avz --delete \
    --exclude='.env' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='logs/' \
    --exclude='nutch_data/' \
    --exclude='wikipedia_en_100_nopic_2026-04.zim' \
    --exclude='data/' \
    "$LOCAL_DIR" \
    "$APP_VM:$REMOTE_DIR"
  echo "==> Sync complete."
fi

if $DO_REBUILD; then
  echo "==> Rebuilding images on $APP_VM"
  # shellcheck disable=SC2029
  ssh "$APP_VM" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE build $SERVICES"

  echo "==> Restarting containers"
  # shellcheck disable=SC2029
  ssh "$APP_VM" "cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE up -d --no-deps $SERVICES"

  echo "==> Verifying container status"
  # shellcheck disable=SC2029
  ssh "$APP_VM" "docker compose -f $REMOTE_DIR/$COMPOSE_FILE ps"
fi

echo "==> Done."
