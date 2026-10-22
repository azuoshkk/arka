from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot-server"))
from app.agents.expert import (
    answer_stream,
)


QUESTIONS = [
    (
        "ROS2",
        "Como habilita os tópicos ROS2 do T800?"
    ),
    (
        "Diagnóstico",
        "Existe algum problema conhecido "
        "na integração do T800?"
    ),
]


for name, question in QUESTIONS:

    print()
    print(
        "=" * 64
    )

    print(
        name
    )

    print(
        question
    )

    print(
        "=" * 64
    )

    result = answer_stream(
        question,
        "t800",

        # Benchmark não imprime conteúdo.
        on_token=lambda token: None,
    )

    metrics = (
        result.get(
            "metrics",
            {}
        )
    )

    print(
        "Retrieval:",
        f"{metrics.get('retrieval', 0):.3f}s"
    )

    print(
        "Primeiro token:",
        (
            f"{metrics['first_token']:.3f}s"
            if metrics.get(
                "first_token"
            ) is not None
            else "---"
        )
    )

    print(
        "Total:",
        f"{metrics.get('total', 0):.3f}s"
    )

    print(
        "Fontes:",
        len(
            result.get(
                "sources",
                []
            )
        )
    )
