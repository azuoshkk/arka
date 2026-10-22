from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

EXPERT = SERVER / "app/agents/expert.py"
TEST = SERVER / "test_credentials_rag.py"


stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_credentials_rag_{stamp}"
)

backup.mkdir(
    parents=True,
    exist_ok=True,
)

shutil.copy2(
    EXPERT,
    backup / "expert.py",
)

print(
    "✅ Backup:",
    backup,
)


text = EXPERT.read_text(
    encoding="utf-8"
)


# ============================================================
# 1. TERMOS DE CREDENCIAL
# ============================================================

if "PASSWORD_TERMS = (" not in text:

    marker = "\n\n\ndef normalize(value):"

    insert = r'''

PASSWORD_TERMS = (
    "senha",
    "password",
    "passwd",
    "passphrase",
    "credential",
    "credentials",
    "credencial",
    "credenciais",
    "pwd",
)

NETWORK_TERMS = (
    "wifi",
    "wi-fi",
    "ssid",
    "wireless",
    "network",
    "rede",
    "internet",
)


def contains_credential_evidence(
    result,
):

    payload = (
        result.payload
        or {}
    )

    text = normalize(
        payload.get(
            "text",
            ""
        )
    )

    has_password = any(
        term in text
        for term
        in PASSWORD_TERMS
    )

    has_network = any(
        term in text
        for term
        in NETWORK_TERMS
    )

    return (
        has_password
        and has_network
    )
'''

    if marker not in text:

        raise RuntimeError(
            "Não encontrei normalize()."
        )

    text = text.replace(
        marker,
        insert + marker,
        1,
    )


# ============================================================
# 2. INTENÇÃO CREDENTIALS
# ============================================================

