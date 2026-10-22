from pathlib import Path
from datetime import datetime
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

ARKA = SERVER / "arka.py"
RUN = SERVER / "arka-run"
CHECK = SERVER / "arka-check"
VOICE = ROOT / "voice.py"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_text_stt_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    ARKA,
    RUN,
    CHECK,
    VOICE,
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
# NOVA ARKA
# ============================================================

ARKA.write_text(
r'''from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from collections import deque

import numpy as np
import requests


from app.core.voice_bridge import (
    prepare_voice_response,
    reset_voice_context,
)

from app.core.voice_sanity import (
    analyze_transcription,
)


# ============================================================
# CONFIG
# ============================================================

OLLAMA_URL = (
    "http://127.0.0.1:11434/api/chat"
)

CHAT_MODEL = os.getenv(
    "ARKA_CHAT_MODEL",
    "qwen3:8b",
)

PROJECT = os.getenv(
    "ARKA_PROJECT",
    "t800",
)


SYSTEM_PROMPT = """
Você é Arka.

Responda sempre em português brasileiro.

Regras:
- Seja natural, objetiva e profissional.
- Não invente informações internas.
- Não diga que consultou documentação quando não consultou.
- Use o histórico da conversa.
- Não repita perguntas que o usuário acabou de responder.
- Quando a pergunta for genérica, responda normalmente.
- Informações técnicas internas são tratadas pelo ExpertAgent.
"""


# ============================================================
# CHAT HISTORY
# ============================================================

history = [
    {
        "role":
            "system",

        "content":
            SYSTEM_PROMPT,
    }
]


def agora():

    return time.perf_counter()


def limitar_history():

    global history

    if len(history) > 17:

        history = (
            [history[0]]
            + history[-16:]
        )


# ============================================================
# CHAT NORMAL
# ============================================================

def responder_chat(
    texto,
):

    global history

    if (
        "embedding"
        in CHAT_MODEL.lower()
        or "embed"
        in CHAT_MODEL.lower()
    ):

        raise RuntimeError(
            "ARKA_CHAT_MODEL aponta "
            "para modelo de embedding: "
            f"{CHAT_MODEL}"
        )

    mensagens = (
        history
        + [
            {
                "role":
                    "user",

                "content":
                    texto,
            }
        ]
    )

    resposta_completa = []

    print()
    print(
        "Arka> ",
        end="",
        flush=True,
    )

    with requests.post(
        OLLAMA_URL,

        json={
            "model":
                CHAT_MODEL,

            "messages":
                mensagens,

            "stream":
                True,

            "think":
                False,

            "keep_alive":
                "30m",

            "options": {
                "temperature":
                    0.3,

                "num_predict":
                    500,
            },
        },

        stream=True,
        timeout=(5, 180),

    ) as response:

        if not response.ok:

            print()
            print(
                "Erro Ollama:",
                response.status_code,
            )

            print(
                response.text
            )

            response.raise_for_status()

        for line in (
            response.iter_lines()
        ):

            if not line:
                continue

            data = json.loads(
                line
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

            resposta_completa.append(
                token
            )

            print(
                token,
                end="",
                flush=True,
            )

    print()

    resposta = "".join(
        resposta_completa
    ).strip()

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

    limitar_history()

    return resposta


# ============================================================
# ROUTER + EXPERT
# ============================================================

def processar(
    texto,
):

    global history

    inicio = agora()

    result = (
        prepare_voice_response(
            texto,
            project=PROJECT,
        )
    )

    tempo = (
        agora()
        - inicio
    )

    rota = result[
        "route"
    ]

    print()
    print(
        "─" * 60
    )

    print(
        "Rota:",
        rota.upper(),
        "|",
        result.get(
            "reason"
        ),
        "|",
        f"{tempo:.3f}s",
    )

    print(
        "─" * 60
    )

    if rota == "chat":

        return responder_chat(
            texto
        )

    resposta = (
        result.get(
            "answer"
        )
        or
        "Não encontrei essa informação "
        "na documentação disponível."
    )

    print()
    print(
        "Arka [EXPERT]>"
    )

    print(
        resposta
    )

    fontes = (
        result.get(
            "sources"
        )
        or []
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

    if result.get(
        "error"
    ):

        print()
        print(
            "Erro Expert:",
            result[
                "error"
            ],
        )

    # Coloca também no histórico do chat
    # para manter coerência caso o usuário
    # volte para conversa geral.

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

    limitar_history()

    return resposta


# ============================================================
# TXT
# ============================================================

def modo_txt():

    print()
    print(
        "=" * 60
    )

    print(
        "ARKA — MODO TXT"
    )

    print(
        "=" * 60
    )

    print(
        "Digite normalmente."
    )

    print(
        "/modo = voltar ao menu"
    )

    print(
        "/limpar = limpar contexto"
    )

    print(
        "/sair = encerrar"
    )

    while True:

        try:

            texto = input(
                "\nVocê> "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):

            print()
            return "menu"

        if not texto:
            continue

        comando = (
            texto
            .lower()
            .strip()
        )

        if comando in (
            "/modo",
            "/voltar",
        ):

            return "menu"

        if comando in (
            "/sair",
            "/exit",
            "/quit",
        ):

            return "exit"

        if comando == "/limpar":

            reset_voice_context()

            history[:] = [
                history[0]
            ]

            print(
                "Contexto limpo."
            )

            continue

        try:

            processar(
                texto
            )

        except Exception as exc:

            print()
            print(
                "ERRO:",
                repr(exc),
            )


# ============================================================
# STT
# ============================================================

SAMPLE_RATE = 16000
VAD_CHUNK = 512

VAD_THRESHOLD = float(
    os.getenv(
        "VAD_THRESHOLD",
        "0.55",
    )
)

SILENCE_TIME = float(
    os.getenv(
        "SILENCE_TIME",
        "0.65",
    )
)

MAX_RECORD_TIME = float(
    os.getenv(
        "MAX_RECORD_TIME",
        "15",
    )
)

WHISPER_MODEL = os.getenv(
    "WHISPER_MODEL",
    "small",
)

WHISPER_BEAM_SIZE = int(
    os.getenv(
        "WHISPER_BEAM_SIZE",
        "5",
    )
)


WHISPER_INITIAL_PROMPT = """
Conversa em português brasileiro.

Termos possíveis:
Arka, Arcanjo, T800, EngineAI,
Wi-Fi, ROS2, ros2_bridge, RC02,
SDK, dashboard, MuJoCo, Odin2,
Face Follow, câmera, gateway,
firmware e Raspberry Pi.
"""


whisper = None
whisper_device = None
vad_model = None


def carregar_stt():

    global whisper
    global whisper_device
    global vad_model

    if (
        whisper is not None
        and vad_model is not None
    ):

        return

    print()
    print(
        "Carregando STT..."
    )

    import torch

    from faster_whisper import (
        WhisperModel,
    )

    from silero_vad import (
        load_silero_vad,
    )

    try:

        import ctranslate2

        gpus = (
            ctranslate2
            .get_cuda_device_count()
        )

    except Exception:

        gpus = 0

    if gpus > 0:

        try:

            print(
                "Whisper:",
                WHISPER_MODEL,
                "| GPU NVIDIA"
            )

            whisper = WhisperModel(
                WHISPER_MODEL,
                device="cuda",
                compute_type="float16",
            )

            whisper_device = (
                "GPU NVIDIA"
            )

        except Exception as exc:

            print(
                "Falha GPU:",
                exc,
            )

            whisper = None

    if whisper is None:

        print(
            "Whisper:",
            WHISPER_MODEL,
            "| CPU"
        )

        whisper = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )

        whisper_device = "CPU"

    torch.set_num_threads(
        1
    )

    vad_model = (
        load_silero_vad()
    )

    print(
        "STT pronto."
    )


def ouvir():

    import sounddevice as sd
    import torch

    inicio_espera = agora()

    inicio_fala = None
    ultima_voz = None

    pre_buffer = deque(
        maxlen=12
    )

    gravacao = []

    falando = False
    silencio_frames = 0
    frames_fala = 0

    max_frames = int(
        MAX_RECORD_TIME
        * SAMPLE_RATE
        / VAD_CHUNK
    )

    limite_silencio = int(
        SILENCE_TIME
        * SAMPLE_RATE
        / VAD_CHUNK
    )

    if hasattr(
        vad_model,
        "reset_states",
    ):

        vad_model.reset_states()

    print()
    print(
        "🎤 Fale..."
    )

    with sd.InputStream(
        samplerate=
            SAMPLE_RATE,

        channels=1,

        dtype="float32",

        blocksize=
            VAD_CHUNK,

    ) as stream:

        while True:

            data, _ = stream.read(
                VAD_CHUNK
            )

            audio = (
                data[:, 0]
                .copy()
            )

            tensor = (
                torch.from_numpy(
                    audio
                )
            )

            prob = (
                vad_model(
                    tensor,
                    SAMPLE_RATE
                )
                .item()
            )

            momento = agora()

            if not falando:

                pre_buffer.append(
                    audio
                )

                if (
                    prob
                    >= VAD_THRESHOLD
                ):

                    falando = True
                    inicio_fala = momento
                    ultima_voz = momento

                    print(
                        "🟢 Detectado."
                    )

                    gravacao.extend(
                        pre_buffer
                    )

                    pre_buffer.clear()

            else:

                gravacao.append(
                    audio
                )

                frames_fala += 1

                if (
                    prob
                    >= VAD_THRESHOLD
                ):

                    silencio_frames = 0
                    ultima_voz = momento

                else:

                    silencio_frames += 1

                if (
                    silencio_frames
                    >= limite_silencio
                ):

                    break

                if (
                    frames_fala
                    >= max_frames
                ):

                    break

    if not gravacao:

        return (
            None,
            None,
        )

    fim = agora()

    audio_final = (
        np.concatenate(
            gravacao
        )
        .astype(
            np.float32
        )
    )

    metrics = {
        "inicio_espera":
            inicio_espera,

        "inicio_fala":
            inicio_fala,

        "ultima_voz":
            ultima_voz,

        "fim_captura":
            fim,

        "tempo_fala_ativa":
            (
                (
                    ultima_voz
                    - inicio_fala
                )

                if (
                    ultima_voz
                    and inicio_fala
                )

                else 0.0
            ),

        "duracao_audio":
            (
                len(
                    audio_final
                )
                / SAMPLE_RATE
            ),
    }

    return (
        audio_final,
        metrics,
    )


def transcrever(
    audio,
):

    segmentos, _ = (
        whisper.transcribe(
            audio,

            language="pt",

            beam_size=
                WHISPER_BEAM_SIZE,

            best_of=
                WHISPER_BEAM_SIZE,

            temperature=0,

            condition_on_previous_text=
                False,

            initial_prompt=
                WHISPER_INITIAL_PROMPT,

            without_timestamps=
                True,

            vad_filter=
                False,
        )
    )

    texto = "".join(
        segmento.text
        for segmento
        in segmentos
    ).strip()

    return texto


def modo_stt():

    carregar_stt()

    print()
    print(
        "=" * 60
    )

    print(
        "ARKA — MODO STT"
    )

    print(
        "=" * 60
    )

    print(
        "Você fala; a Arka responde "
        "SOMENTE em texto."
    )

    print(
        "CTRL+C = voltar ao menu"
    )

    while True:

        try:

            audio, metrics = (
                ouvir()
            )

            if audio is None:
                continue

            inicio = agora()

            texto = transcrever(
                audio
            )

            tempo = (
                agora()
                - inicio
            )

            print()
            print(
                "Você [STT]>",
                texto
            )

            print(
                "STT:",
                f"{tempo:.3f}s",
                "|",
                whisper_device,
            )

            if not texto:
                continue

            sanity = (
                analyze_transcription(
                    texto,
                    metrics,
                )
            )

            if sanity[
                "suspicious"
            ]:

                print(
                    "⚠️ Transcrição "
                    "descartada:",
                    sanity[
                        "reason"
                    ],
                )

                continue

            normalized = (
                texto
                .lower()
                .strip()
            )

            if normalized in (
                "voltar",
                "voltar ao menu",
                "mudar modo",
                "trocar modo",
            ):

                return "menu"

            if normalized in (
                "sair",
                "encerrar",
                "fechar arka",
            ):

                return "exit"

            processar(
                texto
            )

        except KeyboardInterrupt:

            print()
            print(
                "Voltando ao menu..."
            )

            return "menu"

        except Exception as exc:

            print()
            print(
                "ERRO STT:",
                repr(exc),
            )


# ============================================================
# MENU
# ============================================================

def escolher_modo():

    print()
    print(
        "=" * 60
    )

    print(
        " ARKA"
    )

    print(
        "=" * 60
    )

    print(
        "[1] TXT — digitar"
    )

    print(
        "[2] STT — falar no microfone"
    )

    print(
        "[0] Sair"
    )

    while True:

        opcao = input(
            "\nEscolha: "
        ).strip().lower()

        if opcao in (
            "1",
            "txt",
            "texto",
        ):

            return "txt"

        if opcao in (
            "2",
            "stt",
            "voz",
            "microfone",
        ):

            return "stt"

        if opcao in (
            "0",
            "sair",
            "exit",
        ):

            return "exit"

        print(
            "Opção inválida."
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=[
            "txt",
            "stt",
        ],
        default=None,
    )

    args = parser.parse_args()

    print()
    print(
        "Arka online."
    )

    print(
        "Modelo:",
        CHAT_MODEL
    )

    mode = args.mode

    while True:

        if mode is None:

            mode = escolher_modo()

        if mode == "exit":
            break

        if mode == "txt":

            result = modo_txt()

        elif mode == "stt":

            result = modo_stt()

        else:

            result = "menu"

        if result == "exit":
            break

        mode = None

    print()
    print(
        "Arka encerrada."
    )


if __name__ == "__main__":

    main()
''',
    encoding="utf-8",
)

