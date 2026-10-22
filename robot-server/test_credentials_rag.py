from app.agents.expert import (
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