if '"credentials"' not in text.split(
    "def detect_intents",
    1
)[1].split(
    "def importance_bonus",
    1
)[0]:

    old = '''    if any(
        term in q
        for term in (
            "hardware",
            "motor",
            "joint",
            "articulacao",
            "sensor",
            "lidar",
        )
    ):
        intents.add(
            "hardware"
        )

    return intents
'''

    new = '''    if any(
        term in q
        for term in (
            "hardware",
            "motor",
            "joint",
            "articulacao",
            "sensor",
            "lidar",
        )
    ):
        intents.add(
            "hardware"
        )

    has_password_term = any(
        term in q
        for term
        in PASSWORD_TERMS
    )

    has_network_term = any(
        term in q
        for term
        in NETWORK_TERMS
    )

    if (
        has_password_term
        and has_network_term
    ):
        intents.add(
            "credentials"
        )

    return intents
'''

    if old not in text:

        raise RuntimeError(
            "Bloco detect_intents não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 3. CATEGORY BONUS
# ============================================================

if 'if "credentials" in intents:' not in text.split(
    "def category_bonus",
    1
)[1].split(
    "def lexical_bonus",
    1
)[0]:

    old = '''    if "hardware" in intents:

        if category == "HARDWARE_REFERENCE":
            bonus += 0.12

        elif category == "ROBOT_CONFIG":
            bonus += 0.08

    return bonus
'''

    new = '''    if "hardware" in intents:

        if category == "HARDWARE_REFERENCE":
            bonus += 0.12

        elif category == "ROBOT_CONFIG":
            bonus += 0.08

    if "credentials" in intents:

        if category == "OFFICIAL_DOCS":
            bonus += 0.14

        elif category == "ROBOT_CONFIG":
            bonus += 0.08

    return bonus
'''

    if old not in text:

        raise RuntimeError(
            "Bloco category_bonus não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 4. LEXICAL BONUS
# ============================================================

lexical_section = text.split(
    "def lexical_bonus",
    1
)[1].split(
    "def ranking_score",
    1
)[0]

if 'if "credentials" in intents:' not in lexical_section:

    old = '''    if "diagnostics" in intents:

        if any(
            term in text
            for term
            in DIAGNOSTIC_TERMS
        ):
            bonus += 0.08

    return bonus
'''

    new = '''    if "diagnostics" in intents:

        if any(
            term in text
            for term
            in DIAGNOSTIC_TERMS
        ):
            bonus += 0.08

    if "credentials" in intents:

        has_password = any(
            term in text
            for term
            in PASSWORD_TERMS
        )

        has_network = any(
            term in text
            for term
            in NETWORK_TERMS
        )

        if (
            has_password
            and has_network
        ):
            bonus += 0.24

        elif (
            has_password
            or has_network
        ):
            bonus += 0.06

        if (
            "technical_inquiries"
            in source
            or "technical_support"
            in source
        ):
            bonus += 0.08

    return bonus
'''

    if old not in text:

        raise RuntimeError(
            "Bloco lexical_bonus não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 5. DIVERSIFY
# ============================================================

div_section = text.split(
    "def diversify",
    1
)[1].split(
    "def contains_diagnostic_evidence",
    1
)[0]

if "max_per_source" not in div_section:

    old = '''    seen_text = set()

    for result in ranked:
'''

    new = '''    seen_text = set()

    max_per_source = (
        4
        if "credentials" in intents
        else 2
    )

    for result in ranked:
'''

    if old not in text:

        raise RuntimeError(
            "Ponto diversify/set não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )

    old = '''            >= 2
        ):
            continue
'''

    new = '''            >= max_per_source
        ):
            continue
'''

    if old not in text:

        raise RuntimeError(
            "Limite por fonte não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 6. FOCUS NO RETRIEVE
# ============================================================

retrieve_section = text.split(
    "def retrieve",
    1
)[1].split(
    "def support_guard",
    1
)[0]

if 'if "credentials" in intents:' not in retrieve_section:

    old = '''    if "ros2" in intents:

        focus.append(
            "Procure especificamente ros2_bridge do SDK "
            "nativo, ros2_bridge_param, arquivos de "
            "configuração ROS2, tópicos e nodes."
        )

    query_text = (
'''

    new = '''    if "ros2" in intents:

        focus.append(
            "Procure especificamente ros2_bridge do SDK "
            "nativo, ros2_bridge_param, arquivos de "
            "configuração ROS2, tópicos e nodes."
        )

    if "credentials" in intents:

        focus.append(
            "Procure especificamente informações explícitas "
            "de rede e autenticação: Wi-Fi, SSID, wireless, "
            "network, senha, password, credenciais e "
            "configuração de acesso relacionadas ao T800 "
            "e à EngineAI."
        )

    query_text = (
'''

    if old not in text:

        raise RuntimeError(
            "Ponto focus/ros2 não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 7. MAIS CANDIDATOS
# ============================================================

if "credential_candidate_limit" not in text:

    old = '''    candidate_limit = max(
        TOP_K * 10,
        50,
    )

    # ========================================================
'''

    new = '''    candidate_limit = max(
        TOP_K * 10,
        50,
    )

    credential_candidate_limit = max(
        TOP_K * 30,
        150,
    )

    if "credentials" in intents:

        candidate_limit = max(
            candidate_limit,
            credential_candidate_limit,
        )

    # ========================================================
'''

    if old not in text:

        raise RuntimeError(
            "candidate_limit não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 8. FLOOR MAIS BAIXO PARA CREDENTIALS
# ============================================================

if "credential_floor" not in text:

    old = '''    candidate_floor = max(
        0.45,
        MIN_SCORE - 0.08,
    )
'''

    new = '''    credential_floor = max(
        0.30,
        MIN_SCORE - 0.20,
    )

    if "credentials" in intents:

        candidate_floor = (
            credential_floor
        )

    else:

        candidate_floor = max(
            0.45,
            MIN_SCORE - 0.08,
        )
'''

    if old not in text:

        raise RuntimeError(
            "candidate_floor não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


# ============================================================
# 9. SUPPORT GUARD
# ============================================================

support_section = text.split(
    "def support_guard",
    1
)[1].split(
    "def answer",
    1
)[0]

if 'if "credentials" in intents:' not in support_section:

    old = '''    if "ros2" in intents:

        for result in results:
'''

    new = '''    if "credentials" in intents:

        return any(
            contains_credential_evidence(
                result
            )
            for result in results
        )

    if "ros2" in intents:

        for result in results:
'''

    if old not in text:

        raise RuntimeError(
            "support_guard/ros2 não encontrado."
        )

    text = text.replace(
        old,
        new,
        1,
    )


EXPERT.write_text(
    text,
    encoding="utf-8",
)

print(
    "✅ ExpertAgent atualizado."
)


# ============================================================
# TESTE DE REGRESSÃO
# ============================================================

TEST.write_text(
r'''from app.agents.expert import (
    answer,
    retrieve,
    detect_intents,
    contains_credential_evidence,
)


QUESTION = (
    "qual a senha do wifi do t800"
)


def main():

    intents = detect_intents(
        QUESTION
    )

    if "credentials" not in intents:

        raise AssertionError(
            "Intent credentials não detectada."
        )

    results = retrieve(
        QUESTION,
        "t800",
    )

    evidence = [
        result
        for result in results
        if contains_credential_evidence(
            result
        )
    ]

    if not evidence:

        print(
            "❌ Nenhum chunk com evidência "
            "de Wi-Fi + credencial."
        )

        print()
        print(
            "Fontes recuperadas:"
        )

        for result in results:

            payload = (
                result.payload
                or {}
            )

            print(
                " -",
                payload.get(
                    "source",
                    "?"
                ),
                "| score:",
                round(
                    result.score,
                    4
                )
            )

        raise SystemExit(1)

    print(
        "✅ Chunk com evidência "
        "de credencial encontrado."
    )

    print(
        "Fonte:",
        (
            evidence[0].payload
            or {}
        ).get(
            "source",
            "?"
        )
    )

    # Testa a resposta sem imprimir
    # qualquer valor sensível.

    result = answer(
        QUESTION,
        "t800",
    )

    response = (
        result.get(
            "answer",
            ""
        )
        .lower()
    )

    refusal = (
        "não encontrei essa informação "
        "na documentação disponível"
    )

    if refusal in response:

        print(
            "❌ O LLM ainda recusou."
        )

        raise SystemExit(1)

    print(
        "✅ ExpertAgent respondeu "
        "com evidência."
    )

    print(
        "PASS: credentials RAG"
    )


if __name__ == "__main__":
    main()
''',
    encoding="utf-8",
)


subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(EXPERT),
        str(TEST),
    ],
    check=True,
)

print(
    "✅ Sintaxe OK."
)

print()
print(
    "Patch concluído."
)
