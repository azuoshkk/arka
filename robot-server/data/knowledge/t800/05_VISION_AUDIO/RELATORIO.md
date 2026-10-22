# Descobertas — T800 / headFollow

## Atualização: controle físico concluído

Após o usuário solicitar a ativação, o controle foi transferido ao headFollow. A ponte tinha um watchdog que reiniciava `neck_controller.py`; apenas encerrar esse processo não resolveria a disputa. Foi salvo um novo backup e adicionada uma condição à entrada do legado: com `controle_exclusivo.json` presente, ele executa `standby_legacy.py`, que preserva a porta de status 5055, recusa comandos com HTTP 423 e não inicializa um nó ROS. A ponte e suas outras funções continuaram rodando.

Foi instalado e habilitado o serviço de usuário `headfollow.service`, porta 8766, com comandos habilitados e inicialização desarmada. O estado publicado confirmou `lower_body_balance`, telemetria recente e nenhuma concorrência.

**Teste físico executado e aprovado:** alvo yaw 2° → medido 1,8639°; alvo pitch 2° → medido 2,0458°. Houve retorno ao centro entre os eixos e ao final. O maior erro final registrado no teste foi 0,2274°. Isso valida pequenos movimentos dos dois motores por esta aplicação; não valida toda a amplitude/carga nem o comportamento em falha de hardware. Evidências: `resultado_teste_fisico.txt` e `teste_fisico.json`.

O teste foi executado pela API do headFollow no Orin; o controlador entrou e saiu de autorização e ficou desarmado, disponível para o painel. O teste não enviou transições de modo corporal.

O painel real agora é http://127.0.0.1:8766. O comando `bash abrir_robo.sh` reconecta ao serviço. A reversão opcional está em `restaurar_legado.py`. As seções abaixo preservam a investigação inicial; as pendências de concorrência e primeiro teste físico foram resolvidas nesta atualização.

Data local: 22/09/2026, America/Bahia. O relógio do Orin mostrou 23/09/2026 durante parte da coleta; os horários dos arquivos remotos não devem ser comparados diretamente com o relógio deste computador.

## Equipamento e comunicação confirmados

O IP informado inicialmente, `192.18.102.133`, não respondeu. Após correção pelo usuário, o SSH funcionou em `ubuntu@192.168.102.133`. A senha foi usada apenas na autenticação e não foi salva nos arquivos do projeto.

O equipamento acessado é o Orin: Linux aarch64, kernel `5.15.148-6-engine-tegra`, ROS 2 Humble. Interfaces observadas:

| Interface | Endereço | Função observada |
|---|---|---|
| wlP1p1s0 | 192.168.102.133 | Acesso SSH via Wi-Fi |
| eth1 | 192.168.0.162 | Rede DDS interna; peer 192.168.0.163 |
| eno1 | 192.168.100.162 | Rede dos sensores |

