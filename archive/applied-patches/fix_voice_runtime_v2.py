from __future__ import annotations

import json
import shutil
import subprocess
import sys

from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

VOICE = ROOT / "voice.py"

ROUTER = SERVER / "app/core/router.py"
BRIDGE = SERVER / "app/core/voice_bridge.py"
SANITY = SERVER / "app/core/voice_sanity.py"

ROUTER_TESTS = SERVER / "tests/router_cases.json"

TEST_BRIDGE = SERVER / "test_voice_bridge.py"
TEST_SANITY = SERVER / "test_voice_sanity.py"

ARKA_CHECK = SERVER / "arka-check"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"voice_runtime_v2_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    VOICE,
    ROUTER,
    BRIDGE,
    SANITY,
    TEST_BRIDGE,
    TEST_SANITY,
    ARKA_CHECK,
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
# ROUTER V2
# ============================================================

ROUTER.write_text(
r'''from __future__ import annotations

import re
import unicodedata


STRONG_EXPERT_TERMS = {
    "t800",
    "engineai",
    "ros2",
    "ros 2",
    "ros2_bridge",
    "rc02",
    "mujoco",
    "odin2",
    "face follow",
    "headfollow",
    "head follow",
    "gateway de visao",
}


PROJECT_TECH_TERMS = {
    "sdk",
    "dashboard",
    "telemetria",
    "websocket",
    "lidar",
    "camera",
    "speech",
    "audio",
    "motor",
    "articulacao",
    "joint",
    "pescoco",
    "neck",
    "bateria",
    "firmware",
    "driver",
    "parametro",
    "yaml",
    "docker",
    "dockerfile",
}


DOCUMENT_TERMS = {
    "documentacao",
    "manual",
    "arquivo",
    "arquivos",
    "relatorio",
    "fonte",
    "codigo",
    "configuracao",
}


CHAT_PATTERNS = (
    r"^(oi|ola|bom dia|boa tarde|boa noite)\b",
    r"^como voce esta",
    r"^tudo bem",
    r"^obrigad",
    r"^valeu",
)


# "800" sozinho NÃO basta.
#
# Queremos:
#   senha da internet do 800  -> EXPERT
#
# Mas:
#   quanto é 800 / 2?        -> CHAT

T800_ALIAS_CONTEXT = {
    "robo",
    "robot",
    "senha",
    "wifi",
    "wi-fi",
    "internet",
    "rede",
    "sdk",
    "ros2",
    "bridge",
    "driver",
    "camera",
    "motor",
    "bateria",
    "dashboard",
    "gateway",
    "firmware",
    "manual",
    "arquivo",
    "configuracao",
}


def normalize(text: str) -> str:

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

    return value.lower().strip()


def has_t800_alias_context(
    q: str,
) -> bool:

    # Whisper pode produzir:
    # T800
    # T 800
    # T-800
    # 800

    has_alias = bool(
        re.search(
            r"\b(?:t[\s-]*800|800)\b",
            q,
        )
    )

    if not has_alias:
        return False

    # T800 explícito é sempre forte.

    if re.search(
        r"\bt[\s-]*800\b",
        q,
    ):

        return True

    # "800" puro precisa de contexto técnico.

    return any(
        term in q
        for term
        in T800_ALIAS_CONTEXT
    )


def heuristic_route(
    text: str,
):

    q = normalize(
        text
    )

    # --------------------------------------------------------
    # Social explícito
    # --------------------------------------------------------

    for pattern in CHAT_PATTERNS:

        if re.search(
            pattern,
            q,
        ):

            if not any(
                normalize(term) in q
                for term
                in STRONG_EXPERT_TERMS
            ):

                return {
                    "route":
                        "chat",

                    "reason":
                        "social_heuristic",

                    "confidence":
                        1.0,
                }

    # --------------------------------------------------------
    # T800 pronunciado/transcrito de maneiras diferentes
    # --------------------------------------------------------

    if has_t800_alias_context(q):

        return {
            "route":
                "expert",

            "reason":
                "t800_alias_context",

            "confidence":
                1.0,
        }

    # --------------------------------------------------------
    # Termos fortes
    # --------------------------------------------------------

    strong = [
        term
        for term
        in STRONG_EXPERT_TERMS

        if normalize(term) in q
    ]

    if strong:

        return {
            "route":
                "expert",

            "reason":
                "strong_project_term:"
                + ",".join(
                    strong[:3]
                ),

            "confidence":
                1.0,
        }

    # --------------------------------------------------------
    # Combinação de termos internos
    # --------------------------------------------------------

    tech_matches = sum(
        1
        for term
        in PROJECT_TECH_TERMS

        if normalize(term) in q
    )

    doc_matches = sum(
        1
        for term
        in DOCUMENT_TERMS

        if normalize(term) in q
    )

    if (
        tech_matches >= 2
        or (
            tech_matches >= 1
            and doc_matches >= 1
        )
    ):

        return {
            "route":
                "expert",

            "reason":
                "technical_heuristic",

            "confidence":
                0.95,
        }

    return None


def route_message(
    text: str,
):

    result = heuristic_route(
        text
    )

    if result:
        return result

    # Segurança do roteamento:
    # dúvida = chat.
    #
    # Assim conhecimento genérico nunca vai
    # parar acidentalmente no RAG do T800.

    return {
        "route":
            "chat",

        "reason":
            "conservative_default",

        "confidence":
            0.99,
    }
''',
    encoding="utf-8",
)

