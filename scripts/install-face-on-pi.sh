#!/usr/bin/env bash
# Run on the notebook. One interactive SSH authentication; no password saved.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET='arcanjinho@192.168.102.198'
ARKA_SOCKET_DIR=$(mktemp -d)
SSH_ARGS=(-o ControlMaster=auto -o ControlPersist=60 -o "ControlPath=$ARKA_SOCKET_DIR/socket")
cleanup() { ssh "${SSH_ARGS[@]}" -O exit "$TARGET" >/dev/null 2>&1 || true; rm -rf "$ARKA_SOCKET_DIR"; }
trap cleanup EXIT
REMOTE=$(ssh "${SSH_ARGS[@]}" "$TARGET" 'mktemp /tmp/arka-face-setup.XXXXXXXX')
if [[ ! "$REMOTE" =~ ^/tmp/arka-face-setup\.[A-Za-z0-9]+$ ]]; then printf 'Caminho remoto inválido.\n' >&2; exit 1; fi
scp "${SSH_ARGS[@]}" "$ROOT/scripts/setup-pi-face.sh" "$TARGET:$REMOTE"
ssh -t "${SSH_ARGS[@]}" "$TARGET" "bash '$REMOTE'; result=\$?; rm -f '$REMOTE'; exit \$result"