Mensagens compiladas em `/home/ubuntu/source/engineai_workspace/install/setup.bash`. A configuração necessária para receber os dados é:

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/source/engineai_workspace/install/setup.bash
export ROS_DOMAIN_ID=69
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///app/applications/install/bringup/cyclonedds.xml
```

Sem escolher esse XML, a descoberta dos tópicos funcionava, mas os comandos de leitura não recebiam amostras durante o timeout. Com o XML em `eth1` e QoS BEST_EFFORT, as amostras chegaram. Evidências: `telemetria_dds_eth1.txt`, `original_cyclonedds.xml`, `rede_e_status.txt`.

## Juntas e limites

O modelo local e o controlador encontrado no Orin identificam:

| Eixo | Nome do modelo | Índice de comando | Limite do URDF | Envelope do headFollow |
|---|---|---:|---:|---:|
| Inclinação | J23_HEAD_PITCH | 23 | ±0,523 rad, cerca de ±29,97° | ±20° |
| Giro | J24_HEAD_YAW | 24 | ±1,222 rad, cerca de ±70,02° | ±45° |

Foram recebidas **25 posições** no hardware. O código recusa outra quantidade; não se deve reutilizar esse mapeamento no T800 Pro/Max sem investigação. A lista de observações da política de aprendizado no SDK usa outra ordenação; ela não deve ser usada como lista de índices de comando.

O URDF é evidência do modelo, não uma medição dos batentes físicos desta unidade. Velocidade de referência de 8°/s e envelope reduzido são decisões do projeto. Não foi feito teste de esforço/torque ou ajuste de ganhos.

## Interface selecionada

O tópico `/motion/joint_override_command` e o tipo `interface_protocol/msg/JointOverrideCommand` foram encontrados no robô. A mensagem contém peso, índices, posição, velocidade, torque de feedforward, torque, rigidez e amortecimento. O novo programa envia apenas dois elementos em cada vetor, com `joint_indices=[23,24]`.

O [exemplo oficial da EngineAI](https://github.com/engineai-robotics/engineai_ros2_workspace/blob/c41043f64ca1d308be187ebdcc2eaae40884f59c/src/interface_example/scripts/upper_joint_override_example.py) exige `lower_body_balance`. O headFollow segue essa exigência e verifica o estado efetivamente publicado. Não usa `/hardware/joint_command`, que permite comando mais amplo das juntas, nem publica transições em `/motion/set_motion_state`.

`weight=0` é coerente com a desativação de override em `JointOverrideCommand::IsEnable()` do SDK local. O comportamento de retorno e o timeout do firmware instalado não foram comprovados fisicamente. A liberação é uma tentativa de devolução de controle, não uma parada certificada.

## Controlador já instalado e observações

Existe um processo `/usr/bin/python3 /home/ubuntu/scripts-ipq/beniFiles/neck_controller.py`, nó ROS `safe_neck_controller`, API na porta 5055. O código foi copiado para `evidencias/original_neck_controller.py`; um arquivo comprimido preserva também o XML DDS. Nenhum arquivo original ou serviço foi alterado.

Na versão lida:

- `/move`, `/step` e `/center` retornam sucesso sem propagar a recusa do controlador.
- `balance_mode_active` representa uma solicitação local, não confirmação de `MotionState`.
- `has_hardware_feedback` permanece verdadeiro depois da primeira amostra; o status não informa idade da leitura.
- O loop pode continuar publicando sem verificar a atualidade da telemetria ou o modo real.
- Os erros de publicação são ignorados pelo `except`.

Isso impede tratar o sucesso HTTP como prova de movimento. O novo controlador adiciona verificações e respostas HTTP 409 para comandos recusados.

Na primeira amostra DDS confirmada, o robô estava em `idle`, só oferecia transição para `passive`, com pitch `0,510986 rad` (29,28°), yaw `−0,072205 rad` (−4,14°) e torques reportados zero. A API antiga indicava `balance_mode_requested=true`. Essa discrepância ficou registrada.

**O estado mudou durante o trabalho, sem comandos de movimento deste agente.** No teste do headFollow em leitura, o robô reportou `lower_body_balance`, pitch 5,18°, yaw 19,82°, 25 juntas e idade da amostra de 0,015 s. O nó `safe_neck_controller` continuou presente. Portanto o estado inicial `idle` não deve ser interpretado como estado permanente. Consulte o painel para valores atuais.

## Implementação e validação

O projeto usa a biblioteca padrão do Python para HTTP e controle. ROS é necessário somente no Orin. O painel web tem controles dos dois eixos, centro, cópia da posição medida, autorização por botão mantido pressionado e visualização da telemetria.

Foram executados 18 testes automatizados: restrição às juntas do pescoço, graus/radianos, velocidade da referência, sincronização inicial, limites e números inválidos, perda de telemetria, perda de modo, concorrência, watchdog, rejeição de pulso atrasado, cancelamento e API HTTP. Resultado: todos passaram; ver `evidencias/testes.txt`.

O programa foi copiado para `/home/ubuntu/headFollow` e executado em **somente leitura**, sem criar publicador de movimento. A API respondeu com posições reais; ver `evidencias/headfollow_status_real.json`. O SDK original e o controlador existente foram preservados.

O modo simulado foi renderizado no Firefox. As capturas e o resultado do teste de interação estão em `evidencias/`. A leitura real confirmou funcionamento do transporte, mas **não comprova atuação dos motores pelo novo programa**.

## Pendências para teste físico

1. Coordenar a transferência do controlador existente: não podem existir dois publicadores disputando override. O headFollow bloqueia na presença de outro publicador, mesmo que ele pareça ocioso.
2. Preparar postura e modo do robô pelo procedimento oficial; confirmar leitura atual, posição dentro do envelope e acesso à parada física.
3. Executar deslocamento pequeno e verificar sentido, precisão, esforço, ganho e comportamento ao liberar override.
4. Confirmar com a EngineAI o timeout do comando no firmware e a reação a processo encerrado abruptamente. O watchdog Python não cobre morte do processo, falha de hardware ou perda total do DDS.

Não foi implementado seguimento automático de rosto: primeiro é necessário validar o controle manual e os limites desta unidade.

## Fontes preservadas

- `docs/fontes_locais.json`: caminhos originais e cópias dos 15 PDF/DOCX examinados.
- `docs/sdk_local/`: URDF T800, modelo, conversor de override, bridge e mensagens.
- `evidencias/sdk_commit.txt`: commit do SDK local; o repositório já continha alterações alheias e não foi modificado.
- [Repositório ROS 2 oficial](https://github.com/engineai-robotics/engineai_ros2_workspace/tree/c41043f64ca1d308be187ebdcc2eaae40884f59c), branch `community`; a árvore consultada foi salva em `docs/engineai_oficial/tree.json`. O exemplo e o YAML foram baixados dessa branch, e a árvore registra o commit observado na consulta.
- [SDK nativo oficial](https://github.com/engineai-robotics/engineai_robotics_native_sdk).
- [Página do T800 do fabricante](https://en.engineai.com.cn/product-t800): referência adicional para os dois eixos e suas amplitudes nominais.

Os documentos e exemplos externos preservam os direitos e as licenças de seus autores. As descobertas de estado de execução se referem às amostras coletadas, não a uma garantia de estado futuro.
