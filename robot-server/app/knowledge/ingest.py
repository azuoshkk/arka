import argparse
import hashlib
import json
import re
import uuid

from pathlib import Path

from qdrant_client import models

from app.config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

from app.knowledge.chunker import (
    chunk_document,
)

from app.knowledge.loaders import (
    is_supported_file,
    load_file,
)

from app.knowledge.embedder import (
    embed_texts,
)

from app.knowledge.vector_store import (
    ensure_collection,
    upload_points,
)


# ============================================================
# DETECTOR DE CONTEÚDO RESTRITO
# ============================================================

SECRET_PATTERNS = [

    # password / senha / passwd
    # permite algumas palavras entre "password"
    # e o valor, por exemplo:
    # "password of WIFI is e123..."
    re.compile(
        r"(?is)"
        r"\b(password|senha|passwd|pwd)\b"
        r".{0,80}?"
        r"(?:is|é|:|=)"
        r"\s*[\"']?"
        r"[A-Za-z0-9!@#$%^&*._\-]{4,}"
    ),

    # API key / token / secret key
    re.compile(
        r"(?is)"
        r"\b(api[_ -]?key|"
        r"access[_ -]?token|"
        r"secret[_ -]?key)\b"
        r".{0,50}?"
        r"(?:is|é|:|=)"
        r"\s*[\"']?"
        r"[A-Za-z0-9._\-]{6,}"
    ),

    # bearer token
    re.compile(
        r"(?i)"
        r"\bbearer\s+"
        r"[A-Za-z0-9._\-]{8,}"
    ),

    # private keys
    re.compile(
        r"-----BEGIN "
        r"(?:RSA |EC |OPENSSH )?"
        r"PRIVATE KEY-----"
    ),
]


def looks_restricted(text):

    return any(
        pattern.search(text)
        for pattern
        in SECRET_PATTERNS
    )


# ============================================================
# HASH DE CHUNK
# ============================================================

def normalized_chunk_hash(text):

    normalized = "\n".join(
        line.rstrip()
        for line
        in text.strip().splitlines()
    )

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# MANIFEST
# ============================================================

def load_manifest(directory):

    manifest_path = (
        directory
        / "00_INDEX"
        / "PACKAGE_MANIFEST.json"
    )

    if not manifest_path.exists():
        return None

    return json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )


def collect_manifest_files(
    directory,
    manifest,
):

    records = manifest.get(
        "files",
        [],
    )

    available_paths = {
        item["package_path"].lower()
        for item in records
    }

    selected = []

    for item in records:

        relative = Path(
            item["package_path"]
        )

        path = (
            directory
            / relative
        )

        if not path.exists():

            print(
                f"⚠️ Ausente no pacote: "
                f"{relative}"
            )

            continue

        if not is_supported_file(path):
            continue

        # --------------------------------------------
        # TXT canônico > PDF/DOCX equivalente
        # --------------------------------------------

        if path.suffix.lower() in {
            ".pdf",
            ".docx",
        }:

            txt_equivalent = str(
                relative.with_suffix(
                    ".txt"
                )
            ).lower()

            if (
                txt_equivalent
                in available_paths
            ):
                continue

        selected.append(
            (
                path,
                item,
            )
        )

    return selected


def collect_fallback_files(
    directory,
):
    """
    Fallback para outros projetos que ainda
    não possuem PACKAGE_MANIFEST.json.
    """

    result = []

    for path in directory.rglob(
        "*"
    ):

        if not path.is_file():
            continue

        relative = (
            path.relative_to(
                directory
            )
        )

        # Nunca indexar índices internos
        if (
            "00_INDEX"
            in relative.parts
        ):
            continue

        if not is_supported_file(
            path
        ):
            continue

        rel = str(relative)

        result.append((
            path,
            {
                "package_path":
                    rel,

                "original_relpath":
                    rel,

                "category":
                    "UNKNOWN",

                "importance":
                    "MEDIUM",

                "state":
                    "CURRENT",

                "sha256":
                    None,
            },
        ))

    return result


# ============================================================
# INGESTÃO
# ============================================================

