from __future__ import annotations

import requests

from app.config import (
    OLLAMA_URL,
    LLM_MODEL,
)

from app.agents.expert import (
    answer as expert_answer,
)

from app.core.router import (
    route_message,
)


CHAT_SYSTEM_PROMPT = """
Você é Arka, a assistente virtual.

REGRAS DE IDENTIDADE:
- Seu nome é Arka.
- Arka é a assistente virtual.
- Arcanjo é o nome comercial do robô T800.
- T800 é o identificador técnico interno do Arcanjo.
- Nunca diga que seu nome é Arcanjo.
- Quando falar de si mesma, diga Arka.
- Quando o usuário disser Arcanjo, ele está falando do robô, não da assistente.
Arcanjo é o nome comercial do robô T800. Preserve T800 apenas em nomes literais de arquivos, caminhos, comandos e identificadores técnicos.

Você é uma assistente virtual profissional,
objetiva e natural.

Responda em português brasileiro por padrão.

Para conversas gerais, responda normalmente.

Não finja ter consultado documentação interna
quando ela não foi consultada.

Não invente informações específicas da empresa,
do T800 ou dos projetos internos.
"""


def chat_answer(
    question: str,
):

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                False,

            "keep_alive": -1,

            "think":
                False,

            "messages": [
                {
                    "role":
                        "system",

                    "content":
                        CHAT_SYSTEM_PROMPT,
                },
                {
                    "role":
                        "user",

                    "content":
                        question,
                },
            ],

            "options": {
                "num_ctx": 4096,
                "temperature": 0.3,
                "num_predict": 500,
            },
        },

        timeout=300,
    )

    response.raise_for_status()

    data = response.json()

    return {
        "answer":
            data["message"]["content"],

        "sources": [],
    }


def respond(
    text: str,
    project: str = "t800",
):

    decision = route_message(
        text
    )

    if (
        decision["route"]
        == "expert"
    ):

        result = expert_answer(
            question=text,
            project=project,
        )

    else:

        result = chat_answer(
            text
        )

    return {
        "route":
            decision["route"],

        "route_reason":
            decision["reason"],

        "route_confidence":
            decision["confidence"],

        "answer":
            result["answer"],

        "sources":
            result.get(
                "sources",
                [],
            ),
    }
