import os

import requests

from app.config import (
    OLLAMA_URL,
    EMBEDDING_MODEL,
)


EMBED_KEEP_ALIVE = os.getenv(
    "ARKA_EMBED_KEEP_ALIVE",
    "-1",
)
if EMBED_KEEP_ALIVE == "-1":
    EMBED_KEEP_ALIVE = -1

EMBED_NUM_GPU = int(
    os.getenv(
        "ARKA_EMBED_NUM_GPU",
        "0",
    )
)


def embed_texts(
    texts,
    batch_size=16,
):

    if isinstance(
        texts,
        str,
    ):
        texts = [texts]

    embeddings = []

    for start in range(
        0,
        len(texts),
        batch_size,
    ):

        batch = texts[
            start:
            start + batch_size
        ]

        response = requests.post(
            f"{OLLAMA_URL}/api/embed",

            json={
                "model":
                    EMBEDDING_MODEL,

                "input":
                    batch,

                # MUITO IMPORTANTE:
                # embedding fica na CPU.
                "options": {
                    "num_gpu":
                        EMBED_NUM_GPU,
                },

                "keep_alive":
                    EMBED_KEEP_ALIVE,
            },

            timeout=300,
        )

        response.raise_for_status()

        data = response.json()

        embeddings.extend(
            data["embeddings"]
        )

    return embeddings


def embed_text(
    text,
):

    return embed_texts(
        [text]
    )[0]