print(
    "✅ Router V2."
)


# ============================================================
# FILTRO DE TRANSCRIÇÃO
# ============================================================

SANITY.write_text(
r'''from __future__ import annotations

import re
import unicodedata
from collections import Counter


def normalize(
    text: str,
) -> str:

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

    return value.lower()


def analyze_transcription(
    text: str,
    audio_metrics=None,
):

    audio_metrics = (
        audio_metrics
        or {}
    )

    normalized = normalize(
        text
    )

    tokens = re.findall(
        r"[a-z0-9]+",
        normalized,
    )

    active_time = float(
        audio_metrics.get(
            "tempo_fala_ativa"
        )
        or 0.0
    )

    # --------------------------------------------------------
    # Quase nenhum áudio + texto enorme
    # --------------------------------------------------------

    if (
        active_time > 0
        and active_time < 0.20
        and len(tokens) >= 8
    ):

        return {
            "suspicious":
                True,

            "reason":
                "texto incompatível "
                "com duração da fala",
        }

    # --------------------------------------------------------
    # Texto absurdo para áudio curto
    # --------------------------------------------------------

    if (
        active_time > 0
        and active_time < 1.0
        and len(tokens) >= 35
    ):

        return {
            "suspicious":
                True,

            "reason":
                "transcrição longa demais "
                "para áudio curto",
        }

    # --------------------------------------------------------
    # Loop de palavras
    # --------------------------------------------------------

    if len(tokens) >= 20:

        unique_ratio = (
            len(set(tokens))
            / len(tokens)
        )

        if unique_ratio < 0.22:

            return {
                "suspicious":
                    True,

                "reason":
                    "repetição excessiva "
                    "de palavras",
            }

        # Detecta repetição de pares/trincas.

        for size in (
            2,
            3,
            4,
        ):

            grams = [
                tuple(
                    tokens[
                        index:
                        index + size
                    ]
                )

                for index in range(
                    len(tokens)
                    - size
                    + 1
                )
            ]

            if not grams:
                continue

            _, frequency = (
                Counter(grams)
                .most_common(1)[0]
            )

            if frequency >= 6:

                return {
                    "suspicious":
                        True,

                    "reason":
                        "loop repetitivo "
                        "detectado",
                }

    return {
        "suspicious":
            False,

        "reason":
            None,
    }
''',
    encoding="utf-8",
)

print(
    "✅ Filtro anti-alucinação."
)


