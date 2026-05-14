#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

docker build -t salp-13f-monitor:latest .
docker rm -f salp-13f-monitor >/dev/null 2>&1 || true
docker volume create salp-13f-state >/dev/null

docker run -d \
  --name salp-13f-monitor \
  --restart unless-stopped \
  -e POLL_SECONDS="${POLL_SECONDS:-300}" \
  -e DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:?DISCORD_WEBHOOK_URL is required}" \
  -e SEC_USER_AGENT="${SEC_USER_AGENT:-salp-13f-monitor/0.1 contact@example.com}" \
  -e LOG_LEVEL="${LOG_LEVEL:-INFO}" \
  -v salp-13f-state:/app/state \
  salp-13f-monitor:latest

docker logs --tail 50 salp-13f-monitor
