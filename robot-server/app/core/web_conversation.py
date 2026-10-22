"""Web transport adapter; routing, retrieval and guards remain in existing modules."""
import json
import re
import secrets
import threading
import requests
from app.config import OLLAMA_URL, LLM_MODEL
from app.agents.expert import answer_stream
from app.core.voice_bridge import prepare_voice_route

MODEL_LOCK = threading.Lock()
SYSTEM = '''Você é Arka, a assistente virtual.

REGRAS DE IDENTIDADE:
- Seu nome é Arka.
- Arka é a assistente virtual.
- Arcanjo é o nome comercial do robô T800.
- T800 é o identificador técnico interno do Arcanjo.
- Nunca diga que seu nome é Arcanjo.
- Quando falar de si mesma, diga Arka.
- Quando o usuário disser Arcanjo, ele está falando do robô, não da assistente.

REGRAS INSTITUCIONAIS:
- A única empresa que você deve mencionar nominalmente é a IPQ.
- Não mencione fabricantes, fornecedores ou outras empresas pelo nome.
- Se a documentação citar uma empresa externa, diga apenas "fabricante", "fornecedor" ou "documentação técnica", conforme o contexto.

Responda em português brasileiro. Use o histórico da conversa.
Arcanjo é o nome comercial do robô T800. Sempre diga Arcanjo, exceto em
nomes literais de arquivos, caminhos, comandos e identificadores técnicos.
Não invente informações internas nem diga que consultou documentos sem consultá-los.
Você conversa e explica; não executa comandos físicos do robô.'''

# Preserve code, URLs, paths and filenames containing the technical identifier.
LITERAL = re.compile(r'(```[\s\S]*?(?:```|$)|`[^`]*(?:`|$)|https?://\S+|\S*[/\\_.-]\S*\b[Tt]800\S*|\b[Tt]800[\w./\\-]+)')
def display_name(text):
    pieces = LITERAL.split(text)

    def public_text(piece):
        # T800 é apenas identificador interno.
        piece = re.sub(
            r'\bT[ -]?800\b',
            'Arcanjo',
            piece,
            flags=re.I,
        )

        # Não expor nomes de empresas externas.
        # IPQ continua sendo o único nome institucional público.
        piece = re.sub(
            r'\b(?:Engine\s*AI|EngineAI|Zhongqing|Chongqing)\b',
            'fabricante',
            piece,
            flags=re.I,
        )

        return piece

    return ''.join(
        piece if i % 2 else public_text(piece)
        for i, piece in enumerate(pieces)
    )


def public_sources(sources):
    # Only bibliographic metadata. Never return payload text, absolute paths or chunks.
    output = []
    for index, source in enumerate(sources[:12], 1):
        name = str(source.get('source') or 'Documento interno').replace('\\', '/').split('/')[-1][:200]
        page = source.get('page')
        output.append({'number': source.get('number', index), 'source': name,
                       'page': page if isinstance(page, (int, float)) else None})
    return output

def chat_stream(history, text, on_token, learned=None):
    from app.knowledge.text_learning import context
    with requests.post(f'{OLLAMA_URL}/api/chat', json={
        'model': LLM_MODEL, 'stream': True, 'think': False, 'keep_alive': -1,
        'messages': [{'role':'system','content':SYSTEM}] + ([{'role':'system','content':context(learned)}] if learned else []) + history + [{'role':'user','content':text}],
        'options': {'num_ctx':4096, 'temperature':0.3, 'num_predict':600},
    }, stream=True, timeout=(5, 180)) as response:
        response.raise_for_status()
        parts = []
        for line in response.iter_lines():
            if not line: continue
            data = json.loads(line)
            if data.get('error'): raise RuntimeError('Ollama não concluiu a resposta.')
            token = data.get('message', {}).get('content', '')
            if token:
                parts.append(token)
                on_token(token)
    return {'answer': ''.join(parts), 'sources': []}

