from pathlib import Path
from datetime import datetime
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

EMBEDDER = SERVER / "app/knowledge/embedder.py"
ARKA = SERVER / "arka.py"
RUNNER = SERVER / "arka-run"

SPEECH_DIR = SERVER / "app/speech"
TTS = SPEECH_DIR / "tts_fast.py"
WARMUP = SERVER / "warmup_arka.py"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_fast_tts_v5_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

for path in (
    EMBEDDER,
    ARKA,
    RUNNER,
):

    if path.exists():

        target = (
            backup
            / path.relative_to(ROOT)
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            path,
            target,
        )

print(
    "✅ Backup:",
    backup,
)


# ============================================================
# 1. EMBEDDING SEMPRE NA CPU
# ============================================================

EMBEDDER.write_text(
r'''import os

import requests

from app.config import (
    OLLAMA_URL,
    EMBEDDING_MODEL,
)


EMBED_KEEP_ALIVE = os.getenv(
    "ARKA_EMBED_KEEP_ALIVE",
    "30m",
)

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
''',
    encoding="utf-8",
)

print(
    "✅ Embedding → CPU."
)


# ============================================================
# 2. TTS FAST
# ============================================================

SPEECH_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

(SPEECH_DIR / "__init__.py").touch()


TTS.write_text(
r'''from __future__ import annotations

import queue
import re
import threading
import time

import numpy as np
import sounddevice as sd


KOKORO_SAMPLE_RATE = 24000


def clean_for_speech(
    text: str,
):

    text = text or ""

    # Remove citações RAG.
    text = re.sub(
        r"\[Fonte\s+\d+\]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Markdown.
    text = text.replace(
        "**",
        "",
    )

    text = text.replace(
        "__",
        "",
    )

    text = text.replace(
        "`",
        "",
    )

    # URLs enormes não devem ser faladas.
    text = re.sub(
        r"https?://\S+",
        "link",
        text,
    )

    # Espaços.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


class FastTTS:

    def __init__(
        self,
        voice="pf_dora",
        speed=1.08,
    ):

        self.voice = voice
        self.speed = speed

        self.pipeline = None

        self.queue = queue.Queue()

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True,
        )

        self.worker.start()

        self.load_lock = (
            threading.Lock()
        )

        self.first_audio_time = None


    def load(self):

        if self.pipeline is not None:
            return

        with self.load_lock:

            if self.pipeline is not None:
                return

            print()
            print(
                "🔊 Carregando Kokoro TTS..."
            )

            start = time.perf_counter()

            from kokoro import KPipeline

            self.pipeline = KPipeline(
                lang_code="p",
                repo_id="hexgrad/Kokoro-82M",
                device="cpu",
            )

            print(
                "✅ Kokoro pronto em "
                f"{time.perf_counter() - start:.3f}s"
            )


    def say(
        self,
        text,
    ):

        text = clean_for_speech(
            text
        )

        if not text:
            return

        self.queue.put(
            text
        )


    def _worker(self):

        while True:

            text = self.queue.get()

            try:

                self.load()

                generator = self.pipeline(
                    text,
                    voice=self.voice,
                    speed=self.speed,
                    split_pattern=r"\n+",
                )

                for item in generator:

                    # Kokoro normalmente retorna:
                    # graphemes, phonemes, audio
                    audio = item[-1]

                    audio = np.asarray(
                        audio,
                        dtype=np.float32,
                    )

                    if (
                        self.first_audio_time
                        is None
                    ):
                        self.first_audio_time = (
                            time.perf_counter()
                        )

                    sd.play(
                        audio,
                        samplerate=
                            KOKORO_SAMPLE_RATE,
                    )

                    sd.wait()

            except Exception as exc:

                print()
                print(
                    "⚠️ TTS:",
                    repr(exc),
                )

            finally:

                self.queue.task_done()


    def wait(
        self,
    ):

        self.queue.join()


class SentenceTTSBuffer:

    def __init__(
        self,
        engine: FastTTS,
    ):

        self.engine = engine
        self.buffer = ""


    def reset(
        self,
    ):

        self.buffer = ""


    def feed(
        self,
        token: str,
    ):

        self.buffer += (
            token
        )

        self._emit_sentences()


    def _emit_sentences(
        self,
    ):

        while True:

            # Frase completa.
            match = re.search(
                r"^(.+?[.!?;:])(?:\s+|$)",
                self.buffer,
                flags=re.DOTALL,
            )

            if match:

                sentence = (
                    match
                    .group(1)
                    .strip()
                )

                self.buffer = (
                    self.buffer[
                        match.end():
                    ]
                )

                if sentence:

                    self.engine.say(
                        sentence
                    )

                continue

            # Se o modelo escreve uma frase enorme
            # sem ponto, libera no último separador.
            if len(self.buffer) >= 180:

                positions = [
                    self.buffer.rfind(","),
                    self.buffer.rfind(";"),
                ]

                cut = max(
                    positions
                )

                if cut >= 80:

                    piece = (
                        self.buffer[
                            :cut + 1
                        ]
                        .strip()
                    )

                    self.buffer = (
                        self.buffer[
                            cut + 1:
                        ]
                    )

                    if piece:

                        self.engine.say(
                            piece
                        )

                    continue

            break


    def flush(
        self,
    ):

        remaining = (
            self.buffer
            .strip()
        )

        self.buffer = ""

        if remaining:

            self.engine.say(
                remaining
            )


    def flush_and_wait(
        self,
    ):

        self.flush()

        self.engine.wait()
''',
    encoding="utf-8",
)

