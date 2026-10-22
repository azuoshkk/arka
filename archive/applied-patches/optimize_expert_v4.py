from pathlib import Path
from datetime import datetime
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

EXPERT = SERVER / "app/agents/expert.py"
BRIDGE = SERVER / "app/core/voice_bridge.py"
ARKA = SERVER / "arka.py"

RAG_CHECK = SERVER / "rag-check"
RAG_CHECK_CORE = SERVER / "rag-check-core"

BENCHMARK = SERVER / "benchmark_expert.py"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_expert_v4_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)


for path in (
    EXPERT,
    BRIDGE,
    ARKA,
    RAG_CHECK,
):

    if not path.exists():
        continue

    destination = (
        backup
        / path.relative_to(ROOT)
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        path,
        destination,
    )


print(
    "✅ Backup:",
    backup,
)


# ============================================================
# EXPERT.PY
# ============================================================

text = EXPERT.read_text(
    encoding="utf-8",
)


if "import json\n" not in text:

    text = (
        "import json\n"
        + text
    )


if "import time\n" not in text:

    text = (
        "import time\n"
        + text
    )


answer_start = text.find(
    "\ndef answer("
)

if answer_start == -1:

    raise RuntimeError(
        "Não encontrei def answer() "
        "em expert.py"
    )


# Preserva TODO retrieval/ranking atual.
#
# Substituímos apenas a etapa final:
# contexto -> Ollama -> resposta.

prefix = text[
    :answer_start
]


