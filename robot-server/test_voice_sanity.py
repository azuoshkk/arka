from app.core.voice_sanity import (
    analyze_transcription,
)


def check(
    condition,
    message,
):

    if not condition:
        raise AssertionError(
            message
        )


def main():

    hallucination = (
        (
            "O que é que "
            * 80
        ).strip()
    )

    result = analyze_transcription(
        hallucination,

        {
            "tempo_fala_ativa":
                0.128
        },
    )

    check(
        result["suspicious"],
        "Loop do Whisper não foi detectado."
    )

    result = analyze_transcription(
        "Oi!",

        {
            "tempo_fala_ativa":
                0.256
        },
    )

    check(
        not result["suspicious"],
        "Oi foi bloqueado."
    )

    result = analyze_transcription(
        "Qual a senha da internet do 800?",

        {
            "tempo_fala_ativa":
                2.347
        },
    )

    check(
        not result["suspicious"],
        "Pergunta normal foi bloqueada."
    )

    print(
        "✅ loop do Whisper detectado"
    )

    print(
        "✅ fala curta preservada"
    )

    print(
        "✅ pergunta normal preservada"
    )

    print(
        "PASS: voice sanity"
    )


if __name__ == "__main__":
    main()