print(
    "✅ TTS streaming criado."
)


# ============================================================
# 3. WARMUP
# ============================================================

WARMUP.write_text(
r'''import time

import requests

from app.config import (
    OLLAMA_URL,
    EMBEDDING_MODEL,
    LLM_MODEL,
)


def ns_to_s(value):
    return (
        (value or 0)
        / 1_000_000_000
    )


print()
print(
    "🔥 Preparando modelos..."
)


# ============================================================
# EMBEDDING CPU
# ============================================================

start = time.perf_counter()

r = requests.post(
    f"{OLLAMA_URL}/api/embed",

    json={
        "model":
            EMBEDDING_MODEL,

        "input":
            "Arka warmup",

        "keep_alive":
            "30m",

        "options": {
            "num_gpu":
                0,
        },
    },

    timeout=180,
)

r.raise_for_status()

data = r.json()

print(
    "✅ Embedding CPU "
    f"{time.perf_counter() - start:.3f}s "
    "| load="
    f"{ns_to_s(data.get('load_duration')):.3f}s"
)


# ============================================================
# QWEN GPU
# ============================================================

start = time.perf_counter()

r = requests.post(
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

        "messages": [
            {
                "role":
                    "user",

                "content":
                    "Responda apenas OK.",
            }
        ],

        "options": {
            "temperature":
                0,

            "num_predict":
                3,

            "num_ctx":
                4096,
        },
    },

    timeout=180,
)

r.raise_for_status()

data = r.json()

print(
    "✅ Qwen GPU "
    f"{time.perf_counter() - start:.3f}s "
    "| load="
    f"{ns_to_s(data.get('load_duration')):.3f}s"
)


# ============================================================
# RESIDÊNCIA
# ============================================================

r = requests.get(
    f"{OLLAMA_URL}/api/ps",
    timeout=10,
)

r.raise_for_status()

print()

for model in r.json().get(
    "models",
    [],
):

    print(
        "📦",
        model.get("name"),
        "| VRAM:",
        f"{model.get('size_vram', 0) / 1024**3:.2f} GB",
    )
''',
    encoding="utf-8",
)

print(
    "✅ Warmup criado."
)


# ============================================================
# 4. PATCH ARKA
# ============================================================

arka = ARKA.read_text(
    encoding="utf-8",
)


# ------------------------------------------------------------
# IMPORT
# ------------------------------------------------------------

if (
    "from app.speech.tts_fast import"
    not in arka
):

    marker = (
        "from app.agents.expert import (\n"
    )

    tts_import = '''from app.speech.tts_fast import (
    FastTTS,
    SentenceTTSBuffer,
)

'''

    if marker not in arka:

        raise RuntimeError(
            "Import app.agents.expert "
            "não encontrado."
        )

    arka = arka.replace(
        marker,
        tts_import + marker,
        1,
    )


# ------------------------------------------------------------
# GLOBALS DO TTS
# ------------------------------------------------------------

