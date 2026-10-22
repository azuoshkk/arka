import time
import json
import hashlib
import re
import unicodedata

import requests

from app.config import (
    OLLAMA_URL,
    LLM_MODEL,
    TOP_K,
    MIN_SCORE,
)

from app.knowledge.embedder import (
    embed_text,
)

from app.knowledge.vector_store import (
    search,
)


SYSTEM_PROMPT = """
Você é Arka, a assistente virtual.

REGRAS DE IDENTIDADE:
- Seu nome é Arka.
- Arka é a assistente virtual.
- Arcanjo é o nome comercial do robô T800.
- T800 é o identificador técnico interno do Arcanjo.
- Nunca diga que seu nome é Arcanjo.
- Quando falar de si mesma, diga Arka.
- Quando o usuário disser Arcanjo, ele está falando do robô, não da assistente.
O nome comercial do robô é Arcanjo; T800 é seu identificador interno.
Use Arcanjo na resposta, preservando T800 em nomes literais de arquivos,
caminhos, comandos e identificadores técnicos.

Responda exclusivamente com base nas evidências
presentes nas fontes recuperadas.

REGRAS:

1. Não invente fatos.

2. Não use conhecimento próprio para preencher
   informações ausentes.

3. Responda especificamente ao que foi perguntado.

4. Títulos e nomes de arquivos não são evidência
   de que um evento ou problema ocorreu.

5. Só afirme algo quando o conteúdo de pelo menos
   uma fonte sustentar explicitamente a afirmação.

6. Não misture componentes diferentes apenas
   porque possuem nomes semelhantes.

7. ros2_bridge do SDK nativo,
   ros2_websocket_bridge do dashboard e gateways
   devem ser tratados como componentes distintos,
   salvo quando a documentação estabelecer relação.

8. Quando a pergunta for sobre problemas, falhas,
   bugs ou diagnósticos, não responda usando
   especificações gerais do robô.

9. Se fizer inferência, escreva explicitamente:

   "Inferência: ..."

10. Se as fontes não forem suficientes, responda:

   "Não encontrei essa informação na documentação disponível."

11. Cite afirmações técnicas relevantes com
    [Fonte 1], [Fonte 2], etc.

12. Preserve nomes técnicos, caminhos, parâmetros,
    números, versões e comandos como documentados.

13. Responda em português brasileiro.
"""


STOPWORDS = {
    "como",
    "qual",
    "quais",
    "que",
    "dos",
    "das",
    "para",
    "com",
    "sem",
    "uma",
    "por",
    "pelo",
    "pela",
    "utilizado",
    "utilizada",
    "funciona",
    "funcionam",
    "relacionado",
    "relacionados",
    "estao",
    "esta",
    "sao",
    "t800",
    "engineai",
}


DIAGNOSTIC_TERMS = (
    "problema",
    "falha",
    "erro",
    "issue",
    "failure",
    "failed",
    "bug",
    "diagnost",
    "causa",
    "correc",
    "fix",
    "workaround",
    "instabilidade",
    "timeout",
    "offline",
    "nao funciona",
    "nao respondeu",
    "unable",
    "cannot",
)

PASSWORD_TERMS = (
    "senha",
    "password",
    "passwd",
    "passphrase",
    "credential",
    "credentials",
    "credencial",
    "credenciais",
    "pwd",
)

NETWORK_TERMS = (
    "wifi",
    "wi-fi",
    "ssid",
    "wireless",
    "network",
    "rede",
    "internet",
)


def contains_credential_evidence(
    result,
):

    payload = (
        result.payload
        or {}
    )

    text = normalize(
        payload.get(
            "text",
            ""
        )
    )

    has_password = any(
        term in text
        for term
        in PASSWORD_TERMS
    )

    has_network = any(
        term in text
        for term
        in NETWORK_TERMS
    )

    return (
        has_password
        and has_network
    )




