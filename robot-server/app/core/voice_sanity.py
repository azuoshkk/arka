from __future__ import annotations

import re
import unicodedata
from collections import Counter


def normalize(
    text: str,
) -> str:

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

    return value.lower()


def analyze_transcription(
    text: str,
    audio_metrics=None,
):

    audio_metrics = (
        audio_metrics
        or {}
    )

    normalized = normalize(
        text
    )

    tokens = re.findall(
        r"[a-z0-9]+",
        normalized,
    )

    active_time = float(
        audio_metrics.get(
            "tempo_fala_ativa"
        )
        or 0.0
    )

    # --------------------------------------------------------
    # Quase nenhum áudio + texto enorme
    # --------------------------------------------------------

    if (
        active_time > 0
        and active_time < 0.20
        and len(tokens) >= 8
    ):

        return {
            "suspicious":
                True,

            "reason":
                "texto incompatível "
                "com duração da fala",
        }

    # --------------------------------------------------------
    # Texto absurdo para áudio curto
    # --------------------------------------------------------

    if (
        active_time > 0
        and active_time < 1.0
        and len(tokens) >= 35
    ):

        return {
            "suspicious":
                True,

            "reason":
                "transcrição longa demais "
                "para áudio curto",
        }

    # --------------------------------------------------------
    # Loop de palavras
    # --------------------------------------------------------

    if len(tokens) >= 20:

        unique_ratio = (
            len(set(tokens))
            / len(tokens)
        )

        if unique_ratio < 0.22:

            return {
                "suspicious":
                    True,

                "reason":
                    "repetição excessiva "
                    "de palavras",
            }

        # Detecta repetição de pares/trincas.

        for size in (
            2,
            3,
            4,
        ):

            grams = [
                tuple(
                    tokens[
                        index:
                        index + size
                    ]
                )

                for index in range(
                    len(tokens)
                    - size
                    + 1
                )
            ]

            if not grams:
                continue

            _, frequency = (
                Counter(grams)
                .most_common(1)[0]
            )

            if frequency >= 6:

                return {
                    "suspicious":
                        True,

                    "reason":
                        "loop repetitivo "
                        "detectado",
                }

    return {
        "suspicious":
            False,

        "reason":
            None,
    }
