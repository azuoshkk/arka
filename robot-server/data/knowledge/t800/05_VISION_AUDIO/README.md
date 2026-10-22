# T800 Face Follow

## Prioridade
Mantém a regra original: **menor número = maior prioridade**.

## Arquivos
- `app.py`: ROS2 + reconhecimento LBPH + Face Follow + pescoço + servidor web.
- `camera_scanner_ros2.py`: descoberta/captura das câmeras `CompressedImage`.
- `templates/index.html`: painel local.
- `run.sh`: inicialização.
- `rosto_dados/`: criado automaticamente.

## Antes de rodar
Confirme que não há outro controlador disputando `/motion/joint_override_command`:

    ros2 topic info /motion/joint_override_command -v
    ros2 node list | grep -E 'neck|head'

O T800 já apresentou um `safe_neck_controller`; não rode dois controladores do pescoço simultaneamente.

Confira dependências:

    python3 - <<'PY'
    import cv2, numpy, flask, rclpy
    print("OpenCV", cv2.__version__)
    print("cv2.face =", hasattr(cv2, "face"))
    print("OK")
    PY

`cv2.face` precisa ser `True`.

## Rodar

    chmod +x run.sh
    ./run.sh

Abra, em outro aparelho na mesma rede:

    http://192.168.102.133:3110

## Cadastro recomendado
1. Digite nome e prioridade.
2. Clique `Criar/atualizar`.
3. Deixe apenas essa pessoa na imagem.
4. Capture ~20-30 fotos, mudando levemente pose/expressão.
5. Clique `Treinar modelo`.

Também é possível selecionar várias fotos no notebook/celular e usar `Enviar fotos`.
O servidor detecta e recorta o maior rosto de cada upload.

## Primeiro teste do movimento
Comece com o Face Follow OFF e confirme que o status mostra `Pescoço: OK`.
Depois ligue o Face Follow.

Se o rosto estiver à direita e o T800 virar para a esquerda, altere em `app.py`:

    YAW_SIGN = -1.0

Se o movimento vertical estiver invertido:

    PITCH_SIGN = -1.0

## Observação importante
A estrutura de `JointState` e `JointOverrideCommand` usada aqui segue os códigos fornecidos/analisados.
Se `Pescoço: aguardando feedback` nunca mudar para OK, execute:

    ros2 interface show interface_protocol/msg/JointState
    ros2 topic echo /hardware/joint_state --once

e ajuste o callback `feedback()` conforme os campos reais publicados pelo firmware.