PHYSICAL_LOAD_TERMS = (
    "payload",
    "load capacity",
    "carrying capacity",
    "maximum load",
    "max load",
    "capacidade de carga",
    "carga maxima",
    "carga máxima",
    "carga util",
    "carga útil",
    "peso maximo suporta",
    "peso máximo suporta",
)

PHYSICAL_SPEC_TERMS = (
    "peso",
    "weight",
    "payload",
    "carga",
    "load",
    "torque",
    "altura",
    "height",
    "velocidade",
    "speed",
    "autonomia",
    "runtime",
    "battery life",
)

AUXILIARY_EQUIPMENT_TERMS = (
    "guindaste",
    "crane",
    "hoist",
    "talha",
    "lifting equipment",
    "equipamento de içamento",
    "equipamento de suporte",
    "support equipment",
    "support stand",
    "bancada",
    "bench",
    "carrinho",
    "trolley",
)

COMPONENT_LOAD_TERMS = (
    "hand",
    "mão",
    "mao",
    "dexterous hand",
    "gripper",
    "garra",
    "arm",
    "braço",
    "braco",
    "end effector",
)


def is_general_payload_question(
    question,
):

    q = normalize(
        question
    )

    general_terms = (
        "peso maximo",
        "peso máximo",
        "quanto suporta",
        "quanto ele suporta",
        "carga maxima",
        "carga máxima",
        "capacidade de carga",
        "payload",
    )

    return any(
        term in q
        for term in general_terms
    )


def contains_direct_physical_load_evidence(
    result,
    question="",
):

    payload = (
        result.payload
        or {}
    )

    chunk = normalize(
        payload.get(
            "text",
            ""
        )
    )

    source = normalize(
        payload.get(
            "source",
            ""
        )
    )

    combined = (
        source
        + "\n"
        + chunk
    )

    # --------------------------------------------------------
    # Não aceitar capacidade de ferramenta/equipamento auxiliar
    # como se fosse uma especificação do robô.
    # --------------------------------------------------------

    if any(
        term in combined
        for term in AUXILIARY_EQUIPMENT_TERMS
    ):

        return False

    # --------------------------------------------------------
    # Precisa haver vocabulário explícito de carga/payload.
    # Peso do próprio robô NÃO é payload.
    # --------------------------------------------------------

    has_load_metric = any(
        term in combined
        for term in PHYSICAL_LOAD_TERMS
    )

    if not has_load_metric:

        return False

    # --------------------------------------------------------
    # Precisa estar explicitamente relacionado ao T800.
    # --------------------------------------------------------

    has_robot_reference = any(
        term in combined
        for term in (
            "t800",
            "t 800",
            "t-800",
            "engineai t800",
        )
    )

    if not has_robot_reference:

        return False

    # --------------------------------------------------------
    # Se a pergunta é sobre o robô inteiro, não aceitar
    # payload específico de mão/braço/componente como resposta.
    # --------------------------------------------------------

    if is_general_payload_question(
        question
    ):

        q = normalize(
            question
        )

        user_asked_component = any(
            term in q
            for term in COMPONENT_LOAD_TERMS
        )

        chunk_is_component = any(
            term in combined
            for term in COMPONENT_LOAD_TERMS
        )

        if (
            chunk_is_component
            and not user_asked_component
        ):

            return False

    return True


def normalize(value):

    value = value or ""

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    return value.lower()


def question_terms(question):

    tokens = re.findall(
        r"[a-z0-9_]+",
        normalize(question),
    )

    return {
        token
        for token in tokens
        if (
            len(token) >= 3
            and token not in STOPWORDS
        )
    }


