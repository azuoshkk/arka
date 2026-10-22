OLLAMA_URL = "http://127.0.0.1:11434"

LLM_MODEL = "qwen3:8b"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"

QDRANT_URL = "http://127.0.0.1:6333"
QDRANT_COLLECTION = "arka_knowledge"

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

TOP_K = 5

# Inicialmente conservador.
# Depois vamos calibrar olhando os scores reais.
MIN_SCORE = 0.35

