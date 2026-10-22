from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

import requests


ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "voice.py"
RUN = ROOT / "robot-server" / "arka-run"

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_ollama_model_fix_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

shutil.copy2(
    VOICE,
    backup / "voice.py",
)

shutil.copy2(
    RUN,
    backup / "arka-run",
)


# ============================================================
# VOICE.PY
# ============================================================

text = VOICE.read_text(
    encoding="utf-8"
)

start_marker = (
    "def descobrir_modelo_ollama():"
)

end_marker = (
    '\n\nprint()\n'
    'print("🔎 Procurando modelo do Ollama...")'
)

start = text.find(
    start_marker
)

if start == -1:
    raise RuntimeError(
        "Não encontrei "
        "descobrir_modelo_ollama()."
    )

end = text.find(
    end_marker,
    start,
)

if end == -1:
    raise RuntimeError(
        "Não encontrei o final "
        "de descobrir_modelo_ollama()."
    )


new_function = r'''def modelo_serve_para_chat(
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
'''


text = (
    text[:start]
    + new_function
    + text[end:]
)

VOICE.write_text(
    text,
    encoding="utf-8"
)

print(
    "✅ Descoberta de modelo "
    "do voice.py corrigida."
)


# ============================================================
# ARKA-RUN
# ============================================================

run = RUN.read_text(
    encoding="utf-8"
)

sentinel = (
    'export OLLAMA_MODEL='
)

if sentinel not in run:

    old = '''set -u
'''

    new = '''set -u

# Modelo conversacional oficial da Arka.
# Nunca deixa o voice.py pegar acidentalmente
# o modelo de embeddings carregado pelo RAG.

export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
'''

    if old not in run:

        raise RuntimeError(
            "Não encontrei 'set -u' "
            "no arka-run."
        )

    run = run.replace(
        old,
        new,
        1,
    )

    RUN.write_text(
        run,
        encoding="utf-8"
    )

print(
    "✅ arka-run fixado em qwen3:8b."
)


# ============================================================
# SINTAXE
# ============================================================

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(VOICE),
    ],
    check=True,
)

print(
    "✅ voice.py compila."
)


# ============================================================
# TESTE REAL DO /api/chat
# ============================================================

print()
print(
    "🧪 Testando qwen3:8b "
    "diretamente no /api/chat..."
)

response = requests.post(
    "http://localhost:11434/api/chat",

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
                    "Responda somente OK."
            }
        ],

        "options": {
            "temperature":
                0,

            "num_predict":
                5,
        },
    },

    timeout=120,
)

if not response.ok:

    print(
        "❌ Ollama respondeu:",
        response.status_code
    )

    print(
        response.text
    )

    response.raise_for_status()

data = response.json()

print(
    "✅ /api/chat funcionando."
)

print(
    "Resposta:",
    data.get(
        "message",
        {}
    ).get(
        "content",
        ""
    )
)

print()
print(
    "✅ CORREÇÃO CONCLUÍDA."
)

print(
    "Backup:",
    backup
)
