# Arka

Assistente web e corpo visual no Raspberry Pi. Notebook: FastAPI, Whisper, Ollama, RAG/Qdrant, Kokoro e visão. Raspberry: câmera, microfone, rosto e saída de som.

## Para o colega que vai trabalhar na interface

HTML/CSS/JavaScript sem build. Interface principal: `web/index.html`, `web/assets/app.js`, `web/assets/style.css`. Rosto: `web/face.html`, `web/assets/face.js`, `web/assets/face.css`. Painel técnico: `web/monitor.html`, `web/assets/monitor.js`, `web/assets/monitor.css`.

Prévia apenas visual do rosto, sem modelos:

```bash
python3 -m http.server 8080 --bind 127.0.0.1 --directory web
# http://localhost:8080/face.html
```

O painel de câmera precisa do adaptador Raspberry e túnel SSH; veja [CORPO-ARKA.md](CORPO-ARKA.md). Preserve os IDs do HTML e os contratos de API. Não altere Router, autenticação, sessões ou RAG para mudar o design.

## Iniciar no notebook já configurado

```bash
./scripts/start-web.sh
# ./scripts/restart-web.sh
```

`requirements-web.txt` contém dependências adicionais da web; não representa todo o ambiente de IA. Chat: `qwen3:8b`, residente na GPU, `num_ctx=4096`. Embeddings: `qwen3-embedding:0.6b`, CPU. Não reindexar a base para mudanças visuais.

## Visão e estado atual

Veja [OBJECT-DETECTION.md](OBJECT-DETECTION.md) para o detector CPU, modelos, testes e limitações. YOLOX desenha caixas rápidas; Moondream descreve a captura sob pedido. NVIDIA LocateAnything foi testado na CPU, mas ainda não substitui a visão ativa: o teste levou aproximadamente 21 segundos.

## Dados e segurança

Não adicionar `.local/`, credenciais, chaves, modelos, bancos, documentos internos, capturas, logs ou backups. O `.gitignore` protege novas inclusões, mas não elimina arquivos já rastreados nem o histórico anterior. Esta atualização publica somente código/testes/documentação selecionados. A revisão dos documentos/banco já presentes no histórico público permanece pendente.