def respond(session, text, emit, cancelled, knowledge=False):
    raw, emitted = '', 0
    def on_token(token):
        nonlocal raw, emitted
        if cancelled.is_set(): raise InterruptedError('Cliente desconectado')
        raw += token
        visible = display_name(raw)
        # Keep a tail so split identifiers and code delimiters are never partially renamed.
        cut = visible.rfind(' ', emitted, max(emitted, len(visible)-128))
        if cut > emitted:
            emit('token', {'text': visible[emitted:cut+1]})
            emitted = cut+1
    with MODEL_LOCK:
        if cancelled.is_set(): raise InterruptedError('Cliente desconectado')
        plan = prepare_voice_route(text, context=session.context)
        emit('route', {'route': plan['route'].upper()})
        from app.knowledge.teaching import teachings
        from app.agents.expert import detect_intents
        from app.knowledge import text_learning
        fact = text_learning.teaching_fact(text)
        lesson=teachings.match(text) if plan['route']=='chat' else None
        if session.role=='viewer' and 'credentials' in detect_intents(text):
            result={'answer':'Essa consulta requer acesso de administrador.','sources':[]}
            on_token(result['answer'])
        elif fact is not None:
            if session.role != 'admin':
                result={'answer':'Somente administradores podem guardar informações compartilhadas.','sources':[]}
            else:
                try:
                    text_learning.save(fact[:1000], fact, session.username or 'admin')
                    result={'answer':'Informação guardada no conhecimento compartilhado. Outras pessoas já podem perguntar sobre ela.','sources':[]}
                except ValueError as exc:
                    result={'answer':str(exc),'sources':[]}
                except Exception:
                    result={'answer':'Não consegui guardar a informação no RAG. Tente novamente; ainda não confirmei o aprendizado.','sources':[]}
            on_token(result['answer'])
        elif lesson:
            result={'answer':lesson['answer'],'sources':[{'number':1,'source':'Ensinamento revisado: '+lesson['question']}]}
            on_token(result['answer'])
        else:
            if plan['route'] == 'expert':
                # Technical answers keep the original retrieval and physical/credential guards.
                result = answer_stream(plan['question'], 't800', on_token=on_token)
            else:
                try: learned = text_learning.retrieve(text)
                except Exception: learned = []
                result = chat_stream(session.history, text, on_token, learned=learned)
                if learned:
                    result['sources'] = [{'number':i,'source':item['source']} for i,item in enumerate(learned,1)]
    answer = display_name(result.get('answer', '').strip())
    if not answer: raise RuntimeError('Resposta vazia.')
    if emitted < len(answer): emit('token', {'text':answer[emitted:]})
    sources = public_sources(result.get('sources', []))
    message_id = secrets.token_urlsafe(16)
    entry = {'id':message_id, 'text':answer, 'sources':sources, 'route':plan['route'].upper()}
    session.answers[message_id] = entry
    while len(session.answers) > 20: session.answers.pop(next(iter(session.answers)))
    session.history += [{'role':'user','content':text}, {'role':'assistant','content':answer}]
    # Keep whole exchanges inside the 4096 token context budget.
    while len(session.history) > 2 and (len(session.history) > 12 or sum(len(x['content']) for x in session.history) > 6500):
        del session.history[:2]
    # Generated answers are never indexed as new facts.
    learning_id = None
    learning_error = None

    # Log diagnóstico automático.
    try:
        from app.core.diagnostic_log import log_event

        retrieved = []

        if plan.get("route") == "expert":
            try:
                from app.agents.expert import retrieve

                for item in retrieve(
                    plan.get("question") or text,
                    "t800",
                ):
                    payload = item.payload or {}

                    retrieved.append({
                        "score": round(float(item.score), 6),
                        "source": payload.get("source"),
                        "page": payload.get("page"),
                        "category": payload.get("category"),
                        "document_id": payload.get("document_id"),
                        "text": str(payload.get("text", ""))[:700],
                    })

            except Exception as exc:
                retrieved = [{
                    "retrieval_log_error": repr(exc)
                }]

        log_event(
            type="conversation",
            user=getattr(session, "username", None),
            role=getattr(session, "role", None),

            question=text,
            routed_question=plan.get("question"),
            route=plan.get("route"),
            route_reason=plan.get("reason"),

            retrieved=retrieved,
            answer=answer,
            sources=sources,

            learning_id=learning_id,
            learning_saved=bool(learning_id),
            learning_error=learning_error,
        )

    except Exception:
        pass

    emit('answer', entry)
