#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/robot-server"
status=0
for test in test_router.py test_voice_bridge.py test_voice_sanity.py test_credentials_rag.py test_physical_specs_guard.py; do
  "$ROOT/.venv/bin/python" "$test" > "$ROOT/logs/${test%.py}-validation.log" 2>&1
  code=$?
  echo "$test: exit $code"
  if [ "$code" -ne 0 ]; then status=1; fi
done
"$ROOT/.venv/bin/python" test_rag.py --tag critical > "$ROOT/logs/rag-critical-validation.log" 2>&1
code=$?
echo "RAG critical: exit $code"
if [ "$code" -ne 0 ]; then status=1; fi
exit "$status"