def detect_intents(question):

    q = normalize(question)

    intents = set()

    if any(
        term in q
        for term in (
            "problema",
            "falha",
            "erro",
            "diagnost",
            "issue",
            "bug",
            "instabilidade",
        )
    ):
        intents.add(
            "diagnostics"
        )

    if (
        "ros2" in q
        or "ros 2" in q
        or "ros2_bridge" in q
    ):
        intents.add(
            "ros2"
        )

    if any(
        term in q
        for term in (
            "camera",
            "visao",
            "vision",
            "audio",
            "speech",
            "headfollow",
            "head follow",
        )
    ):
        intents.add(
            "vision_audio"
        )

    if any(
        term in q
        for term in (
            "hardware",
            "motor",
            "joint",
            "articulacao",
            "sensor",
            "lidar",
        )
    ):
        intents.add(
            "hardware"
        )

    has_password_term = any(
        term in q
        for term
        in PASSWORD_TERMS
    )

    has_network_term = any(
        term in q
        for term
        in NETWORK_TERMS
    )

    if (
        has_password_term
        and has_network_term
    ):
        intents.add(
            "credentials"
        )


    if any(
        term in q
        for term in (
            "payload",
            "capacidade de carga",
            "carga maxima",
            "carga máxima",
            "peso maximo",
            "peso máximo",
            "quanto suporta",
            "quanto ele suporta",
        )
    ):
        intents.add(
            "physical_load"
        )

    return intents


def importance_bonus(payload):

    importance = (
        payload.get(
            "importance",
            "MEDIUM",
        )
        or "MEDIUM"
    ).upper()

    return {
        "CRITICAL": 0.025,
        "HIGH": 0.012,
        "MEDIUM": 0.0,
        "LOW": -0.010,
    }.get(
        importance,
        0.0,
    )


def category_bonus(
    question,
    payload,
    intents,
):

    category = (
        payload.get(
            "category",
            ""
        )
        or ""
    ).upper()

    q = normalize(
        question
    )

    bonus = 0.0

    if "diagnostics" in intents:

        if category == "ISSUES_SOLUTIONS":
            bonus += 0.18

        elif category == "DIAGNOSTICS":
            bonus += 0.16

        elif category == "OFFICIAL_DOCS":
            bonus += 0.03

        else:
            bonus -= 0.10

    if "ros2" in intents:

        if category == "SOFTWARE_BRIDGE":
            bonus += 0.15

        elif category == "SOFTWARE_SDK":
            bonus += 0.11

        elif category == "ROBOT_CONFIG":
            bonus += 0.09

        elif category == "ARCHITECTURE":
            bonus += 0.03

        elif category == "SOFTWARE_DASHBOARD":

            if (
                "dashboard" in q
                or "websocket" in q
            ):
                bonus += 0.05
            else:
                bonus -= 0.06

    if "vision_audio" in intents:

        if category == "VISION_AUDIO":
            bonus += 0.12

        elif category == "SOFTWARE_GATEWAY":
            bonus += 0.08

    if "hardware" in intents:

        if category == "HARDWARE_REFERENCE":
            bonus += 0.12

        elif category == "ROBOT_CONFIG":
            bonus += 0.08

    if "credentials" in intents:

        if category == "OFFICIAL_DOCS":
            bonus += 0.14

        elif category == "ROBOT_CONFIG":
            bonus += 0.08

    return bonus


def lexical_bonus(
    question,
    payload,
    intents,
):

    terms = question_terms(
        question
    )

    source = normalize(
        payload.get(
            "source",
            ""
        )
    )

    path = normalize(
        payload.get(
            "package_path",
            ""
        )
    )

    text = normalize(
        payload.get(
            "text",
            ""
        )
    )

    haystack = (
        source
        + "\n"
        + path
        + "\n"
        + text
    )

    if not terms:
        return 0.0

    matched = sum(
        1
        for term in terms
        if term in haystack
    )

    bonus = min(
        (
            matched
            / len(terms)
        ) * 0.09,
        0.09,
    )

    if "ros2" in intents:

        if (
            "ros2_bridge_param"
            in haystack
        ):
            bonus += 0.07

        elif (
            "ros2_bridge"
            in haystack
        ):
            bonus += 0.06

        elif (
            "ros2" in haystack
            and "bridge" in haystack
        ):
            bonus += 0.04

    if "diagnostics" in intents:

        if any(
            term in text
            for term
            in DIAGNOSTIC_TERMS
        ):
            bonus += 0.08

    if "credentials" in intents:

        has_password = any(
            term in text
            for term
            in PASSWORD_TERMS
        )

        has_network = any(
            term in text
            for term
            in NETWORK_TERMS
        )

        if (
            has_password
            and has_network
        ):
            bonus += 0.24

        elif (
            has_password
            or has_network
        ):
            bonus += 0.06

        if (
            "technical_inquiries"
            in source
            or "technical_support"
            in source
        ):
            bonus += 0.08

    return bonus



