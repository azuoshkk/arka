import os
import sys
import json
import re
import time
import queue
import threading
from collections import deque
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

from app.core.voice_sanity import (
    analyze_transcription,
)


import numpy as np
import requests
import sounddevice as sd
import torch

from faster_whisper import WhisperModel
from silero_vad import load_silero_vad
from kokoro import KPipeline


# ============================================================
# CONFIGURAÇÕES
# ============================================================

SAMPLE_RATE = 16000
VAD_CHUNK = 512

VAD_THRESHOLD = 0.55

# Quanto silêncio indica que a pessoa terminou de falar.
# Depois podemos reduzir para ~0.45 para ficar ainda mais rápido.
SILENCE_TIME = 0.65

MAX_RECORD_TIME = 15

# Pode ser alterado sem editar o arquivo:
#
# WHISPER_MODEL=small ./robot-server/arka-run --skip-check
#
WHISPER_MODEL = os.getenv(
    "WHISPER_MODEL",
    "base"
)

WHISPER_BEAM_SIZE = int(
    os.getenv(
        "WHISPER_BEAM_SIZE",
        "5"
    )
)

WHISPER_INITIAL_PROMPT = """
Conversa em português brasileiro.

Possíveis termos técnicos:
Arka, T800, EngineAI, Wi-Fi, internet,
ROS2, ros2_bridge, RC02, SDK, dashboard,
MuJoCo, Odin2, Face Follow, câmera,
gateway, firmware, Raspberry Pi.
"""

KOKORO_VOICE = "pf_dora"
KOKORO_SPEED = 1.05
KOKORO_SAMPLE_RATE = 24000

OLLAMA_URL = "http://localhost:11434/api/chat"


SYSTEM_PROMPT = """
Você é Arka, uma robô recepcionista.

Seu nome é Arka, inspirado em Arcanjo.

Você está fisicamente presente na recepção de uma empresa
e conversa verbalmente com visitantes.

REGRAS:

- Fale sempre em português brasileiro.
- Seja simpática, natural e profissional.
- Responda de maneira curta.
- Normalmente responda com uma ou duas frases.
- Não use markdown.
- Não use listas.
- Não use emojis.
- Não diga que é uma inteligência artificial.
- Não invente informações sobre a empresa.
- Quando não souber alguma informação, diga que pode verificar.
- Faça perguntas quando precisar de alguma informação.
- Nunca repita uma pergunta que o visitante acabou de responder.
- Interprete respostas curtas usando o contexto da conversa anterior.
- Não peça o nome da pessoa como resposta genérica ou fallback.
- Só pergunte o nome quando ele realmente for necessário para atender uma visita, contato ou identificação.
- Lembre que suas respostas serão faladas em voz alta.

Exemplos:

Visitante: Bom dia.
Arka: Bom dia! Seja bem-vindo. Como posso ajudar?

Visitante: Vim falar com Guilherme.
Arka: Claro. Qual é o seu nome?

Visitante: Onde fica o financeiro?
Arka: Posso verificar isso para você.
"""


# ============================================================
# UTILIDADES
# ============================================================

def agora():
    return time.perf_counter()


def linha():
    print("=" * 58)


def mostrar_tempo(nome, valor):
    if valor is None:
        print(f"{nome:<38} ---")
    else:
        print(f"{nome:<38} {valor:.3f}s")


# ============================================================
# DESCOBRIR MODELO DO OLLAMA
# ============================================================

def modelo_serve_para_chat(
    nome
):

    if not nome:
        return False

    lower = nome.lower()

    # Modelos de embedding nunca podem
    # ser enviados para /api/chat.

    if (
        "embedding" in lower
        or "embed" in lower
    ):
        return False

    return True


