from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot-server"))
import time

import requests

from app.config import (
    OLLAMA_URL,
    EMBEDDING_MODEL,
    LLM_MODEL,
)


def ns_to_s(value):
    return (
        (value or 0)
        / 1_000_000_000
    )


print()
print(
    "🔥 Preparando modelos..."
)


# ============================================================
# EMBEDDING CPU
# ============================================================

start = time.perf_counter()

r = requests.post(
    f"{OLLAMA_URL}/api/embed",

    json={
        "model":
            EMBEDDING_MODEL,

        "input":
            "Arka warmup",

        "keep_alive":
            -1,

        "options": {
            "num_gpu":
                0,
        },
    },

    timeout=180,
)

r.raise_for_status()

data = r.json()

print(
    "✅ Embedding CPU "
    f"{time.perf_counter() - start:.3f}s "
    "| load="
    f"{ns_to_s(data.get('load_duration')):.3f}s"
)


# ============================================================
# QWEN GPU
# ============================================================

start = time.perf_counter()

r = requests.post(
    f"{OLLAMA_URL}/api/chat",

    json={
        "model":
            LLM_MODEL,

        "stream":
            False,

        "think":
            False,

        "keep_alive":
            -1,

        "messages": [
            {
                "role":
                    "user",

                "content":
                    "Responda apenas OK.",
            }
        ],

        "options": {
            "temperature":
                0,

            "num_predict":
                3,

            "num_ctx":
                4096,
        },
    },

    timeout=180,
)

r.raise_for_status()

data = r.json()

print(
    "✅ Qwen GPU "
    f"{time.perf_counter() - start:.3f}s "
    "| load="
    f"{ns_to_s(data.get('load_duration')):.3f}s"
)


# ============================================================
# RESIDÊNCIA
# ============================================================

r = requests.get(
    f"{OLLAMA_URL}/api/ps",
    timeout=10,
)

r.raise_for_status()

print()

for model in r.json().get(
    "models",
    [],
):

    print(
        "📦",
        model.get("name"),
        "| VRAM:",
        f"{model.get('size_vram', 0) / 1024**3:.2f} GB",
    )