print(
    "✅ Criado:",
    ARKA,
)


# ============================================================
# NOVO ARKA-RUN
# ============================================================

RUN.write_text(
r'''#!/usr/bin/env bash

set -u

ROOT="$(
    cd "$(dirname "$0")"
    pwd
)"

PROJECT_ROOT="$(
    cd "$ROOT/.."
    pwd
)"

cd "$ROOT"


# ============================================================
# VENV
# ============================================================

if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then

    source \
        "$PROJECT_ROOT/.venv/bin/activate"

elif [ -f "$ROOT/.venv/bin/activate" ]; then

    source \
        "$ROOT/.venv/bin/activate"

fi


# ============================================================
# CONFIG
# ============================================================

export ARKA_CHAT_MODEL="${
    ARKA_CHAT_MODEL:-qwen3:8b
}"

export WHISPER_MODEL="${
    WHISPER_MODEL:-small
}"


FULL=0
SKIP_CHECK=0
MODE=""


for arg in "$@"; do

    case "$arg" in

        --full)
            FULL=1
            ;;

        --skip-check)
            SKIP_CHECK=1
            ;;

        --txt)
            MODE="txt"
            ;;

        --stt)
            MODE="stt"
            ;;

    esac

done


mkdir -p \
    session_logs


STAMP="$(
    date +%Y-%m-%d_%H-%M-%S
)"

LOG="$ROOT/session_logs/arka_${STAMP}.log"


echo
echo "============================================================"
echo " ARKA START"
echo "============================================================"
echo


# ============================================================
# CHECK
# ============================================================

if [ "$SKIP_CHECK" -eq 0 ]; then

    echo "🔎 Verificando sistema..."

    if [ "$FULL" -eq 1 ]; then

        ./arka-check --full

    else

        ./arka-check

    fi

    STATUS=$?

    if [ "$STATUS" -ne 0 ]; then

        echo
        echo "❌ Health-check falhou."
        exit "$STATUS"

    fi

else

    echo "⚠️ Health-check ignorado."

fi


# ============================================================
# START
# ============================================================

echo
echo "🚀 Iniciando Arka..."
echo "📝 Log: $LOG"
echo


CMD=(
    python
    -u
    arka.py
)


if [ -n "$MODE" ]; then

    CMD+=(
        --mode
        "$MODE"
    )

fi


"${CMD[@]}" \
    2>&1 \
    | tee -a "$LOG"


STATUS=${PIPESTATUS[0]}


echo
echo "Arka finalizada."


exit "$STATUS"
''',
    encoding="utf-8",
)

