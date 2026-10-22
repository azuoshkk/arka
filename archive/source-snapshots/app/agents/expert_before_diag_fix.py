import hashlib
import requests

from app.config import (
    OLLAMA_URL,
    LLM_MODEL,
    TOP_K,
    MIN_SCORE,
)

from app.knowledge.embedder import (
    embed_text,
)

from app.knowledge.vector_store import (
    search,
)


SYSTEM_PROMPT = """
Você é Arka, especialista técnico interno.

Sua função é responder perguntas usando
exclusivamente as evidências presentes nas
fontes recuperadas da base de conhecimento.

REGRAS OBRIGATÓRIAS:

1. Não invente fatos.

2. Não use conhecimento próprio para
   preencher lacunas.

3. O nome ou título de um arquivo NÃO é
   evidência de que um evento, problema,
   falha ou comportamento ocorreu.

4. Só afirme algo factual quando o CONTEÚDO
   de pelo menos uma fonte recuperada
   sustentar explicitamente essa afirmação.

5. Se precisar inferir algo, escreva
   explicitamente:

   "Inferência:"

   e explique em quais fontes a inferência
   está baseada.

6. Se as fontes não forem suficientes,
   responda exatamente:

   "Não encontrei essa informação na
   documentação disponível."

7. Sempre indique as fontes utilizadas no
   formato [Fonte 1], [Fonte 2], etc.

8. Preserve nomes técnicos, códigos, GPIOs,
   versões, comandos e números exatamente
   como aparecem.

9. Responda em português brasileiro.

10. Não revele nem tente reconstruir
    credenciais, senhas, tokens ou segredos
    que não estejam nas fontes fornecidas.
"""


def _importance_bonus(
    payload,
):

    importance = (
        payload.get(
            "importance",
            "MEDIUM",
        )
        or "MEDIUM"
    ).upper()

    return {
        "CRITICAL": 0.025,
        "HIGH": 0.012,
        "MEDIUM": 0.0,
        "LOW": -0.01,
    }.get(
        importance,
        0.0,
    )


def _diversify(
    results,
    limit,
):
    """
    Evita que top-K seja dominado por
    vários pedaços do mesmo documento.
    """

    ranked = sorted(
        results,

        key=lambda item: (
            item.score

            + _importance_bonus(
                item.payload
                or {}
            )
        ),

        reverse=True,
    )

    selected = []

    per_source = {}

    seen_text = set()

    for result in ranked:

        payload = (
            result.payload
            or {}
        )

        text = payload.get(
            "text",
            "",
        )

        text_hash = (
            hashlib.sha256(
                text.strip().encode(
                    "utf-8"
                )
            ).hexdigest()
        )

        if text_hash in seen_text:
            continue

        source_key = (
            payload.get(
                "package_path"
            )

            or payload.get(
                "path"
            )

            or payload.get(
                "source"
            )

            or "unknown"
        )

        # no máximo 2 chunks
        # do mesmo arquivo
        if (
            per_source.get(
                source_key,
                0,
            )
            >= 2
        ):
            continue

        seen_text.add(
            text_hash
        )

        per_source[
            source_key
        ] = (
            per_source.get(
                source_key,
                0,
            )
            + 1
        )

        selected.append(
            result
        )

        if (
            len(selected)
            >= limit
        ):
            break

    return selected


def retrieve(
    question,
    project,
):

    query_text = (
        f"Projeto: {project}\n"
        f"Pergunta técnica: "
        f"{question}"
    )

    vector = embed_text(
        query_text
    )

    # Primeiro recuperamos mais.
    candidate_limit = max(
        TOP_K * 3,
        15,
    )

    results = search(
        vector=vector,

        project=project,

        limit=
            candidate_limit,

        # restricted NÃO entra
        allowed_access=(
            "public",
            "internal",
            "restricted",
        ),
    )

    valid = [
        result
        for result
        in results
        if (
            result.score
            >= MIN_SCORE
        )
    ]

    return _diversify(
        valid,
        TOP_K,
    )


def answer(
    question,
    project,
):

    results = retrieve(
        question,
        project,
    )

    if not results:

        return {
            "answer":
                "Não encontrei essa "
                "informação na documentação "
                "disponível.",

            "sources": [],
        }

    context_parts = []

    sources = []

    for index, result in enumerate(
        results,
        start=1,
    ):

        payload = (
            result.payload
            or {}
        )

        source = payload.get(
            "source",
            "fonte desconhecida",
        )

        page = payload.get(
            "page"
        )

        category = payload.get(
            "category"
        )

        package_path = payload.get(
            "package_path"
        )

        start_line = payload.get(
            "start_line"
        )

        end_line = payload.get(
            "end_line"
        )

        label = (
            f"Fonte {index}: "
            f"{source}"
        )

        if page is not None:

            label += (
                f", página {page}"
            )

        if (
            start_line is not None
            and end_line is not None
        ):

            label += (
                f", linhas "
                f"{start_line}-"
                f"{end_line}"
            )

        metadata_lines = []

        if category:

            metadata_lines.append(
                f"Categoria: "
                f"{category}"
            )

        if package_path:

            metadata_lines.append(
                f"Caminho: "
                f"{package_path}"
            )

        context_parts.append(
            f"[{label}]\n"

            + "\n".join(
                metadata_lines
            )

            + (
                "\n"
                if metadata_lines
                else ""
            )

            + payload.get(
                "text",
                "",
            )
        )

        sources.append({
            "number":
                index,

            "source":
                source,

            "page":
                page,

            "score":
                result.score,

            "category":
                category,

            "path":
                package_path,

            "start_line":
                start_line,

            "end_line":
                end_line,
        })

    context = "\n\n".join(
        context_parts
    )

    user_prompt = f"""
PROJETO:
{project}

PERGUNTA:
{question}

FONTES RECUPERADAS:

{context}

TAREFA:

Responda usando somente o conteúdo textual
das fontes acima.

Não trate nomes de arquivos, nomes de
relatórios ou metadados como prova de que
um fato ocorreu.

Para cada afirmação técnica relevante,
cite pelo menos uma fonte no formato
[Fonte 1].

Se houver somente indícios, mas não
evidência explícita, não transforme
o indício em fato.

Se fizer inferência, marque-a explicitamente
como "Inferência:".

Se as fontes não permitirem responder com
segurança, responda:

"Não encontrei essa informação na
documentação disponível."
"""

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                False,

            "think":
                False,

            "messages": [
                {
                    "role":
                        "system",

                    "content":
                        SYSTEM_PROMPT,
                },
                {
                    "role":
                        "user",

                    "content":
                        user_prompt,
                },
            ],

            "options": {
                "temperature":
                    0.0,

                "num_predict":
                    650,
            },
        },

        timeout=300,
    )

    response.raise_for_status()

    data = response.json()

    return {
        "answer":
            data[
                "message"
            ][
                "content"
            ],

        "sources":
            sources,
    }