new_answer_section = r'''

REFUSAL_MESSAGE = (
    "Não encontrei essa informação "
    "na documentação disponível."
)


def _generation_limit(
    question,
):

    intents = detect_intents(
        question
    )

    # Perguntas de credencial normalmente
    # exigem respostas muito pequenas.

    if "credentials" in intents:
        return 180

    # Diagnóstico pode exigir explicação.

    if "diagnostics" in intents:
        return 420

    # ROS2 geralmente precisa incluir
    # caminhos, parâmetros e tópicos.

    if "ros2" in intents:
        return 420

    if (
        "vision_audio" in intents
        or "hardware" in intents
    ):
        return 360

    return 360


def _prepare_answer(
    question,
    project,
):

    started = (
        time.perf_counter()
    )

    results = retrieve(
        question,
        project,
    )

    retrieval_seconds = (
        time.perf_counter()
        - started
    )

    if not support_guard(
        question,
        results,
    ):

        return {
            "ready":
                False,

            "answer":
                REFUSAL_MESSAGE,

            "sources":
                [],

            "user_prompt":
                None,

            "retrieval_seconds":
                retrieval_seconds,

            "num_predict":
                0,
        }

    intents = detect_intents(
        question
    )

    context_results = (
        results
    )

    # ========================================================
    # CREDENCIAIS
    #
    # Se já encontramos chunks que realmente contêm
    # evidência de rede + credencial, não mandamos
    # documentos genéricos para o Qwen.
    #
    # Além de ser mais preciso, isso reduz bastante
    # o tamanho do prompt.
    # ========================================================

    if "credentials" in intents:

        evidence = [
            result

            for result in results

            if contains_credential_evidence(
                result
            )
        ]

        if evidence:

            context_results = (
                evidence[:3]
            )

    context_parts = []
    sources = []

    for index, result in enumerate(
        context_results,
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

        # Não precisamos mandar caminhos enormes
        # ao modelo para toda pergunta.
        #
        # O caminho continua disponível no retorno
        # sources, mas não polui o contexto.

        metadata = []

        if category:

            metadata.append(
                f"Categoria: {category}"
            )

        chunk_text = (
            payload.get(
                "text",
                "",
            )
            or ""
        )

        context_parts.append(
            f"[{label}]\n"
            + "\n".join(
                metadata
            )
            + (
                "\n"
                if metadata
                else ""
            )
            + chunk_text
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

Responda apenas à pergunta feita.

Use somente fatos explicitamente presentes
no conteúdo das fontes.

Não transforme nomes de arquivos ou títulos
em fatos.

Se a pergunta for sobre problemas ou falhas,
não apresente especificações gerais do robô.

Para cada problema mencionado, explique o
sintoma ou evidência documentada e, quando
disponível, como ele foi diagnosticado.

Não misture ros2_bridge do SDK nativo com
ros2_websocket_bridge ou gateways do dashboard
sem evidência explícita.

Cite afirmações técnicas com [Fonte N].

Se houver inferência, marque:
"Inferência:".

Se não houver evidência suficiente, responda:

"Não encontrei essa informação na documentação disponível."
"""

    return {
        "ready":
            True,

        "answer":
            None,

        "sources":
            sources,

        "user_prompt":
            user_prompt,

        "retrieval_seconds":
            retrieval_seconds,

        "num_predict":
            _generation_limit(
                question
            ),
    }


def _ollama_messages(
    user_prompt,
):

    return [
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
    ]


def answer(
    question,
    project,
):

    """
    Caminho tradicional.

    Mantido porque test_rag.py e os testes
    de regressão dependem desta função.
    """

    total_started = (
        time.perf_counter()
    )

    prepared = _prepare_answer(
        question,
        project,
    )

    if not prepared[
        "ready"
    ]:

        return {
            "answer":
                prepared["answer"],

            "sources":
                prepared["sources"],

            "metrics": {
                "retrieval":
                    prepared[
                        "retrieval_seconds"
                    ],

                "first_token":
                    None,

                "llm":
                    0.0,

                "total":
                    (
                        time.perf_counter()
                        - total_started
                    ),
            },
        }

    llm_started = (
        time.perf_counter()
    )

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                False,

            "think":
                False,

            "keep_alive":
                "30m",

            "messages":
                _ollama_messages(
                    prepared[
                        "user_prompt"
                    ]
                ),

            "options": {
                "temperature":
                    0.0,

                "num_predict":
                    prepared[
                        "num_predict"
                    ],
            },
        },

        timeout=300,
    )

    response.raise_for_status()

    data = response.json()

    finished = (
        time.perf_counter()
    )

    return {
        "answer":
            data[
                "message"
            ][
                "content"
            ],

        "sources":
            prepared[
                "sources"
            ],

        "metrics": {
            "retrieval":
                prepared[
                    "retrieval_seconds"
                ],

            "first_token":
                None,

            "llm":
                finished
                - llm_started,

            "total":
                finished
                - total_started,
        },
    }


def answer_stream(
    question,
    project,
    on_token=None,
):

    """
    Caminho usado pelo runtime da Arka.

    Faz o mesmo retrieval do answer(), mas o
    texto aparece conforme o Ollama gera tokens.
    """

    total_started = (
        time.perf_counter()
    )

    prepared = _prepare_answer(
        question,
        project,
    )

    if not prepared[
        "ready"
    ]:

        answer_text = (
            prepared[
                "answer"
            ]
        )

        if on_token:
            on_token(
                answer_text
            )

        finished = (
            time.perf_counter()
        )

        return {
            "answer":
                answer_text,

            "sources":
                prepared[
                    "sources"
                ],

            "metrics": {
                "retrieval":
                    prepared[
                        "retrieval_seconds"
                    ],

                "first_token":
                    (
                        finished
                        - total_started
                    ),

                "llm":
                    0.0,

                "total":
                    (
                        finished
                        - total_started
                    ),
            },
        }

    llm_started = (
        time.perf_counter()
    )

    first_token_seconds = (
        None
    )

    parts = []

    with requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                True,

            "think":
                False,

            "keep_alive":
                "30m",

            "messages":
                _ollama_messages(
                    prepared[
                        "user_prompt"
                    ]
                ),

            "options": {
                "temperature":
                    0.0,

                "num_predict":
                    prepared[
                        "num_predict"
                    ],
            },
        },

        stream=True,

        timeout=(
            5,
            300,
        ),

    ) as response:

        response.raise_for_status()

        for raw_line in (
            response.iter_lines(
                decode_unicode=True
            )
        ):

            if not raw_line:
                continue

            data = json.loads(
                raw_line
            )

            token = (
                data
                .get(
                    "message",
                    {}
                )
                .get(
                    "content",
                    ""
                )
            )

            if not token:
                continue

            if (
                first_token_seconds
                is None
            ):

                first_token_seconds = (
                    time.perf_counter()
                    - total_started
                )

            parts.append(
                token
            )

            if on_token:

                on_token(
                    token
                )

    finished = (
        time.perf_counter()
    )

    answer_text = "".join(
        parts
    ).strip()

    if not answer_text:

        answer_text = (
            REFUSAL_MESSAGE
        )

        if on_token:
            on_token(
                answer_text
            )

    return {
        "answer":
            answer_text,

        "sources":
            prepared[
                "sources"
            ],

        "metrics": {
            "retrieval":
                prepared[
                    "retrieval_seconds"
                ],

            "first_token":
                first_token_seconds,

            "llm":
                finished
                - llm_started,

            "total":
                finished
                - total_started,
        },
    }
'''


