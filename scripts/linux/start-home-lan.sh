#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
python3 scripts/linux/configure-home-lan.py "${1:?Falta la IP de Ubuntu en la LAN}"
docker compose --env-file infra/home/.env -f infra/home/compose.yaml --profile dns up -d alice homepage pihole
