#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/.venv/bin/python" "$ROOT/scripts/stop-web.py"
exec "$ROOT/scripts/start-web.sh" "$@"
