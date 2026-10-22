#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 077
mkdir -p logs
exec "$ROOT/.venv/bin/python" -u "$ROOT/scripts/start-web.py" "$@"
