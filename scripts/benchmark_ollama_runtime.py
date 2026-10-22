from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot-server"))
import json
import subprocess
import time

import requests


OLLAMA = "http://127.0.0.1:11434"

CHAT_MODEL = "qwen3:8b"
EMBED_MODEL = "qwen3-embedding:0.6b"


def sec(value):
    if value is None:
        return 0.0

    return value / 1_000_000_000


def gpu_info():
    print()
    print("=" * 72)
    print("GPU")
    print("=" * 72)

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu="
                "name,memory.total,"
                "memory.used,memory.free",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        print(
            result.stdout.strip()
        )

    except Exception as exc:
        print(
            "nvidia-smi indisponível:",
            exc,
        )


def show_ps(label):
    print()
    print("-" * 72)
    print("OLLAMA PS:", label)
    print("-" * 72)

    response = requests.get(
        f"{OLLAMA}/api/ps",
        timeout=10,
    )

    response.raise_for_status()

    models = response.json().get(
        "models",
        [],
    )

    if not models:
        print("(nenhum modelo carregado)")
        return

    for model in models:
        print(
            "Modelo:",
            model.get("name"),
        )

        print(
            "  RAM total:",
            round(
                model.get(
                    "size",
                    0,
                )
                / 1024**3,
                2,
            ),
            "GB",
        )

        print(
            "  VRAM:",
            round(
                model.get(
                    "size_vram",
                    0,
                )
                / 1024**3,
                2,
            ),
            "GB",
        )


def embed(label, cpu=False):
    payload = {
        "model":
            EMBED_MODEL,

        "input":
            (
                "Projeto T800. "
                "Como habilitar os tópicos "
                "ROS2 bridge?"
            ),

        "keep_alive":
            "30m",
    }

    if cpu:
        payload["options"] = {
            "num_gpu": 0,
        }

    started = time.perf_counter()

    response = requests.post(
        f"{OLLAMA}/api/embed",
        json=payload,
        timeout=180,
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    if not response.ok:
        print()
        print(
            f"❌ {label}: "
            f"HTTP {response.status_code}"
        )

        print(
            response.text
        )

        return None

    data = response.json()

    result = {
        "elapsed":
            elapsed,

        "total":
            sec(
                data.get(
                    "total_duration"
                )
            ),

        "load":
            sec(
                data.get(
                    "load_duration"
                )
            ),
    }

    print()
    print(
        f"{label}:"
    )

    print(
        f"  wall: {elapsed:.3f}s"
    )

    print(
        f"  Ollama total: "
        f"{result['total']:.3f}s"
    )

    print(
        f"  LOAD: "
        f"{result['load']:.3f}s"
    )

    return result


def chat(label):
    payload = {
        "model":
            CHAT_MODEL,

        "stream":
            False,

        "think":
            False,

        "keep_alive":
            "30m",

        "messages": [
            {
                "role":
                    "user",

                "content":
                    "Responda somente OK.",
            }
        ],

        "options": {
            "temperature":
                0,

            "num_predict":
                4,

            # Contexto suficiente para a Arka
            # sem reservar memória exagerada.
            "num_ctx":
                4096,
        },
    }

    started = time.perf_counter()

    response = requests.post(
        f"{OLLAMA}/api/chat",
        json=payload,
        timeout=180,
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    response.raise_for_status()

    data = response.json()

    result = {
        "elapsed":
            elapsed,

        "total":
            sec(
                data.get(
                    "total_duration"
                )
            ),

        "load":
            sec(
                data.get(
                    "load_duration"
                )
            ),

        "prompt":
            sec(
                data.get(
                    "prompt_eval_duration"
                )
            ),

        "eval":
            sec(
                data.get(
                    "eval_duration"
                )
            ),
    }

    print()
    print(
        f"{label}:"
    )

    print(
        f"  wall: {elapsed:.3f}s"
    )

    print(
        f"  Ollama total: "
        f"{result['total']:.3f}s"
    )

    print(
        f"  LOAD: "
        f"{result['load']:.3f}s"
    )

    print(
        f"  prompt eval: "
        f"{result['prompt']:.3f}s"
    )

    print(
        f"  geração: "
        f"{result['eval']:.3f}s"
    )

    return result


def test_default():
    print()
    print()
    print("=" * 72)
    print(" TESTE A — EMBEDDING PADRÃO")
    print("=" * 72)

    results = {}

    results["e1"] = embed(
        "A1 embedding"
    )

    show_ps(
        "depois A1"
    )

    results["c1"] = chat(
        "A2 chat"
    )

    show_ps(
        "depois A2"
    )

    results["e2"] = embed(
        "A3 embedding novamente"
    )

    show_ps(
        "depois A3"
    )

    results["c2"] = chat(
        "A4 chat novamente"
    )

    show_ps(
        "depois A4"
    )

    return results


def test_cpu_embedding():
    print()
    print()
    print("=" * 72)
    print(
        " TESTE B — EMBEDDING FORÇADO NA CPU"
    )
    print("=" * 72)

    results = {}

    results["e1"] = embed(
        "B1 embedding CPU",
        cpu=True,
    )

    show_ps(
        "depois B1"
    )

    results["c1"] = chat(
        "B2 chat GPU"
    )

    show_ps(
        "depois B2"
    )

    results["e2"] = embed(
        "B3 embedding CPU novamente",
        cpu=True,
    )

    show_ps(
        "depois B3"
    )

    results["c2"] = chat(
        "B4 chat GPU novamente"
    )

    show_ps(
        "depois B4"
    )

    return results


def analyze(default, cpu):
    print()
    print()
    print("=" * 72)
    print(" ANÁLISE")
    print("=" * 72)

    try:
        default_embed_load = (
            default["e2"]["load"]
        )

        default_chat_load = (
            default["c2"]["load"]
        )

        cpu_embed = (
            cpu["e2"]["elapsed"]
        )

        cpu_chat_load = (
            cpu["c2"]["load"]
        )

    except (
        TypeError,
        KeyError,
    ):
        print(
            "Não foi possível gerar "
            "conclusão automática."
        )
        return

    print(
        "A / embedding LOAD:",
        f"{default_embed_load:.3f}s",
    )

    print(
        "A / chat LOAD:",
        f"{default_chat_load:.3f}s",
    )

    print(
        "B / embedding CPU:",
        f"{cpu_embed:.3f}s",
    )

    print(
        "B / chat LOAD:",
        f"{cpu_chat_load:.3f}s",
    )

    print()

    if (
        default_embed_load > 1.0
        and default_chat_load > 1.0
    ):
        print(
            "🔥 FORTE INDÍCIO DE MODEL SWAPPING."
        )

        print(
            "Embedding e chat estão sendo "
            "recarregados alternadamente."
        )

    elif (
        default_embed_load < 0.5
        and default_chat_load < 0.5
    ):
        print(
            "✅ Os modelos parecem permanecer "
            "carregados."
        )

        print(
            "O gargalo está mais no cálculo "
            "ou no prompt."
        )

    else:
        print(
            "⚠️ Resultado misto."
        )

    if (
        cpu_chat_load + 0.5
        < default_chat_load
    ):
        print()
        print(
            "🚀 Embedding na CPU parece "
            "preservar o qwen3:8b carregado."
        )

        print(
            "Esse será o próximo ajuste."
        )


def main():
    gpu_info()

    show_ps(
        "antes do benchmark"
    )

    default = test_default()

    cpu = test_cpu_embedding()

    analyze(
        default,
        cpu,
    )


if __name__ == "__main__":
    main()
