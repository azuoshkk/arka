# Rosto da Arka no Raspberry Pi

A tela do Raspberry abre **https://192.168.102.144:8444/face**. A página é servida pelo notebook central; o Raspberry só executa Chromium e reproduz o áudio. Nenhum modelo é instalado nele.

## Instalar no Raspberry

No terminal do notebook:

```bash
cd ~/"Área de trabalho"/arcanjinho
./scripts/install-face-on-pi.sh
```

O SSH solicita a senha no terminal. Os scripts não armazenam senhas. O instalador remoto verifica `/face`, baixa a CA local e confere seu SHA-256 antes de confiar nela. Cria backups em `~/.local/share/arka-face/backups/` no Raspberry, instala dependências somente se faltarem (`chromium`, `libnss3-tools`, `curl`), importa a CA na base de certificados do usuário e cria:

- `~/.local/bin/arka-kiosk`
- `~/.local/share/applications/arka-face.desktop`
- `~/.local/share/arka-face/ca.crt`

O perfil do navegador dedicado fica em `~/.config/arka-kiosk`. A instalação não configura inicialização automática do sistema. Abra **Arka — Rosto** no menu ou execute `~/.local/bin/arka-kiosk` na sessão gráfica. O instalador também tenta abrir o kiosk quando encontra a sessão gráfica ativa.

## Somente o rosto

O lançador abre apenas `/face`, sem login, chat, abas extras ou controles visíveis. A página do rosto não exige autenticação; as APIs do chat continuam protegidas. A reinstalação fecha somente o Chromium do perfil dedicado antes de abrir o rosto, evitando reaproveitar a antiga aba de login.

O lançador detecta Wayland e passa `--ozone-platform=wayland` explicitamente. O Raspberry continua sendo apenas cliente visual.

A integração de áudio existente por BroadcastChannel foi preservada, mas depende de um chat na mesma origem e perfil. Com somente o rosto aberto, os olhos ficam ociosos: esta versão não recebe automaticamente a fala de outro dispositivo. Não foi adicionado acesso anônimo às APIs nem um novo canal remoto de áudio.

O argumento de autoplay do kiosk permite reproduzir sem toques. No navegador comum, toque uma vez no rosto para liberar áudio e solicitar fullscreen. Kiosk remove a interface do navegador. O instalador configura confiança na CA; não usa `--ignore-certificate-errors`.

## Comando direto no Raspberry

Com a CA já confiável:

```bash
chromium --ozone-platform=wayland --kiosk --no-first-run --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/arka-kiosk" \
  'https://192.168.102.144:8444/face'
```

Se o executável local se chamar `chromium-browser`, use esse nome. O lançador instalado detecta ambos.

## Validação realizada

- Servidor real: `/`, `/face` e novos assets HTTP 200; login, WebSocket e TTS real funcionando.
- 15 testes de web/face aprovados, incluindo APIs protegidas e streaming WebSocket.
- Navegador: apenas rosto, sem texto; centralização e ausência de scroll em 800×480 e 480×800; redimensionamento atualiza a escala.
- Áudio TTS real do servidor entregue entre duas abas: estado speaking e espectro; término retorna a idle e aos olhos.
- Aba do rosto fechada: handoff retorna para o player do chat.
- Fullscreen nativo/kiosk e Chromium no Raspberry dependem da instalação no dispositivo; não foram confirmados pela ferramenta local. A ferramenta bloqueou o envio da senha SSH antes da autenticação.