def escolher_modelo_chat(
    modelos
):

    nomes = []

    for modelo in modelos:

        nome = (
            modelo.get("name")
            or modelo.get("model")
            or ""
        )

        if (
            modelo_serve_para_chat(
                nome
            )
        ):

            nomes.append(
                nome
            )

    if not nomes:
        return None

    # Modelo principal da Arka.

    preferido = os.getenv(
        "ARKA_CHAT_MODEL",
        "qwen3:8b"
    )

    for nome in nomes:

        if nome == preferido:
            return nome

    for nome in nomes:

        if nome.startswith(
            preferido
        ):
            return nome

    # Segunda preferência:
    # qualquer qwen3:8b.

    for nome in nomes:

        if (
            "qwen3:8b"
            in nome.lower()
        ):

            return nome

    # Depois qualquer Qwen que não seja
    # embedding.

    for nome in nomes:

        if "qwen" in nome.lower():
            return nome

    # Último fallback:
    # qualquer modelo que sirva para chat.

    return nomes[0]


def descobrir_modelo_ollama():

    modelo_env = os.getenv(
        "OLLAMA_MODEL"
    )

    if modelo_env:

        if not modelo_serve_para_chat(
            modelo_env
        ):

            raise RuntimeError(
                "OLLAMA_MODEL aponta para "
                "um modelo de embedding: "
                f"{modelo_env}"
            )

        return modelo_env

    # --------------------------------------------------------
    # 1. Verifica modelos carregados
    # --------------------------------------------------------

    try:

        response = requests.get(
            "http://localhost:11434/api/ps",
            timeout=3
        )

        response.raise_for_status()

        modelo = escolher_modelo_chat(
            response.json().get(
                "models",
                []
            )
        )

        if modelo:
            return modelo

    except Exception:
        pass

    # --------------------------------------------------------
    # 2. Verifica modelos instalados
    # --------------------------------------------------------

    try:

        response = requests.get(
            "http://localhost:11434/api/tags",
            timeout=3
        )

        response.raise_for_status()

        modelo = escolher_modelo_chat(
            response.json().get(
                "models",
                []
            )
        )

        if modelo:
            return modelo

    except Exception:
        pass

    raise RuntimeError(
        "Não encontrei modelo de chat "
        "válido no Ollama."
    )


print()
print("🔎 Procurando modelo do Ollama...")

inicio = agora()

OLLAMA_MODEL = descobrir_modelo_ollama()

tempo_ollama = agora() - inicio

print(
    f"✅ Modelo encontrado: {OLLAMA_MODEL}"
)

print(
    f"   Tempo: {tempo_ollama:.3f}s"
)


# ============================================================
# WHISPER
# ============================================================

whisper = None
whisper_device = None


def criar_whisper_cpu():

    global whisper
    global whisper_device

    print(
        "🔄 Carregando Whisper em CPU..."
    )

    inicio = agora()

    whisper = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8"
    )

    whisper_device = "CPU"

    tempo = agora() - inicio

    print(
        f"✅ Whisper CPU carregado em "
        f"{tempo:.3f}s"
    )

    return tempo


def carregar_whisper():

    global whisper
    global whisper_device

    print()
    print("🎧 Carregando Whisper...")

    inicio_total = agora()

    try:

        import ctranslate2

        quantidade_gpus = (
            ctranslate2.get_cuda_device_count()
        )

    except Exception:

        quantidade_gpus = 0

    if quantidade_gpus > 0:

        try:

            print(
                "🚀 NVIDIA encontrada. "
                "Testando Whisper na GPU..."
            )

            inicio_gpu = agora()

            modelo_gpu = WhisperModel(
                WHISPER_MODEL,
                device="cuda",
                compute_type="float16"
            )

            # IMPORTANTE:
            # WhisperModel pode ser criado mesmo se
            # libcublas estiver faltando.
            #
            # Então fazemos uma inferência curtíssima
            # para confirmar se a GPU realmente funciona.

            audio_teste = np.zeros(
                SAMPLE_RATE // 2,
                dtype=np.float32
            )

            segmentos, _ = (
                modelo_gpu.transcribe(
                    audio_teste,
                    language="pt",
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    condition_on_previous_text=False,
                    without_timestamps=True
                )
            )

            # força execução real do modelo
            list(segmentos)

            whisper = modelo_gpu
            whisper_device = "GPU NVIDIA"

            tempo = agora() - inicio_gpu

            print(
                f"✅ Whisper GPU funcionando."
            )

            print(
                f"   Inicialização + teste: "
                f"{tempo:.3f}s"
            )

        except Exception as erro:

            print()
            print(
                "⚠️ Whisper não conseguiu usar "
                "a GPU."
            )

            print(
                f"   Motivo: {erro}"
            )

            print(
                "   Usando CPU automaticamente."
            )

            criar_whisper_cpu()

    else:

        print(
            "ℹ️ CTranslate2 não encontrou "
            "GPU utilizável."
        )

        criar_whisper_cpu()

    return agora() - inicio_total


