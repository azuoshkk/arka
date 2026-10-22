#!/usr/bin/env bash
# Executed ON the Raspberry. Contains no account/password/token.
set -euo pipefail
umask 077
ARKA_BASE='https://192.168.102.144:8444'
ARKA_CA_URL='http://192.168.102.144:8082/arcanjo-local-ca.crt'
ARKA_CA_SHA='658a0bf21e136a96e3fff6381a864c26a7207bbfff1582cb37c59d46bd03d8f3'
ARKA_DIR="$HOME/.local/share/arka-face"
ARKA_BACKUP="$ARKA_DIR/backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ARKA_DIR" "$ARKA_BACKUP" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/state/arka-face"
missing=()
command -v curl >/dev/null || missing+=(curl)
command -v certutil >/dev/null || missing+=(libnss3-tools)
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then missing+=(chromium); fi
if ((${#missing[@]})); then
  printf 'Instalando dependências: %s\n' "${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
fi
for item in "$ARKA_DIR/ca.crt" "$HOME/.local/bin/arka-kiosk" "$HOME/.local/share/applications/arka-face.desktop"; do
  if [[ -f "$item" ]]; then cp -p "$item" "$ARKA_BACKUP/$(basename "$item")"; fi
done
ARKA_TMP=$(mktemp -d)
trap 'rm -rf "$ARKA_TMP"' EXIT
curl --fail --silent --show-error --connect-timeout 8 "$ARKA_CA_URL" -o "$ARKA_TMP/ca.crt"
printf '%s  %s\n' "$ARKA_CA_SHA" "$ARKA_TMP/ca.crt" | sha256sum -c -
curl --fail --silent --show-error --cacert "$ARKA_TMP/ca.crt" "$ARKA_BASE/face" -o "$ARKA_TMP/face.html"
if ! grep -q 'face-only' "$ARKA_TMP/face.html"; then printf 'O servidor ainda não carregou /face.\n'; exit 1; fi
cp "$ARKA_TMP/ca.crt" "$ARKA_DIR/ca.crt"
# Back up the user trust database before importing the verified local CA.
if [[ -d "$HOME/.pki/nssdb" ]]; then cp -a "$HOME/.pki/nssdb" "$ARKA_BACKUP/nssdb"; fi
mkdir -p "$HOME/.pki/nssdb"
if [[ ! -f "$HOME/.pki/nssdb/cert9.db" ]]; then certutil -N --empty-password -d "sql:$HOME/.pki/nssdb"; fi
if certutil -L -d "sql:$HOME/.pki/nssdb" -n 'Arka LAN local CA' >/dev/null 2>&1; then certutil -D -d "sql:$HOME/.pki/nssdb" -n 'Arka LAN local CA'; fi
certutil -A -d "sql:$HOME/.pki/nssdb" -n 'Arka LAN local CA' -t 'C,,' -i "$ARKA_DIR/ca.crt"
cat > "$HOME/.local/bin/arka-kiosk" <<'KIOSK'
#!/usr/bin/env bash
set -euo pipefail
ARKA_CHROMIUM=$(command -v chromium || command -v chromium-browser)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
if [[ -z "${WAYLAND_DISPLAY:-}" && -S "$XDG_RUNTIME_DIR/wayland-0" ]]; then export WAYLAND_DISPLAY=wayland-0; fi
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  export XDG_SESSION_TYPE=wayland
  ARKA_PLATFORM=wayland
else
  export DISPLAY="${DISPLAY:-:0}"
  ARKA_PLATFORM=x11
fi
exec "$ARKA_CHROMIUM" --ozone-platform="$ARKA_PLATFORM" --kiosk --no-first-run --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/arka-kiosk" \
  'https://192.168.102.144:8444/face'
KIOSK
chmod 700 "$HOME/.local/bin/arka-kiosk"
cat > "$HOME/.local/share/applications/arka-face.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Arka — Rosto
Comment=Somente o rosto da Arka em tela cheia
Exec=$HOME/.local/bin/arka-kiosk
Terminal=false
Categories=Utility;
DESKTOP
printf 'Instalado no Raspberry. Backups: %s\n' "$ARKA_BACKUP"
printf 'Servidor HTTPS e /face: OK. Certificado verificado e importado.\n'
"$(command -v chromium || command -v chromium-browser)" --version
if [[ -S /tmp/.X11-unix/X0 || -S "/run/user/$(id -u)/wayland-0" ]]; then
  # Close only the dedicated kiosk browser so its old chat tab is not reused.
  for ARKA_PROC in /proc/[0-9]*/cmdline; do
    [[ -r "$ARKA_PROC" && -O "$ARKA_PROC" ]] || continue
    ARKA_ARGS=()
    mapfile -d '' -t ARKA_ARGS < "$ARKA_PROC" 2>/dev/null || continue
    ARKA_MATCH=false
    ARKA_CHILD=false
    for ARKA_ARG in "${ARKA_ARGS[@]}"; do
      [[ "$ARKA_ARG" == "--user-data-dir=$HOME/.config/arka-kiosk" ]] && ARKA_MATCH=true
      [[ "$ARKA_ARG" == --type=* ]] && ARKA_CHILD=true
    done
    if $ARKA_MATCH && ! $ARKA_CHILD; then
      ARKA_PID=${ARKA_PROC#/proc/}; ARKA_PID=${ARKA_PID%/cmdline}
      kill -TERM "$ARKA_PID" 2>/dev/null || true
      for ARKA_WAIT in {1..50}; do
        kill -0 "$ARKA_PID" 2>/dev/null || break
        sleep 0.1
      done
      if kill -0 "$ARKA_PID" 2>/dev/null; then
        printf 'Feche a janela antiga Arka no Raspberry e execute o instalador novamente.\n' >&2
        exit 1
      fi
    fi
  done
  nohup setsid "$HOME/.local/bin/arka-kiosk" > "$HOME/.local/state/arka-face/kiosk.log" 2>&1 < /dev/null &
  sleep 3
  if pgrep -u "$(id -u)" -f -- "--user-data-dir=$HOME/.config/arka-kiosk" >/dev/null; then
    printf 'Processo Chromium kiosk ativo. Confirme somente os olhos na tela, sem login ou chat.\n'
  else
    printf 'O Chromium não permaneceu ativo. Diagnóstico:\n' >&2
    tail -n 20 "$HOME/.local/state/arka-face/kiosk.log" >&2
    exit 1
  fi
else
  printf 'Abra Arka — Rosto no menu da sessão gráfica, ou execute ~/.local/bin/arka-kiosk no Raspberry.\n'
fi
