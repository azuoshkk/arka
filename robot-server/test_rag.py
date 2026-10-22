from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time

from datetime import datetime
from pathlib import Path

import requests

from app.agents.expert import answer
from app import config as app_config


ROOT = Path(__file__).resolve().parent

CASES_FILE = ROOT / "tests" / "rag_cases.json"

RESULTS_ROOT = ROOT / "test_results"
RUNS_ROOT = RESULTS_ROOT / "runs"

BACKUP_ROOT = ROOT / "backups" / "rag_pass"

REFUSAL = (
    "não encontrei essa informação "
    "na documentação disponível"
)

CODE_FILES = [
    Path("app/config.py"),
    Path("app/knowledge/loaders.py"),
    Path("app/knowledge/chunker.py"),
    Path("app/knowledge/embedder.py"),
    Path("app/knowledge/vector_store.py"),
    Path("app/knowledge/ingest.py"),
    Path("app/agents/expert.py"),
    Path("ask.py"),
    Path("test_rag.py"),
    Path("tests/rag_cases.json"),
]


def norm(value):

    return (
        (value or "")
        .lower()
        .replace("\n", " ")
    )


def sha256_file(path):

    h = hashlib.sha256()

    with path.open("rb") as handle:

        while True:

            data = handle.read(
                1024 * 1024
            )

            if not data:
                break

            h.update(data)

    return h.hexdigest()


def get_git_commit():

    try:

        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )

        if result.returncode == 0:
            return result.stdout.strip()

    except Exception:
        pass

    return None


def qdrant_status():

    url = getattr(
        app_config,
        "QDRANT_URL",
        "http://127.0.0.1:6333",
    ).rstrip("/")

    collection = getattr(
        app_config,
        "QDRANT_COLLECTION",
        "arka_knowledge",
    )

    try:

        response = requests.get(
            f"{url}/collections/{collection}",
            timeout=5,
        )

        response.raise_for_status()

        data = response.json()

        result = data.get(
            "result",
            {}
        )

        return {
            "ok": True,
            "status":
                result.get("status"),

            "points_count":
                result.get("points_count"),

            "vectors_count":
                result.get("vectors_count"),

            "collection":
                collection,
        }

    except Exception as exc:

        return {
            "ok": False,
            "error": str(exc),
            "collection": collection,
        }


def ollama_status():

    url = getattr(
        app_config,
        "OLLAMA_URL",
        "http://127.0.0.1:11434",
    ).rstrip("/")

    try:

        response = requests.get(
            f"{url}/api/tags",
            timeout=5,
        )

        response.raise_for_status()

        data = response.json()

        models = [
            item.get("name")
            for item in data.get(
                "models",
                []
            )
        ]

        return {
            "ok": True,
            "models": models,
        }

    except Exception as exc:

        return {
            "ok": False,
            "error": str(exc),
        }


def environment():

    hashes = {}

    for relative in CODE_FILES:

        path = ROOT / relative

        if path.exists():

            hashes[str(relative)] = (
                sha256_file(path)
            )

    config_names = [
        "OLLAMA_URL",
        "LLM_MODEL",
        "EMBEDDING_MODEL",
        "QDRANT_URL",
        "QDRANT_COLLECTION",
        "TOP_K",
        "MIN_SCORE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
    ]

    config = {}

    for name in config_names:

        if hasattr(
            app_config,
            name
        ):
            config[name] = getattr(
                app_config,
                name
            )

    return {
        "timestamp":
            datetime.now().isoformat(),

        "hostname":
            platform.node(),

        "platform":
            platform.platform(),

        "python":
            sys.version,

        "git_commit":
            get_git_commit(),

        "config":
            config,

        "qdrant":
            qdrant_status(),

        "ollama":
            ollama_status(),

        "file_hashes":
            hashes,
    }


def load_cases():

    return json.loads(
        CASES_FILE.read_text(
            encoding="utf-8"
        )
    )


def source_hygiene(
    sources,
):

    problems = []

    for source in sources:

        name = norm(
            source.get(
                "source"
            )
        )

        path = norm(
            source.get(
                "path"
            )
        )

        if (
            "rag_ready.md" in name
            or "rag_ready.md" in path
        ):
            problems.append(
                "RAG_READY.md apareceu "
                "como fonte."
            )

        if "00_index" in path:

            problems.append(
                "Arquivo de 00_INDEX "
                "apareceu como fonte."
            )

    return problems