tempo_load_whisper = carregar_whisper()


# ============================================================
# SILERO VAD
# ============================================================

print()
print(
    "👂 Carregando detector de fala..."
)

inicio = agora()

torch.set_num_threads(1)

vad_model = load_silero_vad()

tempo_load_vad = agora() - inicio

print(
    f"✅ VAD carregado em "
    f"{tempo_load_vad:.3f}s"
)


# ============================================================
# KOKORO
# ============================================================

print()
print(
    "🔊 Carregando voz da Arka..."
)

inicio = agora()

# Deixamos Kokoro na CPU inicialmente.
# Isso evita competir com Ollama/Whisper pela GPU.
tts = KPipeline(
    lang_code="p",
    repo_id="hexgrad/Kokoro-82M",
    device="cpu"
)

tempo_load_tts = agora() - inicio

print(
    f"✅ Kokoro carregado em "
    f"{tempo_load_tts:.3f}s"
)


# ============================================================
# HISTÓRICO DA CONVERSA
# ============================================================

history = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]


# ============================================================
# CAPTURA DE VOZ + VAD
# ============================================================

def ouvir():

    inicio_espera = agora()

    inicio_fala = None
    ultima_voz = None

    pre_buffer = deque(
        maxlen=12
    )

    gravacao = []

    falando = False

    silencio_frames = 0

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
        "reset_states"
    ):
        vad_model.reset_states()

    print()
    print(
        "🎤 Aguardando você falar..."
    )

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=VAD_CHUNK
    ) as stream:

        frames_fala = 0

        while True:

            data, overflow = stream.read(
                VAD_CHUNK
            )

            audio = (
                data[:, 0]
                .copy()
            )

            tensor = torch.from_numpy(
                audio
            )

            probabilidade = (
                vad_model(
                    tensor,
                    SAMPLE_RATE
                )
                .item()
            )

            momento = agora()

            # -------------------------------
            # ainda esperando pessoa falar
            # -------------------------------

            if not falando:

                pre_buffer.append(
                    audio
                )

                if (
                    probabilidade
                    >= VAD_THRESHOLD
                ):

                    falando = True

                    inicio_fala = momento
                    ultima_voz = momento

                    print(
                        "🟢 Fala detectada."
                    )

                    gravacao.extend(
                        pre_buffer
                    )

                    pre_buffer.clear()

            # -------------------------------
            # pessoa já começou
            # -------------------------------

            else:

                gravacao.append(
                    audio
                )

                if (
                    probabilidade
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

            if falando:

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

    fim_captura = agora()

    # não detectou fala
    if not gravacao:

        return None, None

    audio_final = np.concatenate(
        gravacao
    ).astype(
        np.float32
    )

    metricas = {

        "inicio_espera":
            inicio_espera,

        "inicio_fala":
            inicio_fala,

        "ultima_voz":
            ultima_voz,

        "fim_captura":
            fim_captura,

        "tempo_esperando":
            (
                inicio_fala
                - inicio_espera
            ),

        "tempo_fala_ativa":
            (
                ultima_voz
                - inicio_fala
            ),

        "tempo_vad_final":
            (
                fim_captura
                - ultima_voz
            ),

        "duracao_audio":
            (
                len(audio_final)
                / SAMPLE_RATE
            )
    }

    print(
        "🔴 Fim da fala detectado."
    )

    return (
        audio_final,
        metricas
    )


# ============================================================
# TRANSCRIÇÃO
# ============================================================

def executar_transcricao(audio):

    segmentos, info = (
        whisper.transcribe(
            audio,

            language="pt",

            beam_size=
                WHISPER_BEAM_SIZE,

            best_of=
                WHISPER_BEAM_SIZE,

            temperature=0,

            condition_on_previous_text=False,

            initial_prompt=
                WHISPER_INITIAL_PROMPT,

            without_timestamps=True,

            vad_filter=False
        )
    )

    texto = "".join(
        segmento.text
        for segmento
        in segmentos
    ).strip()

    return texto


def transcrever(audio):

    global whisper
    global whisper_device

    inicio = agora()

    try:

        texto = executar_transcricao(
            audio
        )

    except RuntimeError as erro:

        erro_texto = str(
            erro
        ).lower()

        # Pode acontecer se a GPU foi detectada,
        # mas a biblioteca CUDA quebrou durante
        # uma inferência posterior.

        if (
            whisper_device != "CPU"
            and (
                "cuda" in erro_texto
                or "cublas" in erro_texto
                or "cudnn" in erro_texto
            )
        ):

            print()
            print(
                "⚠️ Falha CUDA durante STT."
            )

            print(
                "🔄 Mudando Whisper para CPU..."
            )

            criar_whisper_cpu()

            inicio = agora()

            texto = executar_transcricao(
                audio
            )

        else:
            raise

    fim = agora()

    tempo = fim - inicio

    print()
    print(
        f"📝 Você: {texto}"
    )

    print(
        f"⏱️ STT ({whisper_device}): "
        f"{tempo:.3f}s"
    )

    return (
        texto,
        tempo,
        fim
    )


# ============================================================
# DIVISÃO DO TEXTO EM FRASES
# ============================================================

def extrair_frases(buffer):

    frases = []

    while True:

        match = re.search(
            r"^(.+?[.!?])(?:\s+|$)",
            buffer,
            flags=re.DOTALL
        )

        if not match:
            break

        frase = (
            match.group(1)
            .strip()
        )

        buffer = buffer[
            match.end():
        ]

        if frase:
            frases.append(
                frase
            )

    return (
        frases,
        buffer
    )


# ============================================================
# KOKORO
# ============================================================

def extrair_audio_kokoro(resultado):

    # versões mais novas do Kokoro
    if hasattr(
        resultado,
        "audio"
    ):

        audio = resultado.audio

    # compatibilidade com versões antigas
    elif (
        isinstance(
            resultado,
            (tuple, list)
        )
        and len(resultado) >= 3
    ):

        audio = resultado[2]

    else:

        return None

    if audio is None:
        return None

    if hasattr(
        audio,
        "detach"
    ):

        audio = (
            audio
            .detach()
            .cpu()
            .numpy()
        )

    return np.asarray(
        audio,
        dtype=np.float32
    )


def falar_frase(
    texto,
    output_stream
):

    inicio_tts = agora()

    primeiro_audio_pronto = None
    primeira_reproducao = None

    samples_total = 0

    generator = tts(
        texto,
        voice=KOKORO_VOICE,
        speed=KOKORO_SPEED
    )

    for resultado in generator:

        audio = extrair_audio_kokoro(
            resultado
        )

        if audio is None:
            continue

        if primeiro_audio_pronto is None:

            primeiro_audio_pronto = (
                agora()
            )

        audio = audio.reshape(
            -1
        )

        samples_total += len(
            audio
        )

        if primeira_reproducao is None:

            primeira_reproducao = (
                agora()
            )

        output_stream.write(
            audio.reshape(
                -1,
                1
            )
        )

    fim = agora()

    return {

        "inicio_tts":
            inicio_tts,

        "primeiro_audio_pronto":
            primeiro_audio_pronto,

        "primeira_reproducao":
            primeira_reproducao,

        "fim":
            fim,

        "tempo_primeiro_audio":
            (
                primeiro_audio_pronto
                - inicio_tts
                if primeiro_audio_pronto
                else None
            ),

        "tempo_total":
            fim - inicio_tts,

        "duracao_audio":
            (
                samples_total
                / KOKORO_SAMPLE_RATE
            )
    }



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


# ============================================================
# QWEN + TTS EM STREAMING
# ============================================================

def responder(
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

    mensagens = (
        history
        + [
            {
                "role": "user",
                "content": texto_usuario
            }
        ]
    )

    fila_falas = queue.Queue()

    resposta_completa = []

    erros = []

    metricas = {

        "inicio_qwen":
            inicio_qwen,

        "primeiro_token":
            None,

        "primeira_frase":
            None,

        "fim_qwen":
            None,

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

    # ========================================================
    # THREAD DO QWEN
    # ========================================================

    def gerar():

        buffer = ""

        try:

            payload = {

                "model":
                    OLLAMA_MODEL,

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
                        100
                }
            }

            with requests.post(
                OLLAMA_URL,
                json=payload,
                stream=True,
                timeout=(5, 120)
            ) as response:

                response.raise_for_status()

                for line_data in (
                    response.iter_lines()
                ):

                    if not line_data:
                        continue

                    data = json.loads(
                        line_data
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

                    momento = agora()

                    if (
                        metricas[
                            "primeiro_token"
                        ]
                        is None
                    ):

                        metricas[
                            "primeiro_token"
                        ] = momento

                        print(
                            "\n⚡ Primeiro token Qwen: "
                            f"{momento - inicio_qwen:.3f}s"
                        )

                    resposta_completa.append(
                        token
                    )

                    print(
                        token,
                        end="",
                        flush=True
                    )

                    buffer += token

                    frases, buffer = (
                        extrair_frases(
                            buffer
                        )
                    )

                    for frase in frases:

                        if (
                            metricas[
                                "primeira_frase"
                            ]
                            is None
                        ):

                            metricas[
                                "primeira_frase"
                            ] = agora()

                        fila_falas.put(
                            frase
                        )

                # texto final que não terminou em
                # ponto, exclamação ou interrogação

                if buffer.strip():

                    if (
                        metricas[
                            "primeira_frase"
                        ]
                        is None
                    ):

                        metricas[
                            "primeira_frase"
                        ] = agora()

                    fila_falas.put(
                        buffer.strip()
                    )

        except Exception as erro:

            erros.append(
                erro
            )

        finally:

            metricas[
                "fim_qwen"
            ] = agora()

            fila_falas.put(
                None
            )

    thread = threading.Thread(
        target=gerar,
        daemon=True
    )

    print()
    print(
        "🤖 Arka: ",
        end="",
        flush=True
    )

    thread.start()

    # Abrimos a saída de áudio enquanto
    # o Qwen já está pensando.

    with sd.OutputStream(
        samplerate=
            KOKORO_SAMPLE_RATE,

        channels=1,

        dtype="float32"
    ) as output_stream:

        primeira_frase_falada = True

        while True:

            frase = fila_falas.get()

            if frase is None:
                break

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

            if primeira_frase_falada:

                primeira_frase_falada = False

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

    thread.join()

    print()

    if erros:
        raise erros[0]

    resposta = "".join(
        resposta_completa
    ).strip()

    history.append(
        {
            "role": "user",
            "content": texto_usuario
        }
    )

    history.append(
        {
            "role": "assistant",
            "content": resposta
        }
    )

    # Limita histórico para não deixar o
    # contexto crescer indefinidamente.

    if len(history) > 13:

        history = (
            [history[0]]
            + history[-12:]
        )

    return (
        resposta,
        metricas
    )


# ============================================================
# RELATÓRIO DE TEMPOS
# ============================================================

def mostrar_relatorio(
    audio,
    tempo_stt,
    metricas
):

    linha()

    print(
        "⏱️  RELATÓRIO DE LATÊNCIA"
    )

    linha()

    mostrar_tempo(
        "Esperando você começar:",
        audio["tempo_esperando"]
    )

    mostrar_tempo(
        "Tempo de fala ativa:",
        audio["tempo_fala_ativa"]
    )

    mostrar_tempo(
        "VAD esperando fim da fala:",
        audio["tempo_vad_final"]
    )

    mostrar_tempo(
        "Áudio entregue ao Whisper:",
        audio["duracao_audio"]
    )

    print()

    mostrar_tempo(
        "Whisper / STT:",
        tempo_stt
    )

    # -----------------------------
    # QWEN
    # -----------------------------

    if (
        metricas["primeiro_token"]
        is not None
    ):

        mostrar_tempo(
            "Qwen → primeiro token:",
            (
                metricas[
                    "primeiro_token"
                ]
                - metricas[
                    "inicio_qwen"
                ]
            )
        )

    if (
        metricas["primeira_frase"]
        is not None
    ):

        mostrar_tempo(
            "Qwen → primeira frase:",
            (
                metricas[
                    "primeira_frase"
                ]
                - metricas[
                    "inicio_qwen"
                ]
            )
        )

    if (
        metricas["fim_qwen"]
        is not None
    ):

        mostrar_tempo(
            "Qwen → resposta completa:",
            (
                metricas[
                    "fim_qwen"
                ]
                - metricas[
                    "inicio_qwen"
                ]
            )
        )

    print()

    # -----------------------------
    # TTS
    # -----------------------------

    mostrar_tempo(
        "Kokoro → primeiro áudio:",
        metricas[
            "tts_sintese_primeiro"
        ]
    )

    mostrar_tempo(
        "Kokoro/TTS acumulado:",
        metricas[
            "tts_total"
        ]
    )

    mostrar_tempo(
        "Áudio falado pela Arka:",
        metricas[
            "audio_falado"
        ]
    )

    print()

    # ========================================================
    # PRINCIPAIS NÚMEROS
    # ========================================================

    primeira_reproducao = (
        metricas[
            "primeira_reproducao"
        ]
    )

    if primeira_reproducao:

        latencia_real = (
            primeira_reproducao
            - audio[
                "ultima_voz"
            ]
        )

        latencia_apos_vad = (
            primeira_reproducao
            - audio[
                "fim_captura"
            ]
        )

        linha()

        print(
            "🔥 MÉTRICAS PRINCIPAIS"
        )

        linha()

        mostrar_tempo(
            "Fim da fala → Arka fala:",
            latencia_real
        )

        mostrar_tempo(
            "Após VAD → Arka fala:",
            latencia_apos_vad
        )

    if (
        metricas[
            "fim_reproducao"
        ]
        is not None
    ):

        mostrar_tempo(
            "Turno completo:",
            (
                metricas[
                    "fim_reproducao"
                ]
                - audio[
                    "ultima_voz"
                ]
            )
        )

    linha()


# ============================================================
# INICIALIZAÇÃO
# ============================================================

print()
linha()
print("🤖 ARKA ONLINE")
linha()

print(
    f"Ollama:  {OLLAMA_MODEL}"
)

print(
    f"Whisper: {WHISPER_MODEL}"
)

print(
    f"Whisper beam: "
    f"{WHISPER_BEAM_SIZE}"
)

print(
    f"Dispositivo Whisper: "
    f"{whisper_device}"
)

print(
    f"Voz:     {KOKORO_VOICE}"
)

print()

print(
    "Fale normalmente com a Arka."
)

print(
    "CTRL+C para encerrar."
)

linha()


# ============================================================
# LOOP PRINCIPAL
# ============================================================

try:

    while True:

        # --------------------------------
        # 1. ESCUTAR
        # --------------------------------

        audio, metricas_audio = (
            ouvir()
        )

        if audio is None:
            continue

        # --------------------------------
        # 2. TRANSCRIÇÃO
        # --------------------------------

        texto, tempo_stt, fim_stt = (
            transcrever(
                audio
            )
        )

        if not texto:
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
        # --------------------------------

        resposta, metricas_resposta = (
            responder(
                texto,
                metricas_audio,
                fim_stt
            )
        )

        # --------------------------------
        # 4. RELATÓRIO
        # --------------------------------

        mostrar_relatorio(
            metricas_audio,
            tempo_stt,
            metricas_resposta
        )


except KeyboardInterrupt:

    print()
    print()
    print(
        "👋 Arka encerrada."
    )