from qdrant_client import QdrantClient
from qdrant_client import models

from app.config import (
    QDRANT_URL,
    QDRANT_COLLECTION,
)


client = QdrantClient(
    url=QDRANT_URL
)


def ensure_collection(
    vector_size,
    reset=False,
):

    exists = client.collection_exists(
        QDRANT_COLLECTION
    )

    if reset and exists:

        client.delete_collection(
            QDRANT_COLLECTION
        )

        exists = False

    if not exists:

        client.create_collection(
            collection_name=
                QDRANT_COLLECTION,

            vectors_config=
                models.VectorParams(
                    size=vector_size,
                    distance=
                        models.Distance.COSINE,
                ),
        )


def upload_points(points):

    client.upload_points(
        collection_name=
            QDRANT_COLLECTION,

        points=points,

        wait=True,
    )


def search(
    vector,
    project,
    limit=15,
    allowed_access=(
        "public",
        "internal",
        "restricted",
    ),
):

    must = [
        models.FieldCondition(
            key="project",

            match=models.MatchValue(
                value=project
            ),
        )
    ]

    if allowed_access:

        must.append(
            models.FieldCondition(
                key="access",

                match=models.MatchAny(
                    any=list(
                        allowed_access
                    )
                ),
            )
        )

    result = client.query_points(
        collection_name=
            QDRANT_COLLECTION,

        query=vector,

        query_filter=
            models.Filter(
                must=must
            ),

        limit=limit,

        with_payload=True,
    )

    return result.points
