#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
tty_args=()
if [[ ! -t 0 || ! -t 1 ]]; then tty_args=(-T); fi
exec docker compose --env-file infra/home/.env -f infra/home/compose.yaml exec "${tty_args[@]}" alice alice "$@"