os.chmod(
    RUN,
    0o755,
)

print(
    "✅ arka-run atualizado."
)


# ============================================================
# NOVO HEALTH CHECK
# ============================================================

CHECK.write_text(
r'''#!/usr/bin/env bash

set -u

ROOT="$(
    cd "$(dirname "$0")"
    pwd
)"

PROJECT_ROOT="$(
    cd "$ROOT/.."
    pwd
)"

cd "$ROOT"


if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then

    source \
        "$PROJECT_ROOT/.venv/bin/activate"

elif [ -f "$ROOT/.venv/bin/activate" ]; then

    source \
        "$ROOT/.venv/bin/activate"

fi


mkdir -p health_results

STAMP="$(
    date +%Y-%m-%d_%H-%M-%S
)"

LOG="health_results/arka_check_${STAMP}.log"


FULL=0

if [ "${1:-}" = "--full" ]; then

    FULL=1

fi


run_check() {

    echo
    echo "============================================================"
    echo " ARKA SYSTEM CHECK"
    echo "============================================================"
    echo


    # ========================================================
    # 1
    # ========================================================

    echo "[1/10] Python / sintaxe"

    python -m py_compile \
        arka.py \
        app/config.py \
        app/core/router.py \
        app/core/assistant.py \
        app/core/voice_bridge.py \
        app/core/voice_sanity.py \
        app/agents/expert.py \
        app/knowledge/embedder.py \
        app/knowledge/vector_store.py \
        ask.py \
        test_router.py \
        test_voice_bridge.py \
        test_voice_sanity.py \
        test_rag.py \
        || return 1

    echo "✅ Sintaxe"


    # ========================================================
    # 2
    # ========================================================

    echo
    echo "[2/10] Ollama"

    curl -sf \
        http://127.0.0.1:11434/api/tags \
        >/dev/null \
        || return 1

    echo "✅ Ollama"


    # ========================================================
    # 3
    # ========================================================

    echo
    echo "[3/10] Modelos + /api/chat"

    python - <<'PY'
import requests
import sys


tags = requests.get(
    "http://127.0.0.1:11434/api/tags",
    timeout=5,
)

tags.raise_for_status()

models = {
    item.get("name", "")
    for item
    in tags.json().get(
        "models",
        [],
    )
}


required = [
    "qwen3:8b",
    "qwen3-embedding:0.6b",
]


missing = [
    wanted

    for wanted
    in required

    if not any(
        model.startswith(
            wanted
        )
        for model
        in models
    )
]


print(
    "Modelos:"
)

for model in sorted(
    models
):

    print(
        " -",
        model,
    )


if missing:

    print(
        "Faltando:",
        missing,
    )

    sys.exit(1)


response = requests.post(
    "http://127.0.0.1:11434/api/chat",

    json={
        "model":
            "qwen3:8b",

        "stream":
            False,

        "think":
            False,

        "messages": [
            {
                "role":
                    "user",

                "content":
                    "Responda OK."
            }
        ],

        "options": {
            "temperature":
                0,

            "num_predict":
                3,
        },
    },

    timeout=120,
)


if not response.ok:

    print(
        response.status_code,
        response.text,
    )

    sys.exit(1)


print(
    "✅ qwen3:8b aceita /api/chat"
)
