from __future__ import annotations

import re
import unicodedata


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
}


PROJECT_TECH_TERMS = {
    "sdk",
    "dashboard",
    "telemetria",
    "websocket",
    "lidar",
    "camera",
    "speech",
    "audio",
    "motor",
    "articulacao",
    "joint",
    "pescoco",
    "neck",
    "bateria",
    "firmware",
    "driver",
    "parametro",
    "yaml",
    "docker",
    "dockerfile",
}


DOCUMENT_TERMS = {
    "documentacao",
    "manual",
    "arquivo",
    "arquivos",
    "relatorio",
    "fonte",
    "codigo",
    "configuracao",
}


CHAT_PATTERNS = (
    r"^(oi|ola|bom dia|boa tarde|boa noite)\b",
    r"^como voce esta",
    r"^tudo bem",
    r"^obrigad",
    r"^valeu",
)


# "800" sozinho NÃO basta.
#
# Queremos:
#   senha da internet do 800  -> EXPERT
#
# Mas:
#   quanto é 800 / 2?        -> CHAT

T800_ALIAS_CONTEXT = {
    "robo",
    "robot",
    "senha",
    "wifi",
    "wi-fi",
    "internet",
    "rede",
    "sdk",
    "ros2",
    "bridge",
    "driver",
    "camera",
    "motor",
    "bateria",
    "dashboard",
    "gateway",
    "firmware",
    "manual",
    "arquivo",
    "configuracao",
}


def normalize(text: str) -> str:

    value = unicodedata.normalize(
        "NFKD",
        text or "",
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    return value.lower().strip()


def has_t800_alias_context(
    q: str,
) -> bool:

    # Whisper pode produzir:
    # T800
    # T 800
    # T-800
    # 800

    has_alias = bool(
        re.search(
            r"\b(?:t[\s-]*800|800)\b",
            q,
        )
    )

    if not has_alias:
        return False

    # T800 explícito é sempre forte.

    if re.search(
        r"\bt[\s-]*800\b",
        q,
    ):

        return True

    # "800" puro precisa de contexto técnico.

    return any(
        term in q
        for term
        in T800_ALIAS_CONTEXT
    )


def heuristic_route(
    text: str,
):

    q = normalize(
        text
    )

    # --------------------------------------------------------
    # Social explícito
    # --------------------------------------------------------

    for pattern in CHAT_PATTERNS:

        if re.search(
            pattern,
            q,
        ):

            if not any(
                normalize(term) in q
                for term
                in STRONG_EXPERT_TERMS
            ):

                return {
                    "route":
                        "chat",

                    "reason":
                        "social_heuristic",

                    "confidence":
                        1.0,
                }

    # --------------------------------------------------------
    # T800 pronunciado/transcrito de maneiras diferentes
    # --------------------------------------------------------

    if has_t800_alias_context(q):

        return {
            "route":
                "expert",

            "reason":
                "t800_alias_context",

            "confidence":
                1.0,
        }

    # --------------------------------------------------------
    # Termos fortes
    # --------------------------------------------------------

    strong = [
        term
        for term
        in STRONG_EXPERT_TERMS

        if normalize(term) in q
    ]

    if strong:

        return {
            "route":
                "expert",

            "reason":
                "strong_project_term:"
                + ",".join(
                    strong[:3]
                ),

            "confidence":
                1.0,
        }

    # --------------------------------------------------------
    # Combinação de termos internos
    # --------------------------------------------------------

    tech_matches = sum(
        1
        for term
        in PROJECT_TECH_TERMS

        if normalize(term) in q
    )

    doc_matches = sum(
        1
        for term
        in DOCUMENT_TERMS

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
            "route":
                "expert",

            "reason":
                "technical_heuristic",

            "confidence":
                0.95,
        }

    return None


def route_message(
    text: str,
):

    normalized = normalize(text)

    # Entidades corporativas próprias.
    # Não são o robô T800, mas pertencem à base documental da IPQ.
    if (
        "totem arcanjo" in normalized
        or "estacao arcanjo" in normalized
    ):
        return {
            "route": "expert",
            "reason": "corporate_entity",
            "confidence": 1.0,
        }

    result = heuristic_route(
        text
    )

    if result:
        return result

    # Segurança do roteamento:
    # dúvida = chat.
    #
    # Assim conhecimento genérico nunca vai
    # parar acidentalmente no RAG do T800.

    return {
        "route":
            "chat",

        "reason":
            "conservative_default",

        "confidence":
            0.99,
    }