def entity_bonus(
    question,
    payload,
):
    q = normalize(question)

    haystack = normalize(
        " ".join(
            [
                str(payload.get("source", "") or ""),
                str(payload.get("text", "") or ""),
                str(payload.get("package_path", "") or ""),
            ]
        )
    )

    bonus = 0.0

    if "totem arcanjo" in q:
        if "totem arcanjo" in haystack:
            bonus += 0.55
        elif "estacao arcanjo" in haystack:
            bonus += 0.35

    if "estacao arcanjo" in q:
        if "estacao arcanjo" in haystack:
            bonus += 0.55
        elif "totem arcanjo" in haystack:
            bonus += 0.25

    return bonus


def ranking_score(
    result,
    question,
    intents,
):

    payload = (
        result.payload
        or {}
    )

    return (
        result.score
        + importance_bonus(
            payload
        )
        + category_bonus(
            question,
            payload,
            intents,
        )
        + lexical_bonus(
            question,
            payload,
            intents,
        )
        + entity_bonus(
            question,
            payload,
        )
    )


def diversify(
    results,
    question,
    intents,
    limit,
):

    ranked = sorted(
        results,

        key=lambda result:
            ranking_score(
                result,
                question,
                intents,
            ),

        reverse=True,
    )

    selected = []

    per_source = {}

    seen_text = set()

    max_per_source = (
        4
        if "credentials" in intents
        else 2
    )

    for result in ranked:

        payload = (
            result.payload
            or {}
        )

        text = (
            payload.get(
                "text",
                ""
            )
            or ""
        )

        text_hash = hashlib.sha256(
            text.strip().encode(
                "utf-8"
            )
        ).hexdigest()

        if text_hash in seen_text:
            continue

        source_key = (
            payload.get(
                "package_path"
            )
            or payload.get(
                "path"
            )
            or payload.get(
                "source"
            )
            or "unknown"
        )

        if (
            per_source.get(
                source_key,
                0,
            )
            >= max_per_source
        ):
            continue

        seen_text.add(
            text_hash
        )

        per_source[
            source_key
        ] = (
            per_source.get(
                source_key,
                0,
            )
            + 1
        )

        selected.append(
            result
        )

        if len(selected) >= limit:
            break

    return selected


def contains_diagnostic_evidence(
    result,
):

    payload = (
        result.payload
        or {}
    )

    text = normalize(
        payload.get(
            "text",
            ""
        )
    )

    return any(
        term in text
        for term
        in DIAGNOSTIC_TERMS
    )


