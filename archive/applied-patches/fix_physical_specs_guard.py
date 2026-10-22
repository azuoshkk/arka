from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "robot-server"

EXPERT = SERVER / "app/agents/expert.py"
TEST = SERVER / "test_physical_specs_guard.py"


# ============================================================
# BACKUP
# ============================================================

stamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

backup = (
    ROOT
    / "backups"
    / f"before_physical_specs_guard_{stamp}"
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
# 1. TERMOS DE ESPECIFICAÇÃO FÍSICA
# ============================================================

if "PHYSICAL_LOAD_TERMS = (" not in text:

    marker = "\ndef normalize("

    insert = r'''

PHYSICAL_LOAD_TERMS = (
    "payload",
    "load capacity",
    "carrying capacity",
    "maximum load",
    "max load",
    "capacidade de carga",
    "carga maxima",
    "carga máxima",
    "carga util",
    "carga útil",
    "peso maximo suporta",
    "peso máximo suporta",
)

PHYSICAL_SPEC_TERMS = (
    "peso",
    "weight",
    "payload",
    "carga",
    "load",
    "torque",
    "altura",
    "height",
    "velocidade",
    "speed",
    "autonomia",
    "runtime",
    "battery life",
)

AUXILIARY_EQUIPMENT_TERMS = (
    "guindaste",
    "crane",
    "hoist",
    "talha",
    "lifting equipment",
    "equipamento de içamento",
    "equipamento de suporte",
    "support equipment",
    "support stand",
    "bancada",
    "bench",
    "carrinho",
    "trolley",
)

COMPONENT_LOAD_TERMS = (
    "hand",
    "mão",
    "mao",
    "dexterous hand",
    "gripper",
    "garra",
    "arm",
    "braço",
    "braco",
    "end effector",
)


def is_general_payload_question(
    question,
):

    q = normalize(
        question
    )

    general_terms = (
        "peso maximo",
        "peso máximo",
        "quanto suporta",
        "quanto ele suporta",
        "carga maxima",
        "carga máxima",
        "capacidade de carga",
        "payload",
    )

    return any(
        term in q
        for term in general_terms
    )


def contains_direct_physical_load_evidence(
    result,
    question="",
):

    payload = (
        result.payload
        or {}
    )

    chunk = normalize(
        payload.get(
            "text",
            ""
        )
    )

    source = normalize(
        payload.get(
            "source",
            ""
        )
    )

    combined = (
        source
        + "\n"
        + chunk
    )

    # --------------------------------------------------------
    # Não aceitar capacidade de ferramenta/equipamento auxiliar
    # como se fosse uma especificação do robô.
    # --------------------------------------------------------

    if any(
        term in combined
        for term in AUXILIARY_EQUIPMENT_TERMS
    ):

        return False

    # --------------------------------------------------------
    # Precisa haver vocabulário explícito de carga/payload.
    # Peso do próprio robô NÃO é payload.
    # --------------------------------------------------------

    has_load_metric = any(
        term in combined
        for term in PHYSICAL_LOAD_TERMS
    )

    if not has_load_metric:

        return False

    # --------------------------------------------------------
    # Precisa estar explicitamente relacionado ao T800.
    # --------------------------------------------------------

    has_robot_reference = any(
        term in combined
        for term in (
            "t800",
            "t 800",
            "t-800",
            "engineai t800",
        )
    )

    if not has_robot_reference:

        return False

    # --------------------------------------------------------
    # Se a pergunta é sobre o robô inteiro, não aceitar
    # payload específico de mão/braço/componente como resposta.
    # --------------------------------------------------------

    if is_general_payload_question(
        question
    ):

        q = normalize(
            question
        )

        user_asked_component = any(
            term in q
            for term in COMPONENT_LOAD_TERMS
        )

        chunk_is_component = any(
            term in combined
            for term in COMPONENT_LOAD_TERMS
        )

        if (
            chunk_is_component
            and not user_asked_component
        ):

            return False

    return True

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
# 2. INTENT physical_load
# ============================================================

detect_start = text.find(
    "def detect_intents("
)

detect_end = text.find(
    "\ndef ",
    detect_start + 5,
)

if (
    detect_start == -1
    or detect_end == -1
):

    raise RuntimeError(
        "Não encontrei detect_intents()."
    )

detect_block = text[
    detect_start:
    detect_end
]


if '"physical_load"' not in detect_block:

    return_marker = "    return intents\n"

    addition = r'''
    if any(
        term in q
        for term in (
            "payload",
            "capacidade de carga",
            "carga maxima",
            "carga máxima",
            "peso maximo",
            "peso máximo",
            "quanto suporta",
            "quanto ele suporta",
        )
    ):
        intents.add(
            "physical_load"
        )

'''

    if return_marker not in detect_block:

        raise RuntimeError(
            "return intents não encontrado."
        )

    new_block = detect_block.replace(
        return_marker,
        addition + return_marker,
        1,
    )

    text = (
        text[:detect_start]
        + new_block
        + text[detect_end:]
    )


# ============================================================
# 3. SUPPORT GUARD
# ============================================================

support_start = text.find(
    "def support_guard("
)

support_end = text.find(
    "\ndef ",
    support_start + 5,
)

if (
    support_start == -1
    or support_end == -1
):

    raise RuntimeError(
        "Não encontrei support_guard()."
    )

support_block = text[
    support_start:
    support_end
]


if '"physical_load"' not in support_block:

    # Logo depois da detecção das intents.
    marker = '''    intents = detect_intents(
        question
    )
'''

    addition = '''    intents = detect_intents(
        question
    )

    # ========================================================
    # ESPECIFICAÇÕES FÍSICAS / CARGA
    #
    # Só permite resposta numérica se houver evidência
    # explicitamente atribuída ao T800.
    # ========================================================

    if "physical_load" in intents:

        return any(
            contains_direct_physical_load_evidence(
                result,
                question,
            )
            for result in results
        )
'''

    if marker not in support_block:

        raise RuntimeError(
            "intents em support_guard não encontrado."
        )

    new_block = support_block.replace(
        marker,
        addition,
        1,
    )

    text = (
        text[:support_start]
        + new_block
        + text[support_end:]
    )


# ============================================================
# 4. PROMPT — PROÍBE INFERÊNCIA DE SPECS
# ============================================================

prompt_marker = '''Use somente fatos explicitamente presentes
no conteúdo das fontes.
'''

prompt_rule = '''Use somente fatos explicitamente presentes
no conteúdo das fontes.

REGRAS CRÍTICAS PARA ESPECIFICAÇÕES FÍSICAS:

- Nunca transforme o peso do próprio robô em capacidade de carga.
- Nunca transforme a capacidade de um guindaste, talha, bancada,
  suporte, carrinho ou equipamento auxiliar em capacidade do T800.
- Nunca transforme o payload de uma mão, braço, garra ou componente
  em payload do robô inteiro.
- Um valor numérico de payload/carga só pode ser afirmado quando
  a fonte atribuir explicitamente essa capacidade ao T800 no mesmo
  contexto.
- Se a fonte não especificar claramente o escopo da capacidade,
  responda que a documentação disponível não confirma essa informação.
'''

if (
    "Nunca transforme a capacidade de um guindaste"
    not in text
):

    if prompt_marker not in text:

        raise RuntimeError(
            "Prompt principal não encontrado."
        )

    text = text.replace(
        prompt_marker,
        prompt_rule,
        1,
    )


EXPERT.write_text(
    text,
    encoding="utf-8",
)

print(
    "✅ Guard de especificações físicas instalado."
)


# ============================================================
# 5. TESTE
# ============================================================

TEST.write_text(
r'''from types import SimpleNamespace

from app.agents.expert import (
    answer,
    detect_intents,
    contains_direct_physical_load_evidence,
)


QUESTION = (
    "Qual o peso máximo que o T800 suporta?"
)


def fake_result(text):

    return SimpleNamespace(
        payload={
            "text": text,
            "source": "teste.txt",
        },
        score=0.9,
    )


def check(condition, message):

    if not condition:

        raise AssertionError(
            message
        )


def main():

    # --------------------------------------------------------
    # Intent
    # --------------------------------------------------------

    intents = detect_intents(
        QUESTION
    )

    check(
        "physical_load"
        in intents,

        "Intent physical_load não detectada."
    )

    # --------------------------------------------------------
    # GUINDASTE NÃO PODE VIRAR PAYLOAD
    # --------------------------------------------------------

    crane = fake_result(
        "Para movimentação do T800, "
        "utilize um guindaste com capacidade "
        "de 150 kg."
    )

    check(
        not contains_direct_physical_load_evidence(
            crane,
            QUESTION,
        ),

        "ERRO: capacidade do guindaste "
        "foi aceita como payload."
    )

    # --------------------------------------------------------
    # PESO DO ROBÔ NÃO É PAYLOAD
    # --------------------------------------------------------

    robot_mass = fake_result(
        "O T800 possui peso aproximado "
        "de 84,5 kg."
    )

    check(
        not contains_direct_physical_load_evidence(
            robot_mass,
            QUESTION,
        ),

        "ERRO: peso do robô foi tratado "
        "como capacidade de carga."
    )

    # --------------------------------------------------------
    # PAYLOAD DA MÃO NÃO É PAYLOAD DO ROBÔ
    # --------------------------------------------------------

    hand = fake_result(
        "A dexterous hand do T800 possui "
        "payload de 5 kg."
    )

    check(
        not contains_direct_physical_load_evidence(
            hand,
            QUESTION,
        ),

        "ERRO: payload da mão virou "
        "payload geral do T800."
    )

    # --------------------------------------------------------
    # EVIDÊNCIA EXPLÍCITA SERIA ACEITA
    # --------------------------------------------------------

    direct = fake_result(
        "The T800 robot has a maximum "
        "load capacity of 20 kg."
    )

    check(
        contains_direct_physical_load_evidence(
            direct,
            QUESTION,
        ),

        "Evidência explícita válida "
        "foi rejeitada."
    )

    print(
        "✅ Guard unitário passou."
    )

    # --------------------------------------------------------
    # TESTE RAG REAL
    # --------------------------------------------------------

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

    # O erro conhecido nunca mais pode voltar.
    forbidden = (
        "150 kg"
    )

    check(
        forbidden not in response,

        "REGRESSÃO CRÍTICA: "
        "Arka voltou a afirmar 150 kg."
    )

    print(
        "✅ RAG não afirmou 150 kg."
    )

    print(
        "PASS: physical specs guard"
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
    "PATCH CONCLUÍDO."
)
