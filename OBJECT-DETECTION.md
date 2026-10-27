# Detecção de objetos

## Ativo: YOLOX-S + Moondream

`scripts/detect-body.py` roda no notebook, ONNX Runtime CPU, duas threads. Lê quadros pelo túnel local e envia caixas ao adaptador. As imagens ficam na RAM. Até 60 caixas por quadro, 80 categorias COCO, limiar 0,35 e NMS por classe. Não há reconhecimento facial nem garantia de detectar todos os objetos. Resultados velhos desaparecem do overlay.

Dependências extras: `requirements-vision.txt`. Baixe o ONNX de origem oficial com `python scripts/download-detector.py`. Não versionar os pesos. O código usa pré-processamento RGB, letterbox superior/esquerdo e decodificação YOLOX, conforme o [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox), modelo Apache-2.0.

Moondream responde pela descrição textual, exclusivamente CPU, sob pedido. O vídeo continua enquanto analisa. A análise não é aprendizado: não treina modelos nem grava no RAG.

## Experimental: NVIDIA LocateAnything-3B

Testado localmente em 27/10/2026 através do port C++/ggml da LocalAI: https://github.com/mudler/locate-anything.cpp . Modelo NVIDIA: https://huggingface.co/nvidia/LocateAnything-3B . Observe a licença própria dos pesos antes de outros usos.

Quantização Q4_K: 4.716.320.320 bytes, SHA256 `894088a00a2cd2bbb7f34b12893988dd0376c8ed92213a9f2cf6420f1e3901da`. Build CPU, modo slow, 4 threads, imagem reduzida para até 448 px. Teste real levou **20,97 s** e retornou 9 caixas (categorias solicitadas: pessoa, copo, notebook, monitor, teclado e cadeira). Isso não é prova de precisão de todas as caixas. Ainda **não integrado como detector ativo**: substituir o fluxo rápido por isso pioraria a latência. Próxima etapa: modo explícito sob demanda e comparação com cenas anotadas.

O modelo e a compilação ficam em `.local/locate-anything/` e `.local/models/`, fora do Git. O build do port usa CMake com `-DLA_GGML_CUDA=OFF -DLA_SHARED=ON`. Não foi alterado o Ollama: chat permanece na GPU, embedding na CPU, contexto 4096.

## Testes

```bash
node tests/test_wake.cjs
node tests/test_vision_intent.cjs
node tests/test_monitor_queue.cjs
.venv/bin/python -m unittest discover -s tests -p 'test_object_detection.py' -q
.venv/bin/python -m unittest discover -s tests -p 'test_*web.py' -q
```

18 testes web/rosto/visão, 3 de detecção e cenários JS passaram. Integração depende do ambiente local com modelos e credenciais; testes unitários não substituem validação acústica e de cenas reais.
