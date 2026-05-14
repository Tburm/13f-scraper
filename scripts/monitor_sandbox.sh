#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== container =="
docker ps --filter name=salp-13f-monitor --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

echo
echo "== state =="
if docker ps --filter name=salp-13f-monitor --format '{{.Names}}' | grep -qx salp-13f-monitor; then
  docker exec salp-13f-monitor uv run python -m json.tool /app/state/salp_13f_state.json 2>/dev/null || echo "state file not found yet"
else
  echo "container is not running"
fi

echo
echo "== recent logs =="
docker logs --tail "${TAIL:-80}" salp-13f-monitor 2>&1 || true