# ============================================================
# VOICE BRIDGE COM FOLLOW-UP
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

    return value.lower().strip()


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


def prepare_voice_response(
    text: str,
    project: str = "t800",
):

    global _last_route
    global _expert_context

    decision = route_message(
        text
    )

    effective_question = (
        text
    )

    # ========================================================
    # FOLLOW-UP DE UMA PERGUNTA TÉCNICA
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

            "answer":
                None,

            "sources":
                [],

            "error":
                None,
        }

    # Ajuda o RAG quando o Whisper entende
    # "800" em vez de "T800".

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

    # ========================================================
    # EXPERT
    # ========================================================

    try:

        result = expert_answer(
            question=
                effective_question,

            project=
                project,
        )

        _last_route = "expert"

        # Mantém contexto suficiente para
        # perguntas como:
        #
        # "e qual arquivo faz isso?"

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

        _last_route = "expert"

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
    "✅ Voice bridge com contexto."
)


# ============================================================
# TESTES DO ROUTER
# ============================================================

tests = json.loads(
    ROUTER_TESTS.read_text(
        encoding="utf-8"
    )
)

extra = [
    {
        "text":
            "Qual a senha da internet do 800?",

        "expected":
            "expert",
    },
    {
        "text":
            "Qual a configuração do T 800?",

        "expected":
            "expert",
    },
    {
        "text":
            "Quanto é 800 dividido por 2?",

        "expected":
            "chat",
    },
    {
        "text":
            "Tenho 800 reais, quanto sobra se gastar 200?",

        "expected":
            "chat",
    },
]

existing = {
    item["text"]
    for item in tests
}

for item in extra:

    if item["text"] not in existing:
        tests.append(
            item
        )

