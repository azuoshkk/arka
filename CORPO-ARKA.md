# Corpo e painel da Arka

## Arquitetura

Raspberry Pi 4 + C920: Chromium kiosk, câmera/microfone, reprodução na Echo Dot por Bluetooth. A voz foi ouvida e confirmada pelo usuário. O notebook executa os modelos; nenhum modelo vai para o Pi.

`arka-body.service` é um serviço de usuário no Pi, com `scripts/pi-body.py` instalado em `~/.local/share/arka-body/`. O adaptador escuta somente `127.0.0.1:8765`. Seu diretório `web/` recebe `face.html`, `monitor.html` e os assets usados. O rosto abre `http://127.0.0.1:8765/face`, sem login visível. O adaptador guarda a credencial viewer em `~/.config/arka-body/client.json` (permissão 600), com campos `url`, `ca`, `username`, `password`. Criar a conta pelo mecanismo existente de acesso; não versionar a configuração.

Os endpoints de chat, transcrição, TTS e visão continuam autenticados no notebook. O adaptador verifica Host/Origin, limites de tamanho e certificado HTTPS. Não publicar a porta 8765 nem encaminhá-la por túnel público.

## Uso

Diga **“Arka” + pergunta**, ou “Arka” sozinho e a pergunta em até 8 segundos. A variante escrita “Arca” pelo Whisper também ativa. Áudio ambiente ainda é transcrito localmente para detectar a palavra; o chat só recebe comandos após a ativação. A captura para durante processamento/TTS. Supressão de ruído e eco do Chromium, filtros de voz e controle automático de ganho desativado.

“Arka, o que é isso?”, “Arka, analise a cena” e “Arka, o que você está vendo?” disparam visão. Para identificar um objeto específico, coloque-o na mira central. Se houver uma detecção não humana com confiança suficiente cobrindo a mira, a análise usa um recorte; caso contrário usa a cena completa e deve reconhecer ambiguidades.

A análise espera um novo quadro decodificado e registra horário/hash, sem gravar a imagem. A nova observação substitui detalhes visuais anteriores no prompt. Pedidos durante outra análise ficam pendentes; não são marcados como concluídos prematuramente.

## Painel no notebook

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 -i CAMINHO_DA_CHAVE USUARIO@IP_DO_PI
# Abra http://127.0.0.1:8765/monitor
# Em outro terminal, com o ambiente de IA configurado:
.venv/bin/python scripts/detect-body.py
```

`scripts/show-body-monitor.py` abre um visualizador GTK/WebKit no monitor externo de posição X=0; requer pacotes GTK3/WebKit2 4.1 do sistema. Prefira uma única janela de monitoramento. O painel mostra vídeo MJPEG, estado, transcrição, resposta, caixas e análise sob pedido. Vídeo e caixas são estimativas próximas do tempo real, não rastreamento com IDs persistentes.

## Otimizações e limites medidos

- HTTP persistente para requisições curtas; streams fecham explicitamente. Fila de conexões ampliada.
- Vídeo alvo 8 FPS; cai para 5 FPS quando o Pi atinge 78 °C. Câmera captura até 10 FPS. Telemetria a cada 500 ms.
- Espectro exclusivo do corpo limitado a 30 FPS e menos traços, preservando o espectro do site principal.
- Reconexão periódica do stream no painel; timeout de solicitação para não ficar indefinidamente em “pensando”.
- Pi medido a 83,2 °C, com limite térmico ativo e histórico de eventos de alimentação/temperatura. Melhorar ventilação/dissipação e conferir a fonte; software não substitui refrigeração.
- A visão pode errar objetos, relações e posições. As caixas não reconhecem identidade de pessoas.

Diagnóstico: `vcgencmd measure_temp`, `vcgencmd get_throttled`, `wpctl status`, `systemctl --user status arka-body.service`.

Backups ficam em `backups/` no notebook e `~/.local/share/arka-body/backups/` no Pi. Não são publicados.