def evaluate(
    case,
    result,
):

    response = (
        result.get(
            "answer",
            ""
        )
        or ""
    )

    sources = (
        result.get(
            "sources",
            []
        )
        or []
    )

    response_norm = norm(
        response
    )

    failures = []
    warnings = []
    infos = []

    if not response.strip():

        failures.append(
            "Resposta vazia."
        )

    refused = (
        REFUSAL
        in response_norm
    )

    if case.get(
        "must_refuse"
    ):

        if not refused:

            failures.append(
                "A pergunta deveria ser "
                "recusada por falta de "
                "evidência."
            )

    if case.get(
        "must_answer"
    ):

        if refused:

            failures.append(
                "A pergunta deveria ser "
                "respondida, mas houve "
                "recusa."
            )

    expected = case.get(
        "expected_any",
        [],
    )

    if expected and not refused:

        if not any(
            norm(term)
            in response_norm
            for term in expected
        ):

            warnings.append(
                "Nenhum termo esperado "
                "apareceu na resposta."
            )

    for forbidden in case.get(
        "forbidden_any",
        [],
    ):

        if (
            norm(forbidden)
            in response_norm
        ):

            failures.append(
                "Conteúdo proibido apareceu: "
                f"{forbidden}"
            )

    failures.extend(
        source_hygiene(
            sources
        )
    )

    if (
        case.get("must_answer")
        and not refused
        and not sources
    ):

        warnings.append(
            "Resposta sem fontes."
        )

    preferred = {
        item.upper()
        for item
        in case.get(
            "preferred_categories",
            []
        )
    }

    if preferred and sources:

        actual = {
            (
                source.get(
                    "category"
                )
                or ""
            ).upper()

            for source
            in sources
        }

        matched = (
            preferred
            & actual
        )

        infos.append(
            "Categorias encontradas: "
            + ", ".join(
                sorted(
                    actual
                    - {""}
                )
            )
        )

        if not matched:

            warnings.append(
                "Nenhuma categoria "
                "preferencial apareceu."
            )

    if failures:

        status = "FAIL"

    elif warnings:

        status = "WARN"

    else:

        status = "PASS"

    return {
        "status":
            status,

        "failures":
            failures,

        "warnings":
            warnings,

        "infos":
            infos,

        "refused":
            refused,
    }


def run_case(case):

    started = time.perf_counter()

    try:

        result = answer(
            question=
                case["question"],

            project="t800",
        )

        evaluation = evaluate(
            case,
            result,
        )

        error = None

    except Exception as exc:

        result = {
            "answer": "",
            "sources": [],
        }

        evaluation = {
            "status": "FAIL",
            "failures": [
                "Exceção durante execução."
            ],
            "warnings": [],
            "infos": [],
            "refused": False,
        }

        error = repr(exc)

    duration = (
        time.perf_counter()
        - started
    )

    return {
        "id":
            case["id"],

        "name":
            case["name"],

        "tags":
            case.get(
                "tags",
                []
            ),

        "question":
            case["question"],

        "duration_seconds":
            round(
                duration,
                3,
            ),

        "evaluation":
            evaluation,

        "answer":
            result.get(
                "answer",
                ""
            ),

        "sources":
            result.get(
                "sources",
                []
            ),

        "error":
            error,
    }


