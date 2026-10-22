from __future__ import annotations

import shutil
import subprocess
import sys

from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

VOICE = ROOT / "voice.py"

BRIDGE = (
    SERVER
    / "app"
    / "core"
    / "voice_bridge.py"
)

TEST_BRIDGE = (
    SERVER
    / "test_voice_bridge.py"
)

ARKA_CHECK = (
    SERVER
    / "arka-check"
)


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"voice_rag_integration_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    VOICE,
    BRIDGE,
    TEST_BRIDGE,
    ARKA_CHECK,
):

    if not path.exists():
        continue

    relative = path.relative_to(
        ROOT
    )

    destination = (
        backup
        / relative
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
# VOICE BRIDGE
# ============================================================

BRIDGE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

BRIDGE.write_text(
r'''from __future__ import annotations

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


def prepare_voice_response(
    text: str,
    project: str = "t800",
):
    """
    Decide quem deve responder.

    CHAT:
        apenas devolve a decisão.
        O voice.py mantém seu streaming original.

    EXPERT:
        consulta o RAG e devolve a resposta pronta.

    Importante:
        erro no RAG NÃO cai silenciosamente no
        chat geral.
    """

    decision = route_message(
        text
    )

    if (
        decision["route"]
        != "expert"
    ):

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

    try:

        result = expert_answer(
            question=text,
            project=project,
        )

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
    "✅ Criado:",
    BRIDGE,
)


# ============================================================
# TESTE DO BRIDGE
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

        bridge.expert_answer = (
            fake_expert
        )

        # ------------------------------------
        # CHAT não deve consultar RAG
        # ------------------------------------

        chat = (
            bridge
            .prepare_voice_response(
                "Quanto é 15 vezes 7?"
            )
        )

        check(
            chat["route"] == "chat",
            "Matemática caiu no Expert."
        )

        check(
            len(calls) == 0,
            "CHAT consultou ExpertAgent."
        )

        # ------------------------------------
        # EXPERT deve consultar RAG
        # ------------------------------------

        expert = (
            bridge
            .prepare_voice_response(
                "Como funciona o "
                "ROS2 bridge do T800?"
            )
        )

        check(
            expert["route"]
            == "expert",

            "T800 não caiu no Expert."
        )

        check(
            len(calls) == 1,
            "ExpertAgent não foi chamado."
        )

        check(
            expert["answer"]
            == "Resposta técnica de teste.",

            "Resposta do Expert foi perdida."
        )

        # ------------------------------------
        # ERRO NO RAG NÃO PODE VIRAR CHAT
        # ------------------------------------

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
                "Qual é a configuração "
                "do T800?"
            )
        )

        check(
            failed["route"]
            == "expert",

            "Falha técnica caiu no Chat."
        )

        check(
            failed["error"]
            is not None,

            "Erro do RAG não foi registrado."
        )

        print(
            "✅ CHAT → streaming normal"
        )

        print(
            "✅ EXPERT → RAG"
        )

        print(
            "✅ falha do RAG "
            "não cai no Chat"
        )

        print(
            "PASS: voice bridge"
        )

    finally:

        bridge.expert_answer = (
            original
        )


if __name__ == "__main__":
    main()
''',
    encoding="utf-8",
)

print(
    "✅ Criado:",
    TEST_BRIDGE,
)


# ============================================================
# PATCH DO VOICE.PY
# ============================================================

text = VOICE.read_text(
    encoding="utf-8",
)

SENTINEL = (
    "ARKA_RAG_VOICE_INTEGRATION_V1"
)

if SENTINEL in text:

    print(
        "ℹ️ voice.py já possui "
        "integração RAG. Patch ignorado."
    )

else:

    # --------------------------------------------------------
    # Imports
    # --------------------------------------------------------

    old = (
        "import os\n"
        "import json\n"
    )

    new = (
        "import os\n"
        "import sys\n"
        "import json\n"
    )

    if old not in text:

        raise RuntimeError(
            "Não consegui localizar "
            "os imports iniciais."
        )

    text = text.replace(
        old,
        new,
        1,
    )

    old = (
        "from collections import deque\n"
        "\n"
        "import numpy as np"
    )

    new = r'''from collections import deque
from pathlib import Path


# ============================================================
# ARKA CORE / ROBOT SERVER
# ARKA_RAG_VOICE_INTEGRATION_V1
# ============================================================

ARKA_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)

ROBOT_SERVER_DIR = (
    ARKA_ROOT
    / "robot-server"
)

if (
    str(ROBOT_SERVER_DIR)
    not in sys.path
):
    sys.path.insert(
        0,
        str(ROBOT_SERVER_DIR)
    )

from app.core.voice_bridge import (
    prepare_voice_response,
)


import numpy as np'''

    if old not in text:

        raise RuntimeError(
            "Não consegui localizar "
            "o bloco após deque."
        )

    text = text.replace(
        old,
        new,
        1,
    )

    # --------------------------------------------------------
    # Funções para resposta já pronta do RAG
    # --------------------------------------------------------

    anchor = r'''# ============================================================
# QWEN + TTS EM STREAMING
# ============================================================
'''

    helper = r'''
# ============================================================
# RESPOSTA EXPERT → TTS
# ============================================================

def limpar_texto_para_voz(
    texto
):

    # As citações continuam aparecendo
    # no terminal, mas não precisam ser
    # faladas pela Arka.

    texto = re.sub(
        r"\[Fonte\s+\d+\]",
        "",
        texto,
        flags=re.IGNORECASE
    )

    # Remove marcações Markdown que
    # ficam artificiais no TTS.

    texto = re.sub(
        r"`([^`]+)`",
        r"\1",
        texto
    )

    texto = re.sub(
        r"(?m)^\s*[-*•]\s*",
        "",
        texto
    )

    texto = re.sub(
        r"(?m)^\s*\d+[.)]\s*",
        "",
        texto
    )

    texto = re.sub(
        r"[*_#]+",
        "",
        texto
    )

    texto = re.sub(
        r"\n+",
        ". ",
        texto
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    )

    texto = re.sub(
        r"\.{2,}",
        ".",
        texto
    )

    return texto.strip()


def responder_resposta_pronta(
    texto_usuario,
    resposta,
    fontes,
    inicio_processamento,
    fim_processamento
):

    global history

    metricas = {

        "modo":
            "expert",

        "inicio_qwen":
            inicio_processamento,

        # O ExpertAgent atualmente não
        # expõe streaming. Portanto estes
        # tempos representam o instante em
        # que a resposta RAG ficou pronta.

        "primeiro_token":
            fim_processamento,

        "primeira_frase":
            fim_processamento,

        "fim_qwen":
            fim_processamento,

        "inicio_primeiro_tts":
            None,

        "primeiro_audio_tts":
            None,

        "primeira_reproducao":
            None,

        "fim_reproducao":
            None,

        "tts_sintese_primeiro":
            None,

        "tts_total":
            0.0,

        "audio_falado":
            0.0
    }

    print()
    print(
        "🤖 Arka [EXPERT]: ",
        end="",
        flush=True
    )

    print(
        resposta
    )

    if fontes:

        print()
        print(
            "📚 Fontes RAG:"
        )

        fontes_vistas = set()

        for fonte in fontes:

            nome = fonte.get(
                "source",
                "fonte desconhecida"
            )

            if nome in fontes_vistas:
                continue

            fontes_vistas.add(
                nome
            )

            print(
                f"   - {nome}"
            )

    texto_voz = (
        limpar_texto_para_voz(
            resposta
        )
    )

    frases = [
        parte.strip()

        for parte in re.split(
            r"(?<=[.!?])\s+",
            texto_voz
        )

        if parte.strip()
    ]

    if not frases and texto_voz:

        frases = [
            texto_voz
        ]

    with sd.OutputStream(
        samplerate=
            KOKORO_SAMPLE_RATE,

        channels=1,

        dtype="float32"
    ) as output_stream:

        primeira = True

        for frase in frases:

            dados_tts = falar_frase(
                frase,
                output_stream
            )

            metricas[
                "tts_total"
            ] += dados_tts[
                "tempo_total"
            ]

            metricas[
                "audio_falado"
            ] += dados_tts[
                "duracao_audio"
            ]

            if primeira:

                primeira = False

                metricas[
                    "inicio_primeiro_tts"
                ] = dados_tts[
                    "inicio_tts"
                ]

                metricas[
                    "primeiro_audio_tts"
                ] = dados_tts[
                    "primeiro_audio_pronto"
                ]

                metricas[
                    "primeira_reproducao"
                ] = dados_tts[
                    "primeira_reproducao"
                ]

                metricas[
                    "tts_sintese_primeiro"
                ] = dados_tts[
                    "tempo_primeiro_audio"
                ]

            metricas[
                "fim_reproducao"
            ] = dados_tts[
                "fim"
            ]

    # Mantemos a conversa visível para
    # turnos seguintes do modo chat.

    history.append(
        {
            "role":
                "user",

            "content":
                texto_usuario
        }
    )

    history.append(
        {
            "role":
                "assistant",

            "content":
                resposta
        }
    )

    if len(history) > 13:

        history = (
            [history[0]]
            + history[-12:]
        )

    return (
        resposta,
        metricas
    )


'''

    if anchor not in text:

        raise RuntimeError(
            "Não encontrei o início "
            "da seção QWEN + TTS."
        )

    text = text.replace(
        anchor,
        helper + anchor,
        1,
    )

    # --------------------------------------------------------
    # Router no início de responder()
    # --------------------------------------------------------

    old = r'''def responder(
    texto_usuario,
    metricas_audio,
    fim_stt
):

    global history

    inicio_qwen = agora()
'''

    new = r'''def responder(
    texto_usuario,
    metricas_audio,
    fim_stt
):

    global history

    # ========================================================
    # ROUTER
    # ========================================================

    inicio_router = agora()

    decisao = (
        prepare_voice_response(
            texto_usuario,
            project="t800"
        )
    )

    fim_router = agora()

    print()
    print(
        "🧭 Rota:",
        decisao["route"].upper(),
        "|",
        decisao.get(
            "reason"
        ),
        "|",
        f"{fim_router - inicio_router:.3f}s"
    )

    # ========================================================
    # EXPERT
    # ========================================================

    if (
        decisao["route"]
        == "expert"
    ):

        if decisao.get(
            "error"
        ):

            print(
                "⚠️ Erro interno "
                "do ExpertAgent:",
                decisao["error"]
            )

        return responder_resposta_pronta(
            texto_usuario=
                texto_usuario,

            resposta=
                decisao["answer"],

            fontes=
                decisao.get(
                    "sources",
                    []
                ),

            inicio_processamento=
                inicio_router,

            fim_processamento=
                fim_router
        )

    # ========================================================
    # CHAT
    #
    # Daqui para baixo o pipeline original continua
    # inalterado: Qwen streaming → fila → Kokoro.
    # ========================================================

    inicio_qwen = agora()
'''

    if old not in text:

        raise RuntimeError(
            "Não encontrei o início "
            "exato de responder()."
        )

    text = text.replace(
        old,
        new,
        1,
    )

    VOICE.write_text(
        text,
        encoding="utf-8",
    )

    print(
        "✅ voice.py integrado "
        "ao Router + ExpertAgent."
    )


# ============================================================
# PATCH ARKA-CHECK
# ============================================================

check = ARKA_CHECK.read_text(
    encoding="utf-8",
)

if "test_voice_bridge.py" not in check:

    # Converte os contadores 8 → 9.

    for index in range(
        1,
        9,
    ):

        check = check.replace(
            f"[{index}/8]",
            f"[{index}/9]"
        )

    # Inclui novos arquivos no py_compile.

    needle = (
        "        app/core/assistant.py \\\n"
    )

    replacement = (
        "        app/core/assistant.py \\\n"
        "        app/core/voice_bridge.py \\\n"
    )

    if needle in check:

        check = check.replace(
            needle,
            replacement,
            1,
        )

    needle = (
        "        test_router.py \\\n"
        "        test_rag.py"
    )

    replacement = (
        "        test_router.py \\\n"
        "        test_voice_bridge.py \\\n"
        "        test_rag.py"
    )

    if needle in check:

        check = check.replace(
            needle,
            replacement,
            1,
        )

    final_marker = r'''    echo
    echo "============================================================"
    echo " ARKA CHECK: PASS"
'''

    new_step = r'''    echo
    echo "[9/9] Voice → Router → Expert"

    python test_voice_bridge.py

    if [ $? -ne 0 ]; then
        echo "❌ Integração Voice/RAG"
        return 1
    fi

    echo "✅ Integração Voice/RAG"


'''

    if final_marker not in check:

        raise RuntimeError(
            "Não encontrei o final "
            "do arka-check."
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
        "✅ arka-check atualizado "
        "para 9 etapas."
    )

else:

    print(
        "ℹ️ arka-check já contém "
        "o teste Voice/RAG."
    )


# ============================================================
# VALIDAÇÃO DE SINTAXE
# ============================================================

files = [
    VOICE,
    BRIDGE,
    TEST_BRIDGE,
    SERVER / "app/core/router.py",
    SERVER / "app/agents/expert.py",
]

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        *[
            str(path)
            for path in files
        ],
    ],
    check=True,
    cwd=ROOT,
)

print()
print(
    "✅ Sintaxe validada."
)

print()
print(
    "Integração instalada."
)

print(
    "Backup:",
    backup,
)
