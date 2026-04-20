#!/bin/bash
# SHSE — Initialisation Script
# Modify this script as the project grows.

set -euo pipefail

EXPECTED_SERVICES=(opensearch mariadb redis nutch flask celery_worker celery_beat nginx)
FAILED=0

echo "=== SHSE init check ==="

for svc in "${EXPECTED_SERVICES[@]}"; do
    status=$(docker inspect --format '{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$svc" 2>/dev/null || echo "missing")

    if [[ "$status" != "running" ]]; then
        echo "FAIL  $svc — container not running (status: $status)"
        FAILED=1
    elif [[ "$health" == "unhealthy" ]]; then
        echo "FAIL  $svc — unhealthy"
        FAILED=1
    elif [[ "$health" == "starting" ]]; then
        echo "WARN  $svc — still starting"
        FAILED=1
    else
        echo "OK    $svc"
    fi
done

echo "======================="

if [[ $FAILED -ne 0 ]]; then
    echo "One or more services failed. Run: docker compose ps"
    exit 1
fi

echo "All services up."
exit 0
