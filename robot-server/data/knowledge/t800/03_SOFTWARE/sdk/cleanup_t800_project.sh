#!/usr/bin/env bash
set -euo pipefail
cd ~/scripts-ipq/guigoFiles/t800_face_follow_package
STAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="arquivo_antigo_${STAMP}"
mkdir -p "$ARCHIVE"
shopt -s nullglob
for f in app.py.bak_* app.py.broken; do mv -- "$f" "$ARCHIVE/"; done
for f in -- -d -H; do [ -e "$f" ] && mv -- "$f" "$ARCHIVE/" || true; done
rm -rf __pycache__
mkdir -p rosto_dados/backups_modelo
for f in rosto_dados/modelo/modelo_lbph_VALIDADO_*.yml rosto_dados/modelo/labels_VALIDADO_*.json; do
  [ -e "$f" ] && mv -- "$f" rosto_dados/backups_modelo/ || true
done
printf '\nArquivado em: %s\n' "$ARCHIVE"
ls -lah