if "tts_engine = None" not in arka:

    marker = (
        "# ============================================================\n"
        "# CHAT NORMAL"
    )

    globals_tts = r'''
# ============================================================
# TTS
# ============================================================

tts_engine = None
tts_buffer = None
tts_enabled = False


def set_tts_enabled(
    enabled: bool,
):

    global tts_enabled

    tts_enabled = enabled


def ensure_tts():

    global tts_engine
    global tts_buffer

    if tts_engine is None:

        tts_engine = FastTTS(
            voice=os.getenv(
                "ARKA_TTS_VOICE",
                "pf_dora",
            ),

            speed=float(
                os.getenv(
                    "ARKA_TTS_SPEED",
                    "1.08",
                )
            ),
        )

        tts_buffer = SentenceTTSBuffer(
            tts_engine
        )

        # Carrega já para a primeira resposta
        # não pagar custo de inicialização.
        tts_engine.load()


def tts_begin():

    if (
        not tts_enabled
        or tts_buffer is None
    ):
        return

    tts_buffer.reset()


def tts_feed(
    token,
):

    if (
        not tts_enabled
        or tts_buffer is None
    ):
        return

    tts_buffer.feed(
        token
    )


def tts_finish():

    if (
        not tts_enabled
        or tts_buffer is None
    ):
        return

    tts_buffer.flush_and_wait()


'''

    if marker not in arka:

        raise RuntimeError(
            "Seção CHAT NORMAL "
            "não encontrada."
        )

    arka = arka.replace(
        marker,
        globals_tts + marker,
        1,
    )


# ------------------------------------------------------------
# CHAT → TTS
# ------------------------------------------------------------

if "tts_begin()\n\n    mensagens" not in arka:

    old = '''def responder_chat(texto: str):

    mensagens = history + [
'''

    new = '''def responder_chat(texto: str):

    tts_begin()

    mensagens = history + [
'''

    if old not in arka:

        raise RuntimeError(
            "responder_chat não encontrado."
        )

    arka = arka.replace(
        old,
        new,
        1,
    )


# Primeiro print(token) é o CHAT.
chat_print = '''            print(
                token,
                end="",
                flush=True,
            )
'''

chat_print_tts = '''            print(
                token,
                end="",
                flush=True,
            )

            tts_feed(
                token
            )
'''

if (
    chat_print in arka
    and "tts_feed(\n                token" not in arka.split(
        "def responder_chat",
        1
    )[1].split(
        "# ============================================================\n# ROUTER",
        1
    )[0]
):

    arka = arka.replace(
        chat_print,
        chat_print_tts,
        1,
    )


if "tts_finish()\n\n    return resposta_final" not in arka:

    old = '''    return resposta_final
'''

    new = '''    tts_finish()

    return resposta_final
'''

    if old not in arka:

        raise RuntimeError(
            "return resposta_final "
            "não encontrado."
        )

    arka = arka.replace(
        old,
        new,
        1,
    )


# ------------------------------------------------------------
# EXPERT → TTS
# ------------------------------------------------------------

process_section_start = arka.find(
    "def processar(texto: str):"
)

process_section_end = arka.find(
    "# ============================================================\n# TXT",
    process_section_start,
)

if (
    process_section_start == -1
    or process_section_end == -1
):

    raise RuntimeError(
        "processar() não encontrado."
    )

process_section = arka[
    process_section_start:
    process_section_end
]


if (
    "tts_begin()"
    not in process_section
):

    old = '''    print()
    print(
        "Arka [EXPERT]> ",
        end="",
        flush=True,
    )
'''

    new = '''    print()
    print(
        "Arka [EXPERT]> ",
        end="",
        flush=True,
    )

    tts_begin()
'''

    if old not in arka:

        raise RuntimeError(
            "Arka [EXPERT] não encontrada."
        )

    arka = arka.replace(
        old,
        new,
        1,
    )


old = '''        print(
            token,
            end="",
            flush=True,
        )
'''

new = '''        print(
            token,
            end="",
            flush=True,
        )

        tts_feed(
            token
        )
'''

process_section = arka[
    process_section_start:
    process_section_end
]

if (
    "tts_feed("
    not in process_section
):

    pos = arka.find(
        old,
        process_section_start,
        process_section_end,
    )

    if pos == -1:

        raise RuntimeError(
            "mostrar_token não encontrado."
        )

    arka = (
        arka[:pos]
        + new
        + arka[pos + len(old):]
    )


# Finish após answer_stream.
process_section_start = arka.find(
    "def processar(texto: str):"
)

process_section_end = arka.find(
    "# ============================================================\n# TXT",
    process_section_start,
)

process_section = arka[
    process_section_start:
    process_section_end
]