text = (
    prefix
    + new_answer_section
)

EXPERT.write_text(
    text,
    encoding="utf-8",
)

print(
    "✅ ExpertAgent V4 instalado."
)


# ============================================================
# VOICE_BRIDGE
#
# Apesar do nome legado, agora é também usado pelo TXT.
# ============================================================

BRIDGE.write_text(
r'''from __future__ import annotations

import re
import unicodedata

from app.agents.expert import (
    answer as expert_answer,
)

from app.core.router import (
    route_message,
)


EXPERT_ERROR_MESSAGE = (
    "Não consegui consultar a documentação "
    "técnica neste momento."
)


_last_route = "chat"
_expert_context = None


def normalize(
    text: str,
):

    value = unicodedata.normalize(
        "NFKD",
        text or "",
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    return (
        value
        .lower()
        .strip()
    )


def expand_expert_question(
    text: str,
):

    q = normalize(
        text
    )

    has_password = any(
        term in q

        for term in (
            "senha",
            "password",
            "credencial",
            "credenciais",
        )
    )

    has_network = any(
        term in q

        for term in (
            "wifi",
            "wi-fi",
            "internet",
            "rede",
            "wireless",
            "ssid",
        )
    )

    has_t800 = bool(
        re.search(
            r"\b(?:t[\s-]*800|800)\b",
            q,
        )
    )

    if (
        has_password
        and has_network
        and has_t800
    ):

        return (
            "Consulta técnica sobre credenciais "
            "de rede relacionadas ao robô T800 "
            "e à documentação da EngineAI. "
            "Procure especificamente informações "
            "sobre Wi-Fi, rede interna, SSID, "
            "senha, password e credenciais.\n\n"
            "Pergunta original do usuário:\n"
            + text
        )

    return text


def reset_voice_context():

    global _last_route
    global _expert_context

    _last_route = "chat"
    _expert_context = None


def looks_like_followup(
    text: str,
):

    q = normalize(
        text
    )

    patterns = (
        r"^e\b",
        r"^mas\b",
        r"^entao\b",
        r"^onde\b",
        r"^como\b",
        r"^qual\b",
        r"^quais\b",
        r"^isso\b",
        r"^esse\b",
        r"^essa\b",
        r"^esses\b",
        r"^essas\b",
        r"^ele\b",
        r"^ela\b",
        r"^dai\b",
    )

    return any(
        re.search(
            pattern,
            q,
        )

        for pattern
        in patterns
    )


def prepare_voice_route(
    text: str,
    project: str = "t800",
):

    """
    Faz SOMENTE o roteamento.

    Não chama o LLM e não executa o RAG.

    Isso permite que o runtime use
    answer_stream().
    """

    global _last_route
    global _expert_context

    decision = route_message(
        text
    )

    effective_question = (
        expand_expert_question(
            text
        )
    )

    # ========================================================
    # FOLLOW-UP TÉCNICO
    # ========================================================

    if (
        decision["route"]
        == "chat"
        and _last_route
        == "expert"
        and _expert_context
        and looks_like_followup(
            text
        )
    ):

        decision = {
            "route":
                "expert",

            "reason":
                "expert_followup",

            "confidence":
                0.95,
        }

        effective_question = (
            "Contexto da pergunta técnica anterior:\n"
            f"{_expert_context}\n\n"
            "Pergunta atual:\n"
            f"{text}"
        )

    # ========================================================
    # CHAT
    # ========================================================

    if (
        decision["route"]
        != "expert"
    ):

        _last_route = "chat"
        _expert_context = None

        return {
            "route":
                "chat",

            "reason":
                decision.get(
                    "reason"
                ),

            "confidence":
                decision.get(
                    "confidence"
                ),

            "question":
                text,
        }

    # ========================================================
    # EXPERT
    # ========================================================

    if (
        decision.get(
            "reason"
        )
        == "t800_alias_context"
        and "t800"
        not in normalize(
            effective_question
        )
    ):

        effective_question = (
            "No contexto do projeto T800:\n"
            + effective_question
        )

    _last_route = "expert"

    if _expert_context is None:

        _expert_context = (
            text
        )

    else:

        _expert_context = (
            _expert_context
            + "\n"
            + text
        )[-700:]

    return {
        "route":
            "expert",

        "reason":
            decision.get(
                "reason"
            ),

        "confidence":
            decision.get(
                "confidence"
            ),

        "question":
            effective_question,
    }


def prepare_voice_response(
    text: str,
    project: str = "t800",
):

    """
    Compatibilidade com os testes/legado.

    O runtime novo usa prepare_voice_route()
    + answer_stream().
    """

    plan = prepare_voice_route(
        text,
        project=project,
    )

    if (
        plan["route"]
        != "expert"
    ):

        return {
            "route":
                "chat",

            "reason":
                plan.get(
                    "reason"
                ),

            "confidence":
                plan.get(
                    "confidence"
                ),

            "answer":
                None,

            "sources":
                [],

            "error":
                None,
        }

    try:

        result = expert_answer(
            question=
                plan["question"],

            project=
                project,
        )

        return {
            "route":
                "expert",

            "reason":
                plan.get(
                    "reason"
                ),

            "confidence":
                plan.get(
                    "confidence"
                ),

            "answer":
                result.get(
                    "answer",
                    ""
                ),

            "sources":
                result.get(
                    "sources",
                    []
                ),

            "error":
                None,
        }

    except Exception as exc:

        return {
            "route":
                "expert",

            "reason":
                plan.get(
                    "reason"
                ),

            "confidence":
                plan.get(
                    "confidence"
                ),

            "answer":
                EXPERT_ERROR_MESSAGE,

            "sources":
                [],

            "error":
                repr(exc),
        }
''',
    encoding="utf-8",
)