def write_reports(
    run_dir,
    env,
    results,
):

    counts = {
        "PASS": 0,
        "WARN": 0,
        "FAIL": 0,
    }

    for result in results:

        counts[
            result[
                "evaluation"
            ][
                "status"
            ]
        ] += 1

    payload = {
        "environment":
            env,

        "summary":
            counts,

        "tests":
            results,
    }

    (
        run_dir
        / "results.json"
    ).write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    md = [
        "# Arka RAG Regression",
        "",
        f"- PASS: **{counts['PASS']}**",
        f"- WARN: **{counts['WARN']}**",
        f"- FAIL: **{counts['FAIL']}**",
        "",
        "## Ambiente",
        "",
        f"- Host: `{env['hostname']}`",
        f"- Git: `{env.get('git_commit')}`",
        f"- Qdrant points: "
        f"`{env['qdrant'].get('points_count')}`",
        "",
        "## Resultados",
        "",
        "| # | Teste | Status | Tempo |",
        "|---:|---|---|---:|",
    ]

    for index, item in enumerate(
        results,
        start=1,
    ):

        status = item[
            "evaluation"
        ][
            "status"
        ]

        md.append(
            f"| {index} | "
            f"{item['name']} | "
            f"{status} | "
            f"{item['duration_seconds']:.1f}s |"
        )

    for index, item in enumerate(
        results,
        start=1,
    ):

        md.extend([
            "",
            f"## {index}. {item['name']}",
            "",
            f"**Status:** "
            f"{item['evaluation']['status']}",
            "",
            f"**Pergunta:** "
            f"{item['question']}",
            "",
            "### Resposta",
            "",
            item["answer"],
            "",
            "### Fontes",
            "",
        ])

        if item["sources"]:

            for source in item[
                "sources"
            ]:

                md.append(
                    "- "
                    f"{source.get('source')} "
                    f"| categoria="
                    f"{source.get('category')} "
                    f"| score="
                    f"{source.get('score', 0):.3f} "
                    f"| path="
                    f"{source.get('path')}"
                )

        else:

            md.append(
                "- Nenhuma."
            )

        notes = (
            item["evaluation"][
                "failures"
            ]
            + item["evaluation"][
                "warnings"
            ]
            + item["evaluation"][
                "infos"
            ]
        )

        if notes:

            md.extend([
                "",
                "### Observações",
                "",
            ])

            for note in notes:

                md.append(
                    f"- {note}"
                )

    (
        run_dir
        / "report.md"
    ).write_text(
        "\n".join(md)
        + "\n",
        encoding="utf-8",
    )

    txt = []

    for index, item in enumerate(
        results,
        start=1,
    ):

        txt.extend([
            "=" * 72,
            f"TESTE {index}: "
            f"{item['name']}",
            "=" * 72,
            f"Status: "
            f"{item['evaluation']['status']}",
            f"Tempo: "
            f"{item['duration_seconds']:.3f}s",
            "",
            "PERGUNTA:",
            item["question"],
            "",
            "RESPOSTA:",
            item["answer"],
            "",
            "FONTES:",
        ])

        for source in item[
            "sources"
        ]:

            txt.append(
                f"- {source.get('source')} "
                f"| {source.get('category')} "
                f"| score="
                f"{source.get('score', 0):.3f} "
                f"| {source.get('path')}"
            )

        txt.append("")

    txt.extend([
        "=" * 72,
        "RESUMO",
        "=" * 72,
        f"PASS: {counts['PASS']}",
        f"WARN: {counts['WARN']}",
        f"FAIL: {counts['FAIL']}",
        "",
    ])

    (
        run_dir
        / "report.txt"
    ).write_text(
        "\n".join(txt),
        encoding="utf-8",
    )

    with (
        run_dir
        / "summary.csv"
    ).open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:

        writer = csv.writer(
            handle
        )

        writer.writerow([
            "id",
            "name",
            "status",
            "duration_seconds",
            "sources",
            "top_source",
            "top_score",
        ])

        for item in results:

            sources = item[
                "sources"
            ]

            writer.writerow([
                item["id"],
                item["name"],
                item[
                    "evaluation"
                ][
                    "status"
                ],
                item[
                    "duration_seconds"
                ],
                len(sources),
                (
                    sources[0].get(
                        "source"
                    )
                    if sources
                    else ""
                ),
                (
                    sources[0].get(
                        "score"
                    )
                    if sources
                    else ""
                ),
            ])

    (
        run_dir
        / "environment.json"
    ).write_text(
        json.dumps(
            env,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return counts


def update_latest(
    run_dir,
    counts,
):

    shutil.copy2(
        run_dir / "report.md",
        RESULTS_ROOT
        / "latest_report.md",
    )

    shutil.copy2(
        run_dir / "results.json",
        RESULTS_ROOT
        / "latest_results.json",
    )

    summary = (
        f"PASS: {counts['PASS']}\n"
        f"WARN: {counts['WARN']}\n"
        f"FAIL: {counts['FAIL']}\n"
        f"RUN: {run_dir}\n"
    )

    (
        RESULTS_ROOT
        / "latest_summary.txt"
    ).write_text(
        summary,
        encoding="utf-8",
    )


def snapshot_pass(
    run_dir,
    env,
):

    timestamp = (
        run_dir.name
    )

    destination = (
        BACKUP_ROOT
        / timestamp
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    for relative in CODE_FILES:

        src = ROOT / relative

        if not src.exists():
            continue

        dst = (
            destination
            / relative
        )

        dst.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            src,
            dst,
        )

    reports_dst = (
        destination
        / "test_results"
    )

    reports_dst.mkdir(
        parents=True,
        exist_ok=True,
    )

    for filename in [
        "report.md",
        "report.txt",
        "results.json",
        "summary.csv",
        "environment.json",
    ]:

        shutil.copy2(
            run_dir / filename,
            reports_dst / filename,
        )

    (
        BACKUP_ROOT
        / "LATEST"
    ).write_text(
        str(destination)
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "✅ Snapshot aprovado salvo em:"
    )

    print(
        destination
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--tag",
        help=(
            "Executa somente testes "
            "com esta tag."
        ),
    )

    parser.add_argument(
        "--only",
        help=(
            "Executa somente teste cujo "
            "id/nome contenha o texto."
        ),
    )

    args = parser.parse_args()

    cases = load_cases()

    full_run = (
        args.tag is None
        and args.only is None
    )

    if args.tag:

        cases = [
            case
            for case in cases
            if args.tag
            in case.get(
                "tags",
                []
            )
        ]

    if args.only:

        needle = norm(
            args.only
        )

        cases = [
            case
            for case in cases
            if (
                needle
                in norm(
                    case["id"]
                )
                or needle
                in norm(
                    case["name"]
                )
            )
        ]

    if not cases:

        raise SystemExit(
            "Nenhum teste selecionado."
        )

    RESULTS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    RUNS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    BACKUP_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now()
        .strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
    )

    run_dir = (
        RUNS_ROOT
        / timestamp
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    env = environment()

    print()
    print("=" * 72)
    print("ARKA — RAG QUALITY PIPELINE")
    print("=" * 72)

    print(
        f"Testes selecionados: "
        f"{len(cases)}"
    )

    print(
        "Qdrant:",
        (
            "OK"
            if env["qdrant"][
                "ok"
            ]
            else "ERRO"
        ),
    )

    print(
        "Ollama:",
        (
            "OK"
            if env["ollama"][
                "ok"
            ]
            else "ERRO"
        ),
    )

    if not env["qdrant"]["ok"]:

        print()
        print(
            "❌ Qdrant indisponível:"
        )

        print(
            env["qdrant"].get(
                "error"
            )
        )

        raise SystemExit(1)

    if not env["ollama"]["ok"]:

        print()
        print(
            "❌ Ollama indisponível:"
        )

        print(
            env["ollama"].get(
                "error"
            )
        )

        raise SystemExit(1)

    results = []

    for index, case in enumerate(
        cases,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(cases)}] "
            f"{case['name']}"
        )

        result = run_case(
            case
        )

        results.append(
            result
        )

        status = (
            result[
                "evaluation"
            ][
                "status"
            ]
        )

        print(
            f"  → {status} "
            f"({result['duration_seconds']:.1f}s)"
        )

    counts = write_reports(
        run_dir,
        env,
        results,
    )

    update_latest(
        run_dir,
        counts,
    )

    print()
    print("=" * 72)
    print("RESUMO")
    print("=" * 72)

    print(
        f"PASS: {counts['PASS']}"
    )

    print(
        f"WARN: {counts['WARN']}"
    )

    print(
        f"FAIL: {counts['FAIL']}"
    )

    print()
    print(
        f"Relatório: "
        f"{run_dir / 'report.md'}"
    )

    # Snapshot automático somente quando:
    # - é bateria completa
    # - todos passaram
    if (
        full_run
        and counts["WARN"] == 0
        and counts["FAIL"] == 0
        and counts["PASS"]
        == len(cases)
    ):

        snapshot_pass(
            run_dir,
            env,
        )

    if counts["FAIL"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
