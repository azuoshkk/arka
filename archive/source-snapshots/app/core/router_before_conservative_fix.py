from __future__ import annotations

import os
import re
import unicodedata

import requests

from app.config import OLLAMA_URL


ROUTER_MODEL = os.getenv(
    "ARKA_ROUTER_MODEL",
    "qwen3:0.6b",
)


STRONG_EXPERT_TERMS = {
    "t800",
    "engineai",
    "ros2",
    "ros 2",
    "ros2_bridge",
    "rc02",
    "mujoco",
    "odin2",
    "face follow",
    "headfollow",
    "head follow",
    "gateway de visao",
    "gateway de visão",
}


PROJECT_TECH_TERMS = {
    "sdk",
    "dashboard",
    "telemetria",
    "websocket",
    "lidar",
    "camera",
    "câmera",
    "speech",
    "audio",
    "áudio",
    "motor",
    "articulacao",
    "articulação",
    "joint",
    "pescoço",
    "neck",
    "bateria",
    "firmware",
    "driver",
    "parametro",
    "parâmetro",
    "yaml",
    "docker",
    "dockerfile",
}


DOCUMENT_TERMS = {
    "documentacao",
    "documentação",
    "manual",
    "arquivo",
    "arquivos",
    "relatorio",
    "relatório",
    "fonte",
    "codigo",
    "código",
    "configuracao",
    "configuração",
}


CHAT_PATTERNS = (
    r"^(oi|ola|olá|bom dia|boa tarde|boa noite)\b",
    r"^como voce esta",
    r"^como você está",
    r"^tudo bem",
    r"^obrigad",
    r"^valeu",
)


def normalize(text: str) -> str:

    value = unicodedata.normalize(
        "NFKD",
        text or "",
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    return value.lower().strip()


def heuristic_route(text: str):

    q = normalize(text)

    # --------------------------------------------------------
    # Conversa social evidente
    # --------------------------------------------------------

    for pattern in CHAT_PATTERNS:

        if re.search(
            pattern,
            q,
        ):

            if not any(
                normalize(term) in q
                for term in STRONG_EXPERT_TERMS
            ):

                return {
                    "route": "chat",
                    "reason":
                        "social_heuristic",
                    "confidence": 1.0,
                }

    # --------------------------------------------------------
    # Termos muito específicos do projeto
    # --------------------------------------------------------

    strong = [
        term
        for term in STRONG_EXPERT_TERMS
        if normalize(term) in q
    ]

    if strong:

        return {
            "route": "expert",
            "reason":
                "strong_project_term:"
                + ",".join(strong[:3]),
            "confidence": 1.0,
        }

    # --------------------------------------------------------
    # Pergunta claramente sobre conhecimento técnico interno
    # --------------------------------------------------------

    tech_matches = sum(
        1
        for term in PROJECT_TECH_TERMS
        if normalize(term) in q
    )

    doc_matches = sum(
        1
        for term in DOCUMENT_TERMS
        if normalize(term) in q
    )

    if (
        tech_matches >= 2
        or (
            tech_matches >= 1
            and doc_matches >= 1
        )
    ):

        return {
            "route": "expert",
            "reason":
                "technical_heuristic",
            "confidence": 0.95,
        }

    return None


def llm_route(text: str):

    prompt = f"""
Classifique a mensagem do usuário.

EXPERT:
Perguntas que precisam consultar documentação
interna dos projetos, especialmente T800,
EngineAI, SDK, ROS2, hardware do robô,
dashboard, gateway, câmera, telemetria,
configurações, diagnóstico ou arquivos internos.

CHAT:
Conversas gerais, cumprimentos, conhecimento
geral, programação genérica, matemática e
assuntos que não dependem da documentação
interna do projeto.

Mensagem:
{text}

Responda SOMENTE:

EXPERT

ou

CHAT
"""

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                ROUTER_MODEL,

            "stream":
                False,

            "think":
                False,

            "messages": [
                {
                    "role":
                        "user",

                    "content":
                        prompt,
                }
            ],

            "options": {
                "temperature": 0.0,
                "num_predict": 8,
            },
        },

        timeout=60,
    )

    response.raise_for_status()

    content = (
        response.json()
        ["message"]
        ["content"]
        .strip()
        .upper()
    )

    if "EXPERT" in content:

        route = "expert"

    else:

        route = "chat"

    return {
        "route": route,
        "reason":
            f"router_model:{ROUTER_MODEL}",
        "confidence": 0.7,
    }


def route_message(text: str):

    heuristic = heuristic_route(
        text
    )

    if heuristic:
        return heuristic

    try:
        return llm_route(text)

    except Exception as exc:

        # Falha do router nunca derruba a Arka.
        return {
            "route": "chat",
            "reason":
                f"router_fallback:{exc}",
            "confidence": 0.0,
        }