ROUTER_TESTS.write_text(
    json.dumps(
        tests,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print(
    f"✅ Router tests: {len(tests)}."
)


# ============================================================
# TEST VOICE SANITY
# ============================================================

TEST_SANITY.write_text(
r'''from app.core.voice_sanity import (
    analyze_transcription,
)


def check(
    condition,
    message,
):

    if not condition:
        raise AssertionError(
            message
        )


def main():

    hallucination = (
        (
            "O que é que "
            * 80
        ).strip()
    )

    result = analyze_transcription(
        hallucination,

        {
            "tempo_fala_ativa":
                0.128
        },
    )

    check(
        result["suspicious"],
        "Loop do Whisper não foi detectado."
    )

    result = analyze_transcription(
        "Oi!",

        {
            "tempo_fala_ativa":
                0.256
        },
    )

    check(
        not result["suspicious"],
        "Oi foi bloqueado."
    )

    result = analyze_transcription(
        "Qual a senha da internet do 800?",

        {
            "tempo_fala_ativa":
                2.347
        },
    )

    check(
        not result["suspicious"],
        "Pergunta normal foi bloqueada."
    )

    print(
        "✅ loop do Whisper detectado"
    )

    print(
        "✅ fala curta preservada"
    )

    print(
        "✅ pergunta normal preservada"
    )

    print(
        "PASS: voice sanity"
    )


if __name__ == "__main__":
    main()
''',
    encoding="utf-8",
)


# ============================================================
# TEST BRIDGE
# ============================================================

TEST_BRIDGE.write_text(
r'''import app.core.voice_bridge as bridge


def check(
    condition,
    message,
):

    if not condition:
        raise AssertionError(
            message
        )


def main():

    original = (
        bridge.expert_answer
    )

    calls = []

    def fake_expert(
        question,
        project,
    ):

        calls.append(
            (
                question,
                project,
            )
        )

        return {
            "answer":
                "Resposta técnica de teste.",

            "sources": [
                {
                    "source":
                        "teste.txt"
                }
            ],
        }

    try:

        bridge.reset_voice_context()

        bridge.expert_answer = (
            fake_expert
        )

        # CHAT genérico

        chat = (
            bridge
            .prepare_voice_response(
                "Quanto é 15 vezes 7?"
            )
        )

        check(
            chat["route"]
            == "chat",

            "Matemática caiu no Expert."
        )

        check(
            len(calls) == 0,
            "CHAT consultou RAG."
        )

        # "800" + contexto técnico

        alias = (
            bridge
            .prepare_voice_response(
                "Qual a senha da "
                "internet do 800?"
            )
        )

        check(
            alias["route"]
            == "expert",

            "Alias 800 não caiu "
            "no Expert."
        )

        check(
            len(calls) == 1,
            "Alias 800 não consultou RAG."
        )

        # Follow-up técnico

        follow = (
            bridge
            .prepare_voice_response(
                "E qual arquivo "
                "configura isso?"
            )
        )

        check(
            follow["route"]
            == "expert",

            "Follow-up técnico "
            "perdeu contexto."
        )

        check(
            len(calls) == 2,
            "Follow-up não consultou RAG."
        )

        check(
            "Contexto da pergunta"
            in calls[-1][0],

            "Contexto técnico não "
            "foi enviado ao RAG."
        )

        # Volta ao chat

        normal = (
            bridge
            .prepare_voice_response(
                "Obrigado!"
            )
        )

        check(
            normal["route"]
            == "chat",

            "Obrigado ficou preso "
            "no Expert."
        )

        # Erro RAG não vira chat

        bridge.reset_voice_context()

        def broken_expert(
            question,
            project,
        ):

            raise RuntimeError(
                "falha simulada"
            )

        bridge.expert_answer = (
            broken_expert
        )

        failed = (
            bridge
            .prepare_voice_response(
                "Como funciona o "
                "ROS2 bridge do T800?"
            )
        )

        check(
            failed["route"]
            == "expert",

            "Falha Expert caiu "
            "no Chat."
        )

        check(
            failed["error"]
            is not None,

            "Erro não foi registrado."
        )

        print(
            "✅ CHAT normal"
        )

        print(
            "✅ alias 800 → EXPERT"
        )

        print(
            "✅ follow-up técnico"
        )

        print(
            "✅ saída do modo expert"
        )

        print(
            "✅ falha RAG protegida"
        )

        print(
            "PASS: voice bridge"
        )

    finally:

        bridge.expert_answer = (
            original
        )

        bridge.reset_voice_context()


if __name__ == "__main__":
    main()
''',
    encoding="utf-8",
)


# ============================================================
# PATCH VOICE.PY
# ============================================================

voice = VOICE.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Import do filtro
# ------------------------------------------------------------

old = '''from app.core.voice_bridge import (
    prepare_voice_response,
)
'''

new = '''from app.core.voice_bridge import (
    prepare_voice_response,
)

from app.core.voice_sanity import (
    analyze_transcription,
)
'''

if (
    "analyze_transcription"
    not in voice
):

    if old not in voice:

        raise RuntimeError(
            "Import voice_bridge "
            "não encontrado."
        )

    voice = voice.replace(
        old,
        new,
        1,
    )


# ------------------------------------------------------------
# Corrige VAD:
#
# MAX_RECORD_TIME passa a contar DEPOIS que
# a fala começa.
# ------------------------------------------------------------

if "frames_total = 0" in voice:

    voice = voice.replace(
        "        frames_total = 0",
        "        frames_fala = 0",
        1,
    )

if "while frames_total < max_frames:" in voice:

    voice = voice.replace(
        "        while frames_total < max_frames:",
        "        while True:",
        1,
    )

old = '''            frames_total += 1
'''

new = '''            if falando:

                frames_fala += 1

                if (
                    frames_fala
                    >= max_frames
                ):

                    print(
                        "⚠️ Limite máximo "
                        "de fala atingido."
                    )

                    break
'''

if old in voice:

    voice = voice.replace(
        old,
        new,
        1,
    )


# ------------------------------------------------------------
# Filtra transcrição antes do Router
# ------------------------------------------------------------

sentinel = (
    "Transcrição descartada "
    "por possível alucinação"
)

if sentinel not in voice:

    old = '''        if not texto:
            print(
                "⚠️ Não entendi a fala."
            )
            continue

        # --------------------------------
        # 3. QWEN + TTS
'''

    new = '''        if not texto:
            print(
                "⚠️ Não entendi a fala."
            )
            continue

        analise_transcricao = (
            analyze_transcription(
                texto,
                metricas_audio
            )
        )

        if analise_transcricao[
            "suspicious"
        ]:

            print()
            print(
                "⚠️ Transcrição descartada "
                "por possível alucinação "
                "do Whisper."
            )

            print(
                "   Motivo:",
                analise_transcricao[
                    "reason"
                ]
            )

            continue

        # --------------------------------
        # 3. ROUTER + RESPOSTA + TTS
'''

    if old not in voice:

        raise RuntimeError(
            "Ponto pós-STT "
            "não encontrado."
        )

    voice = voice.replace(
        old,
        new,
        1,
    )


# ------------------------------------------------------------
# Melhora comportamento conversacional
# ------------------------------------------------------------

prompt_marker = (
    "- Faça perguntas quando precisar "
    "de alguma informação.\n"
)

prompt_extra = '''- Faça perguntas quando precisar de alguma informação.
- Nunca repita uma pergunta que o visitante acabou de responder.
- Interprete respostas curtas usando o contexto da conversa anterior.
- Não peça o nome da pessoa como resposta genérica ou fallback.
- Só pergunte o nome quando ele realmente for necessário para atender uma visita, contato ou identificação.
'''

if (
    "Nunca repita uma pergunta"
    not in voice
):

    if prompt_marker not in voice:

        raise RuntimeError(
            "Regra do SYSTEM_PROMPT "
            "não encontrada."
        )

    voice = voice.replace(
        prompt_marker,
        prompt_extra,
        1,
    )


VOICE.write_text(
    voice,
    encoding="utf-8",
)

print(
    "✅ voice.py corrigido."
)


# ============================================================
# ARKA CHECK → 10 ETAPAS
# ============================================================

check = ARKA_CHECK.read_text(
    encoding="utf-8"
)

if "test_voice_sanity.py" not in check:

    check = check.replace(
        "/9]",
        "/10]"
    )

    needle = (
        "        app/core/voice_bridge.py \\\n"
    )

    replacement = (
        "        app/core/voice_bridge.py \\\n"
        "        app/core/voice_sanity.py \\\n"
    )

    if needle in check:

        check = check.replace(
            needle,
            replacement,
            1,
        )

    needle = (
        "        test_voice_bridge.py \\\n"
        "        test_rag.py"
    )

    replacement = (
        "        test_voice_bridge.py \\\n"
        "        test_voice_sanity.py \\\n"
        "        test_rag.py"
    )

    if needle in check:

        check = check.replace(
            needle,
            replacement,
            1,
        )

    final_marker = '''    echo
    echo "============================================================"
    echo " ARKA CHECK: PASS"
'''

    new_step = '''    echo
    echo "[10/10] Voice sanity / Whisper"

    python test_voice_sanity.py

    if [ $? -ne 0 ]; then
        echo "❌ Voice sanity"
        return 1
    fi

    echo "✅ Voice sanity"


'''

    if final_marker not in check:

        raise RuntimeError(
            "Final do arka-check "
            "não encontrado."
        )

    check = check.replace(
        final_marker,
        new_step + final_marker,
        1,
    )

    ARKA_CHECK.write_text(
        check,
        encoding="utf-8",
    )

    print(
        "✅ arka-check → 10 etapas."
    )


# ============================================================
# COMPILA
# ============================================================

compile_files = [
    VOICE,
    ROUTER,
    BRIDGE,
    SANITY,
    TEST_BRIDGE,
    TEST_SANITY,
]

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        *[
            str(path)
            for path in compile_files
        ],
    ],
    cwd=ROOT,
    check=True,
)

print()
print(
    "✅ Voice Runtime V2 instalado."
)

print(
    "Backup:",
    backup,
)