print(
    "✅ Bridge separado em ROUTE / ANSWER."
)


# ============================================================
# ARKA.PY
# ============================================================

arka = ARKA.read_text(
    encoding="utf-8",
)


old_import = '''from app.core.voice_bridge import (
    prepare_voice_response,
    reset_voice_context,
)
'''

new_import = '''from app.core.voice_bridge import (
    prepare_voice_route,
    reset_voice_context,
)

from app.agents.expert import (
    answer_stream,
)
'''


if old_import not in arka:

    if "prepare_voice_route" not in arka:

        raise RuntimeError(
            "Import do voice_bridge não encontrado "
            "em arka.py"
        )

else:

    arka = arka.replace(
        old_import,
        new_import,
        1,
    )


process_start = arka.find(
    "def processar(texto: str):"
)

if process_start == -1:

    raise RuntimeError(
        "Não encontrei processar() "
        "em arka.py"
    )


txt_marker = (
    "\n\n# ============================================================\n"
    "# TXT\n"
    "# ============================================================"
)

process_end = arka.find(
    txt_marker,
    process_start,
)

if process_end == -1:

    raise RuntimeError(
        "Não encontrei o final de processar()."
    )


new_processar = r'''def processar(texto: str):

    inicio_rota = (
        time.perf_counter()
    )

    plano = prepare_voice_route(
        texto,
        project=PROJECT,
    )

    tempo_rota = (
        time.perf_counter()
        - inicio_rota
    )

    rota = plano[
        "route"
    ]

    print()
    print(
        "─" * 64
    )

    print(
        f"Rota: {rota.upper()} | "
        f"{plano.get('reason')} | "
        f"{tempo_rota:.3f}s"
    )

    print(
        "─" * 64
    )

    # ========================================================
    # CHAT
    # ========================================================

    if rota == "chat":

        return responder_chat(
            texto
        )

    # ========================================================
    # EXPERT STREAMING
    # ========================================================

    print()
    print(
        "Arka [EXPERT]> ",
        end="",
        flush=True,
    )

    def mostrar_token(
        token,
    ):

        print(
            token,
            end="",
            flush=True,
        )

    resultado = answer_stream(
        question=
            plano["question"],

        project=
            PROJECT,

        on_token=
            mostrar_token,
    )

    print()

    resposta = (
        resultado.get(
            "answer",
            ""
        )
    )

    fontes = (
        resultado.get(
            "sources"
        )
        or []
    )

    metricas = (
        resultado.get(
            "metrics"
        )
        or {}
    )

    print()

    retrieval = metricas.get(
        "retrieval"
    )

    first_token = metricas.get(
        "first_token"
    )

    total = metricas.get(
        "total"
    )

    partes = []

    if retrieval is not None:

        partes.append(
            f"retrieval={retrieval:.3f}s"
        )

    if first_token is not None:

        partes.append(
            f"1º token={first_token:.3f}s"
        )

    if total is not None:

        partes.append(
            f"total={total:.3f}s"
        )

    if partes:

        print(
            "⏱️ Expert: "
            + " | ".join(
                partes
            )
        )

    if fontes:

        print()
        print(
            "Fontes:"
        )

        vistos = set()

        for fonte in fontes:

            nome = (
                fonte.get(
                    "source"
                )
                or fonte.get(
                    "path"
                )
                or "fonte desconhecida"
            )

            if nome in vistos:
                continue

            vistos.add(
                nome
            )

            print(
                " -",
                nome,
            )

    # Histórico do chat normal.

    history.append(
        {
            "role":
                "user",

            "content":
                texto,
        }
    )

    history.append(
        {
            "role":
                "assistant",

            "content":
                resposta,
        }
    )

    if len(history) > 17:

        history[:] = (
            [history[0]]
            + history[-16:]
        )

    return resposta
'''