if "tts_finish()" not in process_section:

    marker = '''    print()

    resposta = (
'''

    replacement = '''    print()

    # Espera terminar a fala antes de
    # reabrir o microfone, evitando que
    # a Arka escute a própria voz.
    tts_finish()

    resposta = (
'''

    if marker not in process_section:

        raise RuntimeError(
            "Final do answer_stream "
            "não encontrado."
        )

    absolute = (
        process_section_start
        + process_section.find(
            marker
        )
    )

    arka = (
        arka[:absolute]
        + replacement
        + arka[
            absolute + len(marker):
        ]
    )


# ------------------------------------------------------------
# TXT = SEM TTS
# ------------------------------------------------------------

if "def modo_txt():\n\n    set_tts_enabled(False)" not in arka:

    old = '''def modo_txt():

    print()
'''

    new = '''def modo_txt():

    set_tts_enabled(False)

    print()
'''

    if old not in arka:

        raise RuntimeError(
            "modo_txt() não encontrado."
        )

    arka = arka.replace(
        old,
        new,
        1,
    )


# ------------------------------------------------------------
# STT = COM TTS
# ------------------------------------------------------------

if "set_tts_enabled(True)" not in arka:

    old = '''def modo_stt():

    carregar_stt()
'''

    new = '''def modo_stt():

    set_tts_enabled(True)

    carregar_stt()

    ensure_tts()
'''

    if old not in arka:

        raise RuntimeError(
            "modo_stt() não encontrado."
        )

    arka = arka.replace(
        old,
        new,
        1,
    )


# Mensagem da interface.
arka = arka.replace(
    '''A resposta da Arka aparece SOMENTE em texto.''',
    '''A Arka responde em texto + voz.''',
)


ARKA.write_text(
    arka,
    encoding="utf-8",
)

print(
    "✅ arka.py → TTS streaming."
)


# ============================================================
# 5. RUNNER
# ============================================================

runner = RUNNER.read_text(
    encoding="utf-8",
)


if "ARKA_EMBED_NUM_GPU" not in runner:

    marker = '''export ARKA_CHAT_MODEL="${ARKA_CHAT_MODEL:-qwen3:8b}"
'''

    replacement = '''export ARKA_CHAT_MODEL="${ARKA_CHAT_MODEL:-qwen3:8b}"

# Modelos separados para não disputar VRAM.
export ARKA_EMBED_NUM_GPU="${ARKA_EMBED_NUM_GPU:-0}"
export ARKA_EMBED_KEEP_ALIVE="${ARKA_EMBED_KEEP_ALIVE:-30m}"

# TTS
export ARKA_TTS_VOICE="${ARKA_TTS_VOICE:-pf_dora}"
export ARKA_TTS_SPEED="${ARKA_TTS_SPEED:-1.08}"
'''

    if marker not in runner:

        raise RuntimeError(
            "ARKA_CHAT_MODEL "
            "não encontrado."
        )

    runner = runner.replace(
        marker,
        replacement,
        1,
    )


if "warmup_arka.py" not in runner:

    marker = '''CMD=(
    python
    -u
    arka.py
)
'''

    replacement = '''# ============================================================
# MODEL WARMUP
# ============================================================

if [ "${ARKA_WARMUP:-1}" = "1" ]; then

    python -u warmup_arka.py || {
        echo "⚠️ Warmup falhou; continuando."
    }

fi


CMD=(
    python
    -u
    arka.py
)
'''

    if marker not in runner:

        raise RuntimeError(
            "CMD do arka-run "
            "não encontrado."
        )

    runner = runner.replace(
        marker,
        replacement,
        1,
    )


RUNNER.write_text(
    runner,
    encoding="utf-8",
)

os.chmod(
    RUNNER,
    0o755,
)

print(
    "✅ arka-run atualizado."
)


# ============================================================
# VALIDATION
# ============================================================

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(EMBEDDER),
        str(TTS),
        str(WARMUP),
        str(ARKA),
    ],
    check=True,
)

subprocess.run(
    [
        "bash",
        "-n",
        str(RUNNER),
    ],
    check=True,
)

print()
print(
    "============================================"
)

print(
    " ARKA FAST + TTS V5 INSTALADO"
)

print(
    "============================================"
)

print()

print(
    "Backup:",
    backup,
)

print()
print(
    "Próximo passo:"
)

print(
    "cd robot-server"
)

print(
    "python warmup_arka.py"
)

print(
    "python benchmark_expert.py"
)

print(
    "./arka-run --stt"
)