def retrieve(
    question,
    project,
):

    intents = detect_intents(
        question
    )

    focus = []

    q_normalized = normalize(question)

    # O produto conhecido informalmente como "Totem Arcanjo"
    # aparece na documentação como "Estação Arcanjo".
    if "totem arcanjo" in q_normalized:
        focus.append(
            "Procure também pela entidade Estação Arcanjo. "
            "Totem Arcanjo e Estação Arcanjo podem se referir "
            "ao mesmo equipamento neste contexto. "
            "Não use o nome do arquivo como evidência factual; "
            "use somente o conteúdo dos trechos recuperados."
        )

    if "diagnostics" in intents:

        focus.append(
            "Procure especificamente problemas, falhas, "
            "issues, erros, sintomas, diagnóstico, testes, "
            "causas, correções e limitações observadas."
        )

    if "ros2" in intents:

        focus.append(
            "Procure especificamente ros2_bridge do SDK "
            "nativo, ros2_bridge_param, arquivos de "
            "configuração ROS2, tópicos e nodes."
        )

    if "credentials" in intents:

        focus.append(
            "Procure especificamente informações explícitas "
            "de rede e autenticação: Wi-Fi, SSID, wireless, "
            "network, senha, password, credenciais e "
            "configuração de acesso relacionadas ao T800 "
            "e à EngineAI."
        )

    # T800 é somente um alias técnico de recuperação.
    # Nunca substitui "Arcanjo" na pergunta original.
    q_norm = normalize(question)

    robot_context = bool(
        "arcanjo" in q_norm
        and (
            any(intent in intents for intent in (
                "ros2",
                "credentials",
                "diagnostics",
                "physical_load",
            ))
            or any(term in q_norm for term in (
                "robo",
                "humanoide",
                "sdk",
                "firmware",
                "camera",
                "motor",
                "bateria",
                "ros2",
                "driver",
                "gateway",
                "dashboard",
                "wifi",
                "wi fi",
                "senha",
            ))
        )
    )

    alias_hint = (
        "Alias técnico adicional para recuperação: T800. "
        "Use esse alias somente para encontrar documentação do robô; "
        "não renomeie outras entidades que contenham Arcanjo."
        if robot_context
        else ""
    )

    query_text = (
        f"Projeto: {project}\n"
        f"Pergunta original: {question}\n"
        + ("\n" + alias_hint if alias_hint else "")
        + ("\n" + "\n".join(focus) if focus else "")
    )

    vector = embed_text(
        query_text
    )

    candidate_limit = max(
        TOP_K * 10,
        50,
    )

    credential_candidate_limit = max(
        TOP_K * 30,
        150,
    )

    if "credentials" in intents:

        candidate_limit = max(
            candidate_limit,
            credential_candidate_limit,
        )

    # ========================================================
    # DIAGNÓSTICO:
    # pesquisa direcionada em fontes que podem realmente
    # sustentar afirmações sobre problema/falha.
    # ========================================================

    if "diagnostics" in intents:

        results = search(
            vector=vector,

            project=project,

            limit=max(
                candidate_limit,
                80,
            ),

            allowed_access=(
                "public",
                "internal",
                "restricted",
            ),

            categories=(
                "DIAGNOSTICS",
                "ISSUES_SOLUTIONS",
                "OFFICIAL_DOCS",
            ),
        )

    else:

        results = search(
            vector=vector,

            project=project,

            limit=candidate_limit,

            allowed_access=(
                "public",
                "internal",
                "restricted",
            ),
        )

    credential_floor = max(
        0.30,
        MIN_SCORE - 0.20,
    )

    if "credentials" in intents:

        candidate_floor = (
            credential_floor
        )

    else:

        candidate_floor = max(
            0.45,
            MIN_SCORE - 0.08,
        )

    valid = [
        result
        for result in results
        if (
            result.score
            >= candidate_floor
        )
    ]

    # Para diagnóstico, categoria não basta.
    # O trecho precisa falar de problema/falha/etc.
    if "diagnostics" in intents:

        valid = [
            result
            for result in valid
            if contains_diagnostic_evidence(
                result
            )
        ]

    return diversify(
        results=valid,

        question=question,

        intents=intents,

        limit=TOP_K,
    )


def support_guard(
    question,
    results,
):

    if not results:
        return False

    intents = detect_intents(
        question
    )

    # ========================================================
    # ESPECIFICAÇÕES FÍSICAS / CARGA
    #
    # Só permite resposta numérica se houver evidência
    # explicitamente atribuída ao T800.
    # ========================================================

    if "physical_load" in intents:

        return any(
            contains_direct_physical_load_evidence(
                result,
                question,
            )
            for result in results
        )

    if "diagnostics" in intents:

        return any(
            contains_diagnostic_evidence(
                result
            )
            for result in results
        )

    if "credentials" in intents:

        return any(
            contains_credential_evidence(
                result
            )
            for result in results
        )

    if "ros2" in intents:

        for result in results:

            payload = (
                result.payload
                or {}
            )

            haystack = normalize(
                (
                    payload.get(
                        "source",
                        ""
                    )
                    or ""
                )
                + "\n"
                + (
                    payload.get(
                        "package_path",
                        ""
                    )
                    or ""
                )
                + "\n"
                + (
                    payload.get(
                        "text",
                        ""
                    )
                    or ""
                )
            )

            if (
                "ros2" in haystack
                and "bridge" in haystack
            ):
                return True

        return False

    return True



