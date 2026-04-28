#!/usr/bin/env bash
set -euo pipefail

docker compose build flask celery_worker celery_beat
docker compose up -d --no-deps flask celery_worker celery_beat
