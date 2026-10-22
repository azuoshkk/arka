#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -u "$ROOT/scripts/start-demo.py"