arka = (
    arka[:process_start]
    + new_processar
    + arka[process_end:]
)

ARKA.write_text(
    arka,
    encoding="utf-8",
)

print(
    "✅ arka.py agora usa EXPERT streaming."
)


# ============================================================
# BENCHMARK
# ============================================================

BENCHMARK.write_text(
r'''from app.agents.expert import (
    answer_stream,
)


QUESTIONS = [
    (
        "ROS2",
        "Como habilita os tópicos ROS2 do T800?"
    ),
    (
        "Diagnóstico",
        "Existe algum problema conhecido "
        "na integração do T800?"
    ),
]


for name, question in QUESTIONS:

    print()
    print(
        "=" * 64
    )

    print(
        name
    )

    print(
        question
    )

    print(
        "=" * 64
    )

    result = answer_stream(
        question,
        "t800",

        # Benchmark não imprime conteúdo.
        on_token=lambda token: None,
    )

    metrics = (
        result.get(
            "metrics",
            {}
        )
    )

    print(
        "Retrieval:",
        f"{metrics.get('retrieval', 0):.3f}s"
    )

    print(
        "Primeiro token:",
        (
            f"{metrics['first_token']:.3f}s"
            if metrics.get(
                "first_token"
            ) is not None
            else "---"
        )
    )

    print(
        "Total:",
        f"{metrics.get('total', 0):.3f}s"
    )

    print(
        "Fontes:",
        len(
            result.get(
                "sources",
                []
            )
        )
    )
''',
    encoding="utf-8",
)

print(
    "✅ benchmark_expert.py criado."
)


# ============================================================
# RAG-CHECK WRAPPER
# ============================================================

if not RAG_CHECK_CORE.exists():

    shutil.copy2(
        RAG_CHECK,
        RAG_CHECK_CORE,
    )

    os.chmod(
        RAG_CHECK_CORE,
        0o755,
    )


RAG_CHECK.write_text(
r'''#!/usr/bin/env bash

set -u

ROOT="$(
    cd "$(dirname "$0")"
    pwd
)"

cd "$ROOT"


echo
echo "============================================================"
echo " ARKA RAG CHECK + CREDENTIALS"
echo "============================================================"
echo


./rag-check-core "$@"

STATUS=$?

if [ "$STATUS" -ne 0 ]; then

    echo
    echo "❌ Core RAG falhou."
    exit "$STATUS"

fi


echo
echo "============================================================"
echo " TESTE DE CREDENCIAIS"
echo "============================================================"
echo


python -u test_credentials_rag.py

STATUS=$?

if [ "$STATUS" -ne 0 ]; then

    echo
    echo "❌ Credentials RAG falhou."
    exit "$STATUS"

fi


echo
echo "============================================================"
echo " RAG + CREDENTIALS: PASS"
echo "============================================================"
echo


exit 0
''',
    encoding="utf-8",
)

os.chmod(
    RAG_CHECK,
    0o755,
)

print(
    "✅ test_credentials_rag integrado "
    "ao rag-check."
)


# ============================================================
# SINTAXE
# ============================================================

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(EXPERT),
        str(BRIDGE),
        str(ARKA),
        str(BENCHMARK),
        str(SERVER / "test_credentials_rag.py"),
    ],
    check=True,
    cwd=SERVER,
)

print()
print(
    "✅ Sintaxe validada."
)

print()
print(
    "========================================"
)

print(
    " EXPERT V4 INSTALADO"
)

print(
    "========================================"
)

print()

print(
    "Backup:",
    backup,
)

print()
print(
    "Agora execute:"
)

print(
    "cd robot-server"
)

print(
    "python test_voice_bridge.py"
)

print(
    "./rag-check --tag critical"
)

print(
    "python benchmark_expert.py"
)
