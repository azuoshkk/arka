from pathlib import Path
from datetime import datetime
import shutil


ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "voice.py"

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_whisper_quality_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

shutil.copy2(
    VOICE,
    backup / "voice.py",
)

text = VOICE.read_text(
    encoding="utf-8"
)


# ============================================================
# CONFIGURAÇÃO DO MODELO
# ============================================================

old = '''WHISPER_MODEL = "base"
'''

new = '''# Pode ser alterado sem editar o arquivo:
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
'''

if old not in text:

    if (
        "WHISPER_BEAM_SIZE"
        not in text
    ):

        raise RuntimeError(
            "Não encontrei "
            "WHISPER_MODEL."
        )

else:

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# DECODIFICAÇÃO
# ============================================================

old = '''            beam_size=1,

            best_of=1,

            temperature=0,

            condition_on_previous_text=False,

            without_timestamps=True,

            vad_filter=False
'''

new = '''            beam_size=
                WHISPER_BEAM_SIZE,

            best_of=
                WHISPER_BEAM_SIZE,

            temperature=0,

            condition_on_previous_text=False,

            initial_prompt=
                WHISPER_INITIAL_PROMPT,

            without_timestamps=True,

            vad_filter=False
'''

if old not in text:

    if (
        "initial_prompt="
        not in text
    ):

        raise RuntimeError(
            "Não encontrei o bloco "
            "de transcrição."
        )

else:

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# MOSTRA CONFIGURAÇÃO AO INICIAR
# ============================================================

marker = '''print(
    f"Whisper: {WHISPER_MODEL}"
)
'''

replacement = '''print(
    f"Whisper: {WHISPER_MODEL}"
)

print(
    f"Whisper beam: "
    f"{WHISPER_BEAM_SIZE}"
)
'''

if (
    "Whisper beam:"
    not in text
):

    if marker not in text:

        raise RuntimeError(
            "Não encontrei impressão "
            "do Whisper."
        )

    text = text.replace(
        marker,
        replacement,
        1,
    )


VOICE.write_text(
    text,
    encoding="utf-8",
)

print(
    "✅ Qualidade do Whisper melhorada."
)

print(
    "Modelo:",
    "base"
)

print(
    "Beam:",
    5
)

print(
    "Vocabulário técnico:",
    "ativado"
)

print(
    "Backup:",
    backup,
)
