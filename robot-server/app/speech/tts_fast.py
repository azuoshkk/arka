from __future__ import annotations

import queue
import re
import threading
import time

import numpy as np
from num2words import num2words
import sounddevice as sd


KOKORO_SAMPLE_RATE = 24000


# ============================================================
# AJUSTES
# ============================================================

MAX_BLOCK_CHARS = 260

# Remove apenas silêncio exagerado na borda
# do áudio gerado pelo modelo.
TRIM_THRESHOLD = 0.008

# Mantém um pequeno respiro para não cortar fonemas.
TRIM_PAD_MS = 35



def _integer_pt(
    value,
):
    try:
        return num2words(
            int(value),
            lang="pt_BR",
        )
    except Exception:
        return str(value)


def _decimal_pt(
    match,
):
    inteiro = match.group(1)
    decimal = match.group(2)

    decimal_words = " ".join(
        _integer_pt(digit)
        for digit in decimal
    )

    return (
        _integer_pt(inteiro)
        + " vírgula "
        + decimal_words
    )


def numbers_for_speech(
    text: str,
):
    """
    Converte números/unidades para fala natural.
    Só altera a versão enviada ao TTS.
    """

    # --------------------------------------------------------
    # NOMES TÉCNICOS
    # --------------------------------------------------------

    text = re.sub(
        r"\bT[\s-]*800\b",
        "T oitocentos",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\bROS[\s-]*2\b",
        "ROS dois",
        text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # UNIDADES
    # --------------------------------------------------------

    units = [
        (r"\bkm/h\b", "quilômetros por hora"),
        (r"\bm/s\b", "metros por segundo"),
        (r"\bkHz\b", "quilohertz"),
        (r"\bMHz\b", "megahertz"),
        (r"\bGHz\b", "gigahertz"),
        (r"\bkg\b", "quilogramas"),
        (r"\bcm\b", "centímetros"),
        (r"\bmm\b", "milímetros"),
        (r"\bkm\b", "quilômetros"),
        (r"\bHz\b", "hertz"),
        (r"\bV\b", "volts"),
        
        (r"\bW\b", "watts"),
        (r"\bg\b", "gramas"),
        (r"\bm\b", "metros"),
    ]

    for pattern, replacement in units:

        text = re.sub(
            pattern,
            replacement,
            text,
            flags=re.IGNORECASE,
        )

    # "a" is also a Portuguese article/preposition. Expand amperes only
    # as a suffix of a numeric quantity, with or without a separating space.
    text = re.sub(
        r"(?<![\w.,])([+-]?\d+(?:[.,]\d+)?)\s*[aA]\b(?!\s*\d)",
        r"\1 ampères",
        text,
    )

    # Percentual.
    text = re.sub(
        r"(\d+(?:[,.]\d+)?)\s*%",
        r"\1 por cento",
        text,
    )

    # --------------------------------------------------------
    # DECIMAIS
    # --------------------------------------------------------

    text = re.sub(
        r"\b(\d+)[,.](\d+)\b",
        _decimal_pt,
        text,
    )

    # --------------------------------------------------------
    # INTEIROS
    # --------------------------------------------------------

    def replace_integer(
        match,
    ):
        return _integer_pt(
            match.group(0)
        )

    text = re.sub(
        r"\b\d+\b",
        replace_integer,
        text,
    )

    return text



def commercial_name_for_speech(
    text: str,
):
    """
    Na fala, o usuário deve ouvir somente
    o nome comercial Arcanjo.
    """

    text = re.sub(
        r"\bT[\s-]*800\b",
        "Arcanjo",
        text,
        flags=re.IGNORECASE,
    )

    return text


def clean_for_speech(
    text: str,
):

    text = text or ""

    # ========================================================
    # REMOVE REFERÊNCIAS DE FONTE DA FALA
    # REMOVE REFERÊNCIAS DE FONTE
    #
    # Exemplos removidos:
    # [Fonte 1]
    # Fonte 1
    # fonte 3
    # Fontes 2 e 4
    # ========================================================

    # Formato entre colchetes.
    text = re.sub(
        r"\[\s*fontes?\s+\d+(?:\s*(?:,|e)\s*\d+)*\s*\]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Formato sem colchetes.
    text = re.sub(
        r"\bfontes?\s+\d+(?:\s*(?:,|e)\s*\d+)*\b",
        "",
        text,
        flags=re.IGNORECASE,
    )


    # Limpa palavras que ficaram órfãs depois
    # da remoção das citações.
    text = re.sub(
        r"\b(?:conforme|segundo)\s*[\.,;:]",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s+([\.,!?])",
        r"\1",
        text,
    )

    text = re.sub(
        r",\s*\.",
        ".",
        text,
    )

    # ========================================================
    # NOME COMERCIAL
    # ========================================================

    text = commercial_name_for_speech(
        text
    )

    text = numbers_for_speech(
        text
    )

    # --------------------------------------------------------
    # EMOJIS / SÍMBOLOS VISUAIS
    #
    # O terminal continua mostrando os emojis.
    # Só removemos da versão enviada ao TTS.
    # --------------------------------------------------------

    text = re.sub(
        "["
        "\U0001F1E0-\U0001F1FF"
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\U00002600-\U000026FF"
        "\U00002700-\U000027BF"
        "]+",
        "",
        text,
    )

    # Variation selectors / zero-width joiner,
    # comuns em emojis compostos.
    text = text.replace(
        "\ufe0f",
        "",
    )

    text = text.replace(
        "\u200d",
        "",
    )

    # --------------------------------------------------------
    # RAG / MARKDOWN
    # --------------------------------------------------------

    text = re.sub(
        r"\[Fonte\s+\d+\]",
        "",
        text,
        flags=re.IGNORECASE,
    )

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

    text = re.sub(
        r"https?://\S+",
        "link",
        text,
    )

    # --------------------------------------------------------
    # PONTUAÇÃO
    #
    # Não removemos pontos normais.
    # O Kokoro usa isso para prosódia.
    #
    # Só reduzimos casos que provocam pausas exageradas.
    # --------------------------------------------------------

    # Reticências -> vírgula curta.
    text = re.sub(
        r"\.{2,}",
        ",",
        text,
    )

    # ; tende a soar muito longo.
    text = re.sub(
        r"\s*;\s*",
        ", ",
        text,
    )

    # Dois-pontos em fala técnica geralmente
    # funciona melhor como vírgula.
    text = re.sub(
        r"\s*:\s*",
        ", ",
        text,
    )

    # Várias exclamações/interrogações.
    text = re.sub(
        r"!{2,}",
        "!",
        text,
    )

    text = re.sub(
        r"\?{2,}",
        "?",
        text,
    )

    # --------------------------------------------------------
    # ESPAÇOS
    # --------------------------------------------------------

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def trim_silence(
    audio,
):

    """
    Remove silêncio exagerado no começo/fim
    de cada bloco de áudio sem mexer nas pausas
    internas da frase.
    """

    audio = np.asarray(
        audio,
        dtype=np.float32,
    )

    if audio.size == 0:
        return audio

    absolute = np.abs(
        audio
    )

    indexes = np.where(
        absolute
        > TRIM_THRESHOLD
    )[0]

    if indexes.size == 0:
        return audio

    pad = int(
        (
            TRIM_PAD_MS
            / 1000
        )
        * KOKORO_SAMPLE_RATE
    )

    start = max(
        0,
        int(indexes[0]) - pad,
    )

    end = min(
        len(audio),
        int(indexes[-1]) + pad,
    )

    return audio[
        start:end
    ]


class FastTTS:

    def __init__(
        self,
        voice="pf_dora",
        speed=1.25,
    ):

        self.voice = voice
        self.speed = speed

        self.pipeline = None

        self.queue = queue.Queue()

        self.load_lock = (
            threading.Lock()
        )

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True,
        )

        self.worker.start()


    def load(
        self,
    ):

        if self.pipeline is not None:
            return

        with self.load_lock:

            if self.pipeline is not None:
                return

            print()
            print(
                "🔊 Carregando Kokoro TTS..."
            )

            started = (
                time.perf_counter()
            )

            from kokoro import KPipeline

            self.pipeline = KPipeline(
                lang_code="p",
                repo_id="hexgrad/Kokoro-82M",
                device="cpu",
            )

            print(
                "✅ Kokoro pronto em "
                f"{time.perf_counter() - started:.3f}s"
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


    def _worker(
        self,
    ):

        while True:

            text = self.queue.get()

            try:

                self.load()

                # IMPORTANTE:
                # o bloco já chega maior.
                # Não quebramos novamente em cada frase.
                generator = self.pipeline(
                    text,
                    voice=self.voice,
                    speed=self.speed,

                    # Só quebra se houver newline explícito.
                    split_pattern=r"\n+",
                )

                for item in generator:

                    audio = (
                        item[-1]
                    )

                    audio = trim_silence(
                        audio
                    )

                    if (
                        audio is None
                        or len(audio) == 0
                    ):
                        continue

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

    """
    O nome foi mantido por compatibilidade,
    mas agora funciona como BLOCK buffer.

    Não envia cada frase individualmente.
    Junta várias frases em um bloco maior.
    """

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

        self.buffer += token

        self._maybe_emit()


    def _maybe_emit(
        self,
    ):

        # ----------------------------------------------------
        # Só começa a pensar em emitir quando já há texto
        # suficiente.
        # ----------------------------------------------------

        if (
            len(self.buffer)
            < 140
        ):
            return

        # ----------------------------------------------------
        # Se chegou perto do tamanho máximo, procura
        # o ÚLTIMO fim de frase disponível.
        # ----------------------------------------------------

        if (
            len(self.buffer)
            >= MAX_BLOCK_CHARS
        ):

            window = self.buffer[
                :MAX_BLOCK_CHARS
            ]

            positions = [
                window.rfind(". "),
                window.rfind("? "),
                window.rfind("! "),
            ]

            cut = max(
                positions
            )

            # Se não há ponto bom, tenta vírgula,
            # mas só depois de bastante texto.
            if cut < 100:

                cut = window.rfind(
                    ", "
                )

            # Último fallback:
            # espaço.
            if cut < 100:

                cut = window.rfind(
                    " "
                )

            if cut > 0:

                block = (
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

                if block:

                    self.engine.say(
                        block
                    )


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
