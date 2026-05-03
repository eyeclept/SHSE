#!/usr/bin/env bash
# reset.sh — wipe all persistent state and return the SHSE stack to a clean install.
# Deletes named Docker volumes, bind-mount data directories, re-pulls images,
# brings the stack back up, and re-applies all database migrations.
set -euo pipefail

echo "WARNING: This will permanently delete all persistent data and restart the stack."
echo "  MariaDB, OpenSearch, Nutch, and Redis data will be DELETED."
echo ""
read -r -p "Type 'y' to continue, anything else to abort: " answer
if [ "$answer" != "y" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "--- Stopping containers ---"
docker compose down

echo ""
echo "--- Removing named volumes (if they exist) ---"
for vol in opensearch_data mariadb_data shse_opensearch_data shse_mariadb_data; do
    if docker volume ls -q | grep -qx "$vol"; then
        echo "  removing volume: $vol"
        docker volume rm "$vol"
    fi
done

echo ""
echo "--- Removing bind-mount data directories ---"
# Container users (OpenSearch UID 1000, MariaDB UID 999) own the files on the
# host, so host rm -rf is permission-denied. Use a root busybox container to
# delete the contents, then remove the now-empty dirs from the host.
for dir in ./data/opensearch ./data/mariadb ./data/nutch ./data/redis; do
    if [ -d "$dir" ]; then
        echo "  deleting $dir"
        abs="$(cd "$(dirname "$dir")" && pwd)/$(basename "$dir")"
        docker run --rm -v "${abs}:/mnt/target" busybox \
            sh -c "rm -rf /mnt/target/* /mnt/target/.[!.]*" 2>/dev/null || true
        rm -rf "$dir"
    fi
done

echo ""
echo "--- Pulling latest images ---"
docker compose pull

echo ""
echo "--- Starting stack ---"
docker compose up -d

echo ""
echo "--- Waiting for Flask to become healthy (up to 180s) ---"
echo "    (Flask runs migrations automatically before starting — this may take a moment)"
timeout 180 bash -c \
    'until docker compose ps flask 2>/dev/null | grep -q "(healthy)"; do sleep 3; done' \
    || { echo "WARNING: Flask did not reach healthy within 180s; check logs."; }

echo ""
echo "--- Done. Stack is up with a clean state. ---"
docker compose ps