REFUSAL_MESSAGE = (
    "Não encontrei essa informação "
    "na documentação disponível."
)


def _generation_limit(
    question,
):

    intents = detect_intents(
        question
    )

    # Perguntas de credencial normalmente
    # exigem respostas muito pequenas.

    if "credentials" in intents:
        return 120

    # Diagnóstico pode exigir explicação.

    if "diagnostics" in intents:
        return 260

    # ROS2 geralmente precisa incluir
    # caminhos, parâmetros e tópicos.

    if "ros2" in intents:
        return 260

    if (
        "vision_audio" in intents
        or "hardware" in intents
    ):
        return 240

    return 220


def _prepare_answer(
    question,
    project,
):

    started = (
        time.perf_counter()
    )

    results = retrieve(
        question,
        project,
    )

    retrieval_seconds = (
        time.perf_counter()
        - started
    )

    if not support_guard(
        question,
        results,
    ):

        return {
            "ready":
                False,

            "answer":
                REFUSAL_MESSAGE,

            "sources":
                [],

            "user_prompt":
                None,

            "retrieval_seconds":
                retrieval_seconds,

            "num_predict":
                0,
        }

    intents = detect_intents(
        question
    )

    context_results = (
        results
    )

    # ========================================================
    # CREDENCIAIS
    #
    # Se já encontramos chunks que realmente contêm
    # evidência de rede + credencial, não mandamos
    # documentos genéricos para o Qwen.
    #
    # Além de ser mais preciso, isso reduz bastante
    # o tamanho do prompt.
    # ========================================================

    if "credentials" in intents:

        evidence = [
            result

            for result in results

            if contains_credential_evidence(
                result
            )
        ]

        if evidence:

            context_results = (
                evidence[:3]
            )

    context_parts = []
    sources = []

    for index, result in enumerate(
        context_results,
        start=1,
    ):

        payload = (
            result.payload
            or {}
        )

        source = payload.get(
            "source",
            "fonte desconhecida",
        )

        page = payload.get(
            "page"
        )

        category = payload.get(
            "category"
        )

        package_path = payload.get(
            "package_path"
        )

        start_line = payload.get(
            "start_line"
        )

        end_line = payload.get(
            "end_line"
        )

        label = (
            f"Fonte {index}: "
            f"{source}"
        )

        if page is not None:

            label += (
                f", página {page}"
            )

        if (
            start_line is not None
            and end_line is not None
        ):

            label += (
                f", linhas "
                f"{start_line}-"
                f"{end_line}"
            )

        # Não precisamos mandar caminhos enormes
        # ao modelo para toda pergunta.
        #
        # O caminho continua disponível no retorno
        # sources, mas não polui o contexto.

        metadata = []

        if category:

            metadata.append(
                f"Categoria: {category}"
            )

        chunk_text = (
            payload.get(
                "text",
                "",
            )
            or ""
        )

        context_parts.append(
            f"[{label}]\n"
            + "\n".join(
                metadata
            )
            + (
                "\n"
                if metadata
                else ""
            )
            + chunk_text
        )

        sources.append({
            "number":
                index,

            "source":
                source,

            "page":
                page,

            "score":
                result.score,

            "category":
                category,

            "path":
                package_path,

            "start_line":
                start_line,

            "end_line":
                end_line,
        })

    context = "\n\n".join(
        context_parts
    )

    user_prompt = f"""
PROJETO:
{project}

PERGUNTA:
{question}

FONTES RECUPERADAS:

{context}

Responda apenas à pergunta feita.

IDENTIDADE:
- Seu nome é Arka.
- Arka é a assistente virtual.
- Arcanjo é o nome comercial do robô.
- T800 é o modelo/identificador técnico interno do Arcanjo.
- Nunca diga que seu nome é Arcanjo.
- Quando falar de si mesma, use "Arka".
- Quando falar do robô, use "Arcanjo".
- Se o usuário disser "Arcanjo", ele está se referindo ao robô T800, não à assistente.

NOME COMERCIAL:
- O robô T800 deve ser chamado de "Arcanjo" na resposta ao usuário.
- T800 é o modelo/identificador técnico interno do Arcanjo.
- A assistente se chama Arka.
- Nunca chame a assistente de Arcanjo.
- Preserve "T800" apenas dentro de nomes de arquivos, caminhos,
  comandos, parâmetros ou identificadores técnicos que precisem
  permanecer literais.

Seja direto e conciso.
Para perguntas simples, prefira 1 a 3 parágrafos curtos.
Não repita a pergunta nem faça introduções desnecessárias.
Só dê explicações longas quando o usuário pedir detalhes.

Use somente fatos explicitamente presentes
no conteúdo das fontes.

REGRAS SOBRE FONTES E NOMES DE ARQUIVOS:
- O nome do arquivo é apenas metadado bibliográfico.
- Nunca use o nome do arquivo como evidência factual.
- Nunca conclua fatos a partir de palavras presentes somente no filename.
- Para afirmar algo, a informação precisa aparecer no conteúdo recuperado.
- Se o nome do arquivo disser uma coisa que não aparece no conteúdo, ignore essa parte do nome.
- "Totem Arcanjo" e "Estação Arcanjo" podem se referir ao mesmo equipamento neste contexto; quando a pergunta usar "Totem Arcanjo", procure evidência também por "Estação Arcanjo".

REGRAS CRÍTICAS PARA ESPECIFICAÇÕES FÍSICAS:

- Nunca transforme o peso do próprio robô em capacidade de carga.
- Nunca transforme a capacidade de um guindaste, talha, bancada,
  suporte, carrinho ou equipamento auxiliar em capacidade do T800.
- Nunca transforme o payload de uma mão, braço, garra ou componente
  em payload do robô inteiro.
- Um valor numérico de payload/carga só pode ser afirmado quando
  a fonte atribuir explicitamente essa capacidade ao T800 no mesmo
  contexto.
- Se a fonte não especificar claramente o escopo da capacidade,
  responda que a documentação disponível não confirma essa informação.

Não transforme nomes de arquivos ou títulos
em fatos.

Se a pergunta for sobre problemas ou falhas,
não apresente especificações gerais do robô.

Para cada problema mencionado, explique o
sintoma ou evidência documentada e, quando
disponível, como ele foi diagnosticado.

Não misture ros2_bridge do SDK nativo com
ros2_websocket_bridge ou gateways do dashboard
sem evidência explícita.

Cite afirmações técnicas com [Fonte N].

Se houver inferência, marque:
"Inferência:".

Se não houver evidência suficiente, responda:

"Não encontrei essa informação na documentação disponível."
"""

    return {
        "ready":
            True,

        "answer":
            None,

        "sources":
            sources,

        "user_prompt":
            user_prompt,

        "retrieval_seconds":
            retrieval_seconds,

        "num_predict":
            _generation_limit(
                question
            ),
    }


