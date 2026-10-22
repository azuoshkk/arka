# headFollow — pescoço do EngineAI T800

Projeto criado em 22/09/2026. Python + painel web, sem instalação de pacotes para a simulação.

**Resultado atualizado:** controle físico ativado e testado em 22/09/2026. Para alvos de 2°, a telemetria mediu yaw 1,86° e pitch 2,05°; os dois eixos retornaram ao centro. O controlador antigo foi colocado em espera, com backup e reversão, e o serviço `headfollow.service` está ativo no Orin.

## Abrir agora

Durante a sessão de desenvolvimento foram iniciados:

- http://127.0.0.1:8765 — simulação local; pode experimentar os comandos.
- http://127.0.0.1:8766 — **controle real do pescoço**, com comandos habilitados.

O controle no Orin é um serviço de usuário, habilitado para iniciar na sessão do usuário Ubuntu. Iniciar o serviço não movimenta o robô. O túnel SSH e a simulação são processos temporários. Para reconectar depois, use os comandos abaixo. Se a porta já estiver ocupada pelo headFollow, use o painel existente.

## Simular

```bash
cd "$HOME/Área de trabalho/headFollow"
bash iniciar_simulacao.sh
```

Abra http://127.0.0.1:8765. Prepare os ângulos de inclinação e giro; mantenha o botão verde pressionado durante o movimento. Também é possível focar o botão com Tab e segurar Espaço. Soltar, trocar de janela ou pressionar Esc libera a sessão. “Preparar centro” apenas ajusta os controles para zero; o movimento só começa ao segurar o botão.

O desenho é uma representação dos dois eixos, não uma simulação de forças ou colisões. Não inclui rastreamento automático de rostos nesta versão.

## Conectar ao robô

```bash
cd "$HOME/Área de trabalho/headFollow"
bash abrir_robo.sh
```

O script conecta ao serviço já instalado no Orin e abre um túnel SSH em http://127.0.0.1:8766. Ele pede a senha pelo próprio SSH, sem salvá-la. Não cria um segundo controlador nem envia transições de estado corporal.

Conexão configurada: `ubuntu@192.168.102.133`. Para outra rede, use `HEADFOLLOW_HOST=novo_ip bash abrir_robo.sh`.

## Usar o controle físico

```bash
bash abrir_robo.sh
```

O serviço está configurado com `--enable-motion`; **não move o robô na inicialização**. O botão só funciona quando:

1. A aplicação recebe as 25 juntas, com telemetria atualizada em até 0,5 s.
2. O robô confirma `lower_body_balance`, com estado atualizado em até 1,5 s. Se estiver em `idle`, use o procedimento oficial do fabricante para preparar o robô. O programa não envia transições de postura.
3. Não existe outro publicador em `/motion/joint_override_command`. A ponte reiniciava automaticamente o controlador antigo; agora sua entrada reconhece `controle_exclusivo.json` e mantém somente um serviço de status na porta 5055, sem publicador ROS. Os comandos do painel antigo recebem HTTP 423; use o headFollow.
4. A posição medida está dentro do envelope inicial: pitch ±20° e yaw ±45°. Não amplie os limites para contornar esse bloqueio sem validar a postura inicial.
5. Existe receptor para o comando de juntas.

O teste físico de 2° nos dois eixos passou. Os ganhos Kp=100 e Kd=3 foram copiados do controlador existente; esse teste não substitui uma validação mecânica de toda a amplitude e carga. Use a parada física se houver comportamento inesperado.

Soltar o botão envia `weight=0` em cinco mensagens e devolve a autoridade ao controlador principal, cuja referência pode ser diferente. **Isso não garante imobilidade nem substitui a parada física.** O watchdog da aplicação funciona enquanto o processo estiver vivo; encerramento forçado, falha do Orin ou perda do DDS podem impedir a entrega dessas mensagens. Não foi confirmado um watchdog de override no firmware.

## Como funciona

Navegador → HTTP local → túnel SSH → Python no Orin → ROS 2 → controlador de movimento.

- Comando: `/motion/joint_override_command`, `interface_protocol/msg/JointOverrideCommand`.
- Apenas índices `[23, 24]`, na ordem **pitch, yaw**; radianos na mensagem e graus no painel.
- Telemetria: `/hardware/joint_state` e `/motion/motion_state`, QoS BEST_EFFORT.
- ROS_DOMAIN_ID=69, CycloneDDS em `eth1`, usando o XML instalado pelo fabricante.
- Interpolação quíntica a 100 Hz, velocidade máxima da referência de 8°/s; não aceita novo alvo no meio de uma trajetória.
- Autorização expira em 0,7 s sem presença do navegador. Recusa NaN, infinito, valores fora dos limites e comandos de outra sessão.
- O modo real nunca se converte silenciosamente em simulação se faltar ROS.
- API aceita mudanças apenas com token da sessão, e o servidor escuta somente em `127.0.0.1`.

## Arquivos e evidências

- [RELATORIO.md](RELATORIO.md): descobertas, fontes e pendências.
- `app.py`, `core.py`, `ros_backend.py`, `web/`: aplicação.
- `docs/originais/`: 15 documentos locais copiados, sem modificar as fontes.
- `docs/textos/`: conteúdo extraído para pesquisa.
- `docs/sdk_local/`: URDF, configurações e mensagens do SDK local.
- `docs/engineai_oficial/`: exemplo público e configuração da EngineAI, licença e árvore do repositório.
- `evidencias/`: diagnósticos SSH, configuração DDS, cópia do controlador anterior, status real, capturas do painel e testes.

```bash
python3 -m unittest discover -s tests -v
```

Os 18 testes cobrem núcleo de controle e API HTTP. O teste adicional `tests/browser_check.py` requer Firefox com Marionette na porta 2828, simulação na 8765 e painel real na 8766; valida movimento apenas no simulador e inspeciona o estado do botão real sem acioná-lo. Não há dependências Python externas para esses testes.

## Serviço e reversão

No Orin, `systemctl --user status headfollow.service` mostra o serviço. A origem está em `/home/ubuntu/headFollow`. O programa legado teve somente sua entrada modificada; as funções de vídeo, áudio e os serviços do fabricante não foram reiniciados por essa mudança.

Há um backup anterior à transferência, registrado em `controle_exclusivo.json` no Orin e em `evidencias/instalacao_exclusividade.txt` neste computador. Para devolver o pescoço ao programa antigo, execute no Orin `python3 /home/ubuntu/headFollow/restaurar_legado.py --execute`. A reversão verifica os hashes antes de restaurar, para não sobrescrever alterações posteriores.
