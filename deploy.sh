#!/usr/bin/env bash
# Deploy/update the public demo: ./deploy.sh [extra compose args]
set -euo pipefail
cd "$(dirname "$0")"
exec docker compose -p stacklight-demo --env-file .env --env-file deploy.env \
  -f docker-compose.yml -f docker-compose.override.yml up -d --build --wait "$@"