def _ollama_messages(
    user_prompt,
):

    return [
        {
            "role":
                "system",

            "content":
                SYSTEM_PROMPT,
        },
        {
            "role":
                "user",

            "content":
                user_prompt,
        },
    ]


def answer(
    question,
    project,
):

    """
    Caminho tradicional.

    Mantido porque test_rag.py e os testes
    de regressão dependem desta função.
    """

    total_started = (
        time.perf_counter()
    )

    prepared = _prepare_answer(
        question,
        project,
    )

    if not prepared[
        "ready"
    ]:

        return {
            "answer":
                prepared["answer"],

            "sources":
                prepared["sources"],

            "metrics": {
                "retrieval":
                    prepared[
                        "retrieval_seconds"
                    ],

                "first_token":
                    None,

                "llm":
                    0.0,

                "total":
                    (
                        time.perf_counter()
                        - total_started
                    ),
            },
        }

    llm_started = (
        time.perf_counter()
    )

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                False,

            "think":
                False,

            "keep_alive":
                -1,

            "messages":
                _ollama_messages(
                    prepared[
                        "user_prompt"
                    ]
                ),

            "options": {
                "num_ctx": 4096,
                "temperature":
                    0.0,

                "num_predict":
                    prepared[
                        "num_predict"
                    ],
            },
        },

        timeout=300,
    )

    response.raise_for_status()

    data = response.json()

    finished = (
        time.perf_counter()
    )

    return {
        "answer":
            data[
                "message"
            ][
                "content"
            ],

        "sources":
            prepared[
                "sources"
            ],

        "metrics": {
            "retrieval":
                prepared[
                    "retrieval_seconds"
                ],

            "first_token":
                None,

            "llm":
                finished
                - llm_started,

            "total":
                finished
                - total_started,
        },
    }