def ingest_directory(
    directory,
    project,
    reset=False,
):

    directory = Path(
        directory
    )

    manifest = load_manifest(
        directory
    )

    if manifest:

        files = (
            collect_manifest_files(
                directory,
                manifest,
            )
        )

        manifest_mode = True

    else:

        files = (
            collect_fallback_files(
                directory
            )
        )

        manifest_mode = False

    if not files:

        print(
            "Nenhum documento "
            "suportado encontrado."
        )

        return

    print()

    print(
        f"Projeto: {project}"
    )

    print(
        "Modo de seleção: "
        + (
            "PACKAGE_MANIFEST.json"
            if manifest_mode
            else "varredura da pasta"
        )
    )

    print(
        f"Arquivos selecionados: "
        f"{len(files)}"
    )

    print()

    records = []

    # Evita chunks realmente idênticos
    # em documentos diferentes.
    seen_chunk_hashes = set()

    restricted_chunks = 0

    duplicate_chunks = 0

    empty_files = 0

    for path, metadata in files:

        print(
            f"📄 Processando: "
            f"{path.name}"
        )

        pages = load_file(
            path
        )

        if not pages:

            empty_files += 1

            continue

        for page_data in pages:

            chunks = chunk_document(
                path=path,

                text=
                    page_data["text"],

                chunk_size=
                    CHUNK_SIZE,

                overlap=
                    CHUNK_OVERLAP,
            )

            for index, chunk_data in enumerate(
                chunks
            ):

                chunk = (
                    chunk_data["text"]
                )

                chunk_hash = (
                    normalized_chunk_hash(
                        chunk
                    )
                )

                if (
                    chunk_hash
                    in seen_chunk_hashes
                ):

                    duplicate_chunks += 1

                    continue

                seen_chunk_hashes.add(
                    chunk_hash
                )

                # ----------------------------------
                # ACCESS CONTROL
                # ----------------------------------

                access = (
                    "restricted"
                    if looks_restricted(
                        chunk
                    )
                    else "internal"
                )

                if (
                    access
                    == "restricted"
                ):
                    restricted_chunks += 1

                category = (
                    metadata.get(
                        "category",
                        "UNKNOWN",
                    )
                )

                importance = (
                    metadata.get(
                        "importance",
                        "MEDIUM",
                    )
                )

                package_path = (
                    metadata.get(
                        "package_path",

                        str(
                            path.relative_to(
                                directory
                            )
                        ),
                    )
                )

                embedding_text = (
                    f"Projeto: "
                    f"{project}\n"

                    f"Categoria: "
                    f"{category}\n"

                    f"Documento: "
                    f"{path.name}\n"

                    f"Caminho: "
                    f"{package_path}\n"

                    f"{chunk}"
                )

                records.append({

                    "source":
                        path.name,

                    "path":
                        str(path),

                    "package_path":
                        package_path,

                    "original_relpath":
                        metadata.get(
                            "original_relpath"
                        ),

                    "category":
                        category,

                    "importance":
                        importance,

                    "state":
                        metadata.get(
                            "state",
                            "CURRENT",
                        ),

                    "sha256":
                        metadata.get(
                            "sha256"
                        ),

                    "chunk_sha256":
                        chunk_hash,

                    "access":
                        access,

                    "page":
                        page_data["page"],

                    "chunk_index":
                        index,

                    "start_line":
                        chunk_data.get(
                            "start_line"
                        ),

                    "end_line":
                        chunk_data.get(
                            "end_line"
                        ),

                    "text":
                        chunk,

                    "embedding_text":
                        embedding_text,
                })

    if not records:

        print(
            "Nenhum texto válido "
            "foi encontrado."
        )

        return

    print()
    print(
        "----- PREPARAÇÃO -----"
    )

    print(
        f"Trechos únicos: "
        f"{len(records)}"
    )

    print(
        f"Trechos duplicados "
        f"ignorados: "
        f"{duplicate_chunks}"
    )

    print(
        f"Trechos restricted: "
        f"{restricted_chunks}"
    )

    print(
        f"Arquivos sem texto: "
        f"{empty_files}"
    )

    print()
    print(
        "Gerando embeddings..."
    )

    embeddings = embed_texts(
        [
            item[
                "embedding_text"
            ]
            for item
            in records
        ]
    )

    vector_size = len(
        embeddings[0]
    )

    print(
        f"Dimensão dos vetores: "
        f"{vector_size}"
    )

    ensure_collection(
        vector_size,
        reset=reset,
    )

    points = []

    for record, vector in zip(
        records,
        embeddings,
    ):

        unique_key = (
            f"{project}|"
            f"{record['package_path']}|"
            f"{record['page']}|"
            f"{record['chunk_index']}|"
            f"{record['chunk_sha256']}"
        )

        point_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                unique_key,
            )
        )

        points.append(
            models.PointStruct(
                id=point_id,

                vector=vector,

                payload={
                    "project":
                        project,

                    "access":
                        record["access"],

                    "category":
                        record["category"],

                    "importance":
                        record[
                            "importance"
                        ],

                    "state":
                        record["state"],

                    "source":
                        record["source"],

                    "path":
                        record["path"],

                    "package_path":
                        record[
                            "package_path"
                        ],

                    "original_relpath":
                        record[
                            "original_relpath"
                        ],

                    "page":
                        record["page"],

                    "chunk_index":
                        record[
                            "chunk_index"
                        ],

                    "start_line":
                        record[
                            "start_line"
                        ],

                    "end_line":
                        record[
                            "end_line"
                        ],

                    "sha256":
                        record["sha256"],

                    "chunk_sha256":
                        record[
                            "chunk_sha256"
                        ],

                    "text":
                        record["text"],
                },
            )
        )

    upload_points(
        points
    )

    print()
    print(
        "✅ Indexação concluída."
    )

    print(
        f"{len(points)} "
        f"trechos armazenados."
    )

    print(
        f"{restricted_chunks} "
        f"trechos marcados "
        f"como restricted."
    )


if __name__ == "__main__":

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "directory"
    )

    parser.add_argument(
        "--project",
        required=True,
    )

    parser.add_argument(
        "--reset",
        action="store_true",
    )

    args = parser.parse_args()

    ingest_directory(
        directory=
            args.directory,

        project=
            args.project,

        reset=
            args.reset,
    )
