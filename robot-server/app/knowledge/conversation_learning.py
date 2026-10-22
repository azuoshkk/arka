from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import uuid

from qdrant_client import models

from app.knowledge.embedder import embed_texts
from app.knowledge.training_pdf import COLLECTION
from app.knowledge.vector_store import client


SKIP_TERMS = {
    "oi",
    "olá",
    "ola",
    "obrigado",
    "obrigada",
    "valeu",
    "tchau",
    "bom dia",
    "boa tarde",
    "boa noite",
}

ERROR_MARKERS = (
    "não encontrei essa informação",
    "não consegui concluir",
    "erro",
    "tente novamente",
)


def should_learn(question: str, answer: str) -> bool:
    q = " ".join((question or "").lower().split())
    a = " ".join((answer or "").lower().split())

    if not q or not a:
        return False

    if q in SKIP_TERMS:
        return False

    if len(q) < 8 or len(a) < 20:
        return False

    if any(marker in a for marker in ERROR_MARKERS):
        return False

    return True


def learn_exchange(
    question: str,
    answer: str,
    author: str,
    route: str,
    sources=None,
):
    if not should_learn(question, answer):
        return None

    combined = (
        f"Pergunta: {question.strip()}\n"
        f"Resposta: {answer.strip()}"
    )

    vector = embed_texts([combined])[0]

    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config=models.VectorParams(
                size=len(vector),
                distance=models.Distance.COSINE,
            ),
        )

    digest = hashlib.sha256(
        combined.encode("utf-8")
    ).hexdigest()

    point_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "conversation:" + digest,
        )
    )

    payload = {
        "project": "t800",
        "access": "internal",
        "category": "conversation",
        "importance": "low",
        "state": "published",
        "approved": True,
        "source": "Conversa corporativa",
        "package_path": f"conversation/{point_id}",
        "text": combined,
        "question": question.strip(),
        "answer": answer.strip(),
        "author": author or "unknown",
        "route": route,
        "created": datetime.now(timezone.utc).isoformat(),
        "sources": [
            s.get("source", "")
            for s in (sources or [])
            if isinstance(s, dict)
        ][:10],
        "chunk_sha256": digest,
    }

    client.upsert(
        COLLECTION,
        points=[
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        ],
        wait=True,
    )

    return point_id