def answer_stream(
    question,
    project,
    on_token=None,
):

    """
    Caminho usado pelo runtime da Arka.

    Faz o mesmo retrieval do answer(), mas o
    texto aparece conforme o Ollama gera tokens.
    """

    total_started = (
        time.perf_counter()
    )

    prepared = _prepare_answer(
        question,
        project,
    )

    if not prepared[
        "ready"
    ]:

        answer_text = (
            prepared[
                "answer"
            ]
        )

        if on_token:
            on_token(
                answer_text
            )

        finished = (
            time.perf_counter()
        )

        return {
            "answer":
                answer_text,

            "sources":
                prepared[
                    "sources"
                ],

            "metrics": {
                "retrieval":
                    prepared[
                        "retrieval_seconds"
                    ],

                "first_token":
                    (
                        finished
                        - total_started
                    ),

                "llm":
                    0.0,

                "total":
                    (
                        finished
                        - total_started
                    ),
            },
        }

    llm_started = (
        time.perf_counter()
    )

    first_token_seconds = (
        None
    )

    parts = []

    with requests.post(
        f"{OLLAMA_URL}/api/chat",

        json={
            "model":
                LLM_MODEL,

            "stream":
                True,

            "think":
                False,

            "keep_alive":
                -1,

            "messages":
                _ollama_messages(
                    prepared[
                        "user_prompt"
                    ]
                ),

            "options": {
                "num_ctx": 4096,
                "temperature":
                    0.0,

                "num_predict":
                    prepared[
                        "num_predict"
                    ],
            },
        },

        stream=True,

        timeout=(
            5,
            300,
        ),

    ) as response:

        response.raise_for_status()

        for raw_line in (
            response.iter_lines(
                decode_unicode=True
            )
        ):

            if not raw_line:
                continue

            data = json.loads(
                raw_line
            )

            token = (
                data
                .get(
                    "message",
                    {}
                )
                .get(
                    "content",
                    ""
                )
            )

            if not token:
                continue

            if (
                first_token_seconds
                is None
            ):

                first_token_seconds = (
                    time.perf_counter()
                    - total_started
                )

            parts.append(
                token
            )

            if on_token:

                on_token(
                    token
                )

    finished = (
        time.perf_counter()
    )

    answer_text = "".join(
        parts
    ).strip()

    if not answer_text:

        answer_text = (
            REFUSAL_MESSAGE
        )

        if on_token:
            on_token(
                answer_text
            )

    return {
        "answer":
            answer_text,

        "sources":
            prepared[
                "sources"
            ],

        "metrics": {
            "retrieval":
                prepared[
                    "retrieval_seconds"
                ],

            "first_token":
                first_token_seconds,

            "llm":
                finished
                - llm_started,

            "total":
                finished
                - total_started,
        },
    }
