from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

BRIDGE = SERVER / "app/core/voice_bridge.py"
TEST = SERVER / "test_voice_bridge.py"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_query_expansion_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

shutil.copy2(
    BRIDGE,
    backup / "voice_bridge.py",
)

shutil.copy2(
    TEST,
    backup / "test_voice_bridge.py",
)

print(
    "✅ Backup:",
    backup,
)


# ============================================================
# VOICE BRIDGE
# ============================================================

text = BRIDGE.read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------
# Adiciona expansor
# ------------------------------------------------------------

if "def expand_expert_question(" not in text:

    marker = '''def reset_voice_context():
'''

    expansion = r'''
def expand_expert_question(
    text: str,
):
    """
    Expande formas naturais/curtas sem substituir
    a pergunta original.

    Serve apenas para melhorar o retrieval.

    Exemplo:
        "senha do wifi do t800"

    passa a carregar também termos como:
        credencial
        Wi-Fi
        rede interna
        password
        EngineAI
        T800
    """

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
        )
    )

    has_t800 = (
        "t800" in q
        or "t 800" in q
        or "t-800" in q
        or " 800" in f" {q}"
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
            "senha, password e credenciais.\\n\\n"
            "Pergunta original do usuário:\\n"
            + text
        )

    return text


'''

    if marker not in text:
        raise RuntimeError(
            "Não encontrei reset_voice_context()."
        )

    text = text.replace(
        marker,
        expansion + marker,
        1,
    )


# ------------------------------------------------------------
# Usa a expansão no Expert
# ------------------------------------------------------------

old = '''    effective_question = (
        text
    )
'''

new = '''    effective_question = (
        expand_expert_question(
            text
        )
    )
'''

if old in text:

    text = text.replace(
        old,
        new,
        1,
    )

elif "expand_expert_question(" not in text.split(
    "effective_question",
    1
)[-1]:

    raise RuntimeError(
        "Não encontrei effective_question."
    )


BRIDGE.write_text(
    text,
    encoding="utf-8",
)

print(
    "✅ Expansão de consulta instalada."
)


# ============================================================
# TESTA SEM EXPOR CREDENCIAL
# ============================================================

subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(BRIDGE),
    ],
    check=True,
)

print(
    "✅ Sintaxe OK."
)


print()
print(
    "🧪 Testando expansão..."
)

sys.path.insert(
    0,
    str(SERVER),
)

from app.core.voice_bridge import (
    expand_expert_question,
)


question = (
    "qual a senha do wifi do t800"
)

expanded = expand_expert_question(
    question
)

if expanded == question:

    raise RuntimeError(
        "A expansão não foi ativada."
    )

required = [
    "credenciais",
    "Wi-Fi",
    "EngineAI",
    "T800",
]

for term in required:

    if term.lower() not in expanded.lower():

        raise RuntimeError(
            f"Termo ausente: {term}"
        )

print(
    "✅ Pergunta natural expandida."
)

print()
print(
    "Consulta original:"
)

print(
    question
)

print()
print(
    "Consulta enviada ao ExpertAgent:"
)

print(
    expanded
)

print()
print(
    "✅ PATCH CONCLUÍDO."
)
