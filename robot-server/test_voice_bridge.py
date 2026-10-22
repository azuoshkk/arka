import app.core.voice_bridge as bridge


def check(
    condition,
    message,
):

    if not condition:
        raise AssertionError(
            message
        )


def main():

    original = (
        bridge.expert_answer
    )

    calls = []

    def fake_expert(
        question,
        project,
    ):

        calls.append(
            (
                question,
                project,
            )
        )

        return {
            "answer":
                "Resposta técnica de teste.",

            "sources": [
                {
                    "source":
                        "teste.txt"
                }
            ],
        }

    try:

        bridge.reset_voice_context()

        bridge.expert_answer = (
            fake_expert
        )

        # CHAT genérico

        chat = (
            bridge
            .prepare_voice_response(
                "Quanto é 15 vezes 7?"
            )
        )

        check(
            chat["route"]
            == "chat",

            "Matemática caiu no Expert."
        )

        check(
            len(calls) == 0,
            "CHAT consultou RAG."
        )

        # "800" + contexto técnico

        alias = (
            bridge
            .prepare_voice_response(
                "Qual a senha da "
                "internet do 800?"
            )
        )

        check(
            alias["route"]
            == "expert",

            "Alias 800 não caiu "
            "no Expert."
        )

        check(
            len(calls) == 1,
            "Alias 800 não consultou RAG."
        )

        # Follow-up técnico

        follow = (
            bridge
            .prepare_voice_response(
                "E qual arquivo "
                "configura isso?"
            )
        )

        check(
            follow["route"]
            == "expert",

            "Follow-up técnico "
            "perdeu contexto."
        )

        check(
            len(calls) == 2,
            "Follow-up não consultou RAG."
        )

        check(
            "Contexto da pergunta"
            in calls[-1][0],

            "Contexto técnico não "
            "foi enviado ao RAG."
        )

        # Volta ao chat

        normal = (
            bridge
            .prepare_voice_response(
                "Obrigado!"
            )
        )

        check(
            normal["route"]
            == "chat",

            "Obrigado ficou preso "
            "no Expert."
        )

        # Erro RAG não vira chat

        bridge.reset_voice_context()

        def broken_expert(
            question,
            project,
        ):

            raise RuntimeError(
                "falha simulada"
            )

        bridge.expert_answer = (
            broken_expert
        )

        failed = (
            bridge
            .prepare_voice_response(
                "Como funciona o "
                "ROS2 bridge do T800?"
            )
        )

        check(
            failed["route"]
            == "expert",

            "Falha Expert caiu "
            "no Chat."
        )

        check(
            failed["error"]
            is not None,

            "Erro não foi registrado."
        )

        print(
            "✅ CHAT normal"
        )

        print(
            "✅ alias 800 → EXPERT"
        )

        print(
            "✅ follow-up técnico"
        )

        print(
            "✅ saída do modo expert"
        )

        print(
            "✅ falha RAG protegida"
        )

        print(
            "PASS: voice bridge"
        )

    finally:

        bridge.expert_answer = (
            original
        )

        bridge.reset_voice_context()


if __name__ == "__main__":
    main()
