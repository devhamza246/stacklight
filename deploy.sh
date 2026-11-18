#!/usr/bin/env bash
# Deploy/update the demo as its own compose project: ./deploy.sh [extra `up` args]
#
# Reads secrets from .env. Two optional, git-ignored files layer on top when present:
#   deploy.env                   non-secret production overrides (port, spend cap, rate limit, TRUST_PROXY_HEADERS)
#   docker-compose.override.yml  extra networks, e.g. attaching the app to a reverse proxy / tunnel network
# See docs/deploy.md. Without them this is just `docker compose up` under the project name stacklight-demo.
set -euo pipefail
cd "$(dirname "$0")"

args=(-p stacklight-demo)
[[ -f .env ]] && args+=(--env-file .env)
[[ -f deploy.env ]] && args+=(--env-file deploy.env)
args+=(-f docker-compose.yml)
[[ -f docker-compose.override.yml ]] && args+=(-f docker-compose.override.yml)

exec docker compose "${args[@]}" up -d --build --wait "$@"
