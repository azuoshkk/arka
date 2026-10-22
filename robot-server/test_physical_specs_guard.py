from types import SimpleNamespace

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
