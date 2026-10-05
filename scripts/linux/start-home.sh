#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
[[ -f infra/home/.env ]] || python3 scripts/linux/prepare-home.py
docker info >/dev/null
docker compose --env-file infra/home/.env -f infra/home/compose.yaml config --quiet
docker compose --env-file infra/home/.env -f infra/home/compose.yaml up -d --build alice qdrant homepage
docker compose --env-file infra/home/.env -f infra/home/compose.yaml ps
printf '\nAlice: http://127.0.0.1:8330 | Panel: http://127.0.0.1:8331\n'
