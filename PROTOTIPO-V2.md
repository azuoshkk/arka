# Arka — lista de compras do protótipo V2

Planejamento de 27/10/2026. Raspberry = rosto, câmera, captura de voz e reprodução; notebook atual = modelos, Router, RAG e visão. Não é necessário comprar outro computador/GPU para montar este corpo. Quantidades para uma unidade. Sem preços: cotar no Brasil com frete e impostos.

| Qtde. | Item recomendado | Critério de compra / uso |
|---|---|---|
| 1 | Raspberry Pi 5, 4 GB | Recomendação para cliente Chromium e periféricos. 8 GB é opcional para margem; não transfere os modelos do notebook. |
| 1 | Fonte oficial Raspberry Pi USB-C 27 W | Alimentação adequada ao Pi 5 e periféricos; não reutilizar automaticamente a fonte do Pi 4. |
| 1 | Raspberry Pi Active Cooler | Refrigeração ativa, com entradas e saídas de ar livres. |
| 1 | Corpo/case ventilado compatível com Pi 5 e Active Cooler | Conferir folgas da tela, conectores e dissipador. Evitar gabinete fechado sem fluxo de ar. |
| 1 | Raspberry Pi Touch Display 2 de 7 polegadas | Tela oficial com toque; montar na orientação desejada e configurar rotação de imagem/toque em conjunto. Conferir kit de cabos DSI adequado ao Pi 5 e alimentação GPIO. |
| 1 | microSD 64 GB, A2, de fornecedor confiável | Sistema e cliente. Modelos/documentos permanecem no notebook. Leitor USB de microSD para instalação, se não tiver. |
| 1 | reSpeaker XVF3800 USB Mic Array | Microfone USB com processamento de áudio/AEC. Escolher versão USB; não precisa do ESP32 para este projeto. |
| 1 | Cabo USB de dados compatível com o reSpeaker | USB-A no Raspberry e conector correspondente na placa; verificar cabo incluso. Cabo somente de carga não serve. |
| 1 par | Creative Pebble V2 | Caixas ativas: áudio pelo P2 de 3,5 mm do reSpeaker; USB é alimentação, não entrada de áudio. |
| 1 | Fonte USB 5 V / 2 A para as caixas | Alimentação separada do Pi. Conferir conector/adaptador das caixas. |
| 1 | Webcam Logitech C920 existente | Reutilizar: já testada no projeto. Prender com suporte firme; começar em 640×480 e 10 fps. Não comprar outra webcam antes de testar iluminação e posicionamento. |
| 1–2 | Cabos Ethernet Cat5e/Cat6 | Preferir conexão cabeada entre Pi, roteador/switch e notebook. Adaptador USB–Ethernet só se o notebook não tiver porta. |
| 1 kit | Suportes, espaçadores e parafusos apropriados | Fixação da tela/câmera/Pi, passa-cabos, abraçadeiras e alívio de tração. Selecionar medidas pelos desenhos mecânicos. |
| Conforme necessidade | Hub USB alimentado e switch Gigabit | Opcionais: comprar apenas se faltarem portas ou houver limitação elétrica. |
| Reutilizar | Teclado, mouse, notebook e rede existentes | Para configuração/manutenção. Micro-HDMI→HDMI é opcional para diagnóstico em monitor externo. |

## Ligações

- Webcam → USB do Raspberry.
- Microfone reSpeaker → USB do Raspberry.
- Saída P2 do reSpeaker → entrada P2 das Pebble; fonte USB separada → alimentação das caixas.
- Touch Display → DSI + alimentação conforme manual oficial.
- Raspberry → Ethernet → rede do notebook.
- Notebook continua executando IA e RAG; não expor serviços internos.

Manter reprodução e captura no mesmo reSpeaker favorece a referência de cancelamento de eco. Confirmar firmware/modo USB duplex e selecionar explicitamente seus dispositivos de entrada e saída no sistema. AEC não substitui teste acústico: separar microfone de ventoinha, vibração e saída das caixas. Recomendação baseada nas interfaces documentadas; este conjunto específico ainda não foi testado fisicamente por nós.

Para reduzir custo, reutilizar primeiro Pi 4, C920 e tela atuais, corrigindo refrigeração/alimentação. As maiores prioridades práticas são resfriamento, áudio cabeado com AEC e rede estável. Trocar para Pi 5 não acelera a análise de IA executada no notebook. Echo Bluetooth pode continuar como solução temporária, mas adiciona pareamento e latência.

## Congelamento investigado

Em 27/10, o endpoint JPEG avançou nas sequências 4869, 4878, 4883 e 4888, com hashes diferentes, enquanto o monitor era relatado como congelado. Evidência de captura/transporte até o notebook ativos; problema localizado após essa etapa, na apresentação/conexão de vídeo. Não prova uma única causa para todos os congelamentos anteriores.

O monitor agora solicita quadros independentes, com timeout de 2 s, tentativas automáticas, liberação de URLs temporárias e indicação de falta de quadros. Telemetria e detecção continuam independentes. O endpoint MJPEG permanece disponível, sem mudanças na API existente. Recarregar monitores já abertos para obter o JavaScript novo.

O Pi também já apresentou limite térmico ativo em diagnóstico anterior. A última leitura antes desta correção foi cerca de 78 °C, sem sinal ativo de throttling naquele instante. Refrigeração continua necessária; ainda falta teste prolongado do conjunto.

## Referências oficiais

- Raspberry Pi 5, alimentação e refrigeração: https://www.raspberrypi.com/products/raspberry-pi-5/
- Active Cooler: https://www.raspberrypi.com/products/active-cooler/
- Tela e instalação: https://www.raspberrypi.com/documentation/accessories/touch-display-2.html
- reSpeaker USB e conexões de áudio: https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/
- Pebble V2 — alimentação 5 V e entrada analógica: https://support.creative.com/kb/ShowArticle.aspx?sid=200196
- Pebble V2 — USB não transporta áudio: https://support.creative.com/kb/ShowArticle.aspx?sid=200273
