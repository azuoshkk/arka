"""Arcanjo LAN API. Single process, bounded work, isolated sessions."""
import asyncio
from contextlib import asynccontextmanager
import ipaddress
import json
import logging
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

import requests
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.core import access
from app.sessions import SessionStore
from app.core.web_conversation import respond
from app.speech.web_audio import WebAudio
from app.config import OLLAMA_URL, LLM_MODEL, EMBEDDING_MODEL

ROOT = Path(__file__).resolve().parents[3]
store = SessionStore()
audio = WebAudio()
admission = threading.BoundedSemaphore(4)
log = logging.getLogger('arcanjo')
MAX_BODY = 12*1024*1024
NETWORKS = [ipaddress.ip_network(x.strip()) for x in os.getenv('ARCANJO_LAN_NETWORKS','127.0.0.0/8,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12').split(',')]
HOSTS = {'localhost','127.0.0.1', *os.getenv('ARCANJO_LAN_HOSTS','').split(',')}
readiness = {'models':'starting'}

def warmup():
    try:
        for endpoint, payload in [
            ('embed', {'model':EMBEDDING_MODEL,'input':'Arcanjo warmup','keep_alive':-1,'options':{'num_gpu':0}}),
            ('chat', {'model':LLM_MODEL,'stream':False,'think':False,'keep_alive':-1,
                      'messages':[{'role':'user','content':'Responda OK.'}],
                      'options':{'num_ctx':4096,'num_predict':3,'temperature':0}}),
        ]:
            response=requests.post(f'{OLLAMA_URL}/api/{endpoint}',json=payload,timeout=180)
            response.raise_for_status()
        readiness['models']='ready'
    except Exception:
        readiness['models']='unavailable'
        log.warning('Warmup Ollama falhou; verifique o serviço local.')
    audio.warmup()

@asynccontextmanager
async def lifespan(app):
    if os.getenv('ARCANJO_SKIP_WARMUP') != '1':
        threading.Thread(target=warmup,daemon=True).start()
    yield

app=FastAPI(title='Arka',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

def remote_hosts():
    import re
    try:
        host=urlsplit((ROOT/'.local/demo-url').read_text().strip()).hostname
        return {host} if host and re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com',host) else set()
    except OSError:return set()

@app.middleware('http')
async def lan_guard(request:Request,call_next):
    try:
        client=ipaddress.ip_address(request.client.host)
        host=urlsplit('//'+request.headers.get('host','')).hostname
        if not any(client in network for network in NETWORKS) or host not in HOSTS | remote_hosts():
            return JSONResponse({'detail':'Acesso permitido somente pela rede local configurada.'},403)
        origin=request.headers.get('origin')
        expected_origin = ('https://'+request.headers.get('host','')) if host in remote_hosts() else str(request.base_url).rstrip('/')
        if origin and origin != expected_origin:
            return JSONResponse({'detail':'Origem não permitida.'},403)
        length=request.headers.get('content-length')
        if length and (int(length)<0 or int(length)>MAX_BODY):
            return JSONResponse({'detail':'Envio excede 12 MB.'},413)
    except (ValueError, AttributeError):
        return JSONResponse({'detail':'Requisição inválida.'},400)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Permissions-Policy']='microphone=(self), camera=()'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

def session_for(request):
    auth=request.headers.get('authorization','')
    session=store.get(auth[7:]) if auth.startswith('Bearer ') else None
    if session is None or (access.required() and not session.username): raise HTTPException(401,'Entre com seu usuário e senha.')
    return session

def reserve(session):
    if not session.lock.acquire(blocking=False): raise HTTPException(409,'Esta sessão já está processando uma solicitação.')
    if not admission.acquire(blocking=False):
        session.lock.release()
        raise HTTPException(429,'Servidor ocupado. Tente novamente em instantes.')

def release(session):
    session.touched=time.monotonic()
    session.lock.release()
    admission.release()

async def bounded_body(request, limit=MAX_BODY):
    result=bytearray()
    async for chunk in request.stream():
        result.extend(chunk)
        if len(result)>limit: raise HTTPException(413,'Envio muito grande.')
    return bytes(result)

@app.post('/api/sessions')
async def new_session(request:Request):
    await bounded_body(request,1024)
    if access.required():raise HTTPException(401,'Entre com seu usuário e senha.')
    try: session=store.create()
    except RuntimeError as exc: raise HTTPException(429,str(exc))
    return {'token':session.token,'name':'Arka'}

@app.get('/api/state')
async def state(request:Request):
    session=session_for(request)
    return {'state':session.state,'models':readiness['models'],
            'stt':'unavailable' if audio.stt_error else ('ready' if audio.whisper or audio.upstream_ready else 'starting'),
            'tts':'unavailable' if audio.tts_error else ('ready' if audio.pipeline else 'starting')}

@app.get('/api/history')
async def history(request:Request):
    session=session_for(request)
    if session.lock.locked(): raise HTTPException(409,'Sessão ocupada.')
    return {'messages':session.history,'answers':list(session.answers.values())}

@app.delete('/api/history')
async def clear_history(request:Request):
    session=session_for(request); reserve(session)
    try:
        from app.core.voice_bridge import reset_voice_context
        session.history.clear(); session.answers.clear(); reset_voice_context(session.context)
        session.state='idle'
    finally: release(session)
    return {'ok':True}

@app.get('/api/answers/{message_id}')
async def get_answer(message_id:str,request:Request):
    entry=session_for(request).answers.get(message_id)
    if entry is None: raise HTTPException(404,'Resposta não encontrada nesta sessão.')
    return entry

@app.get('/api/answers/{message_id}/sources')
async def get_sources(message_id:str,request:Request):
    return {'sources':(await get_answer(message_id,request))['sources']}

class ChatInput(BaseModel):
    text:str=Field(min_length=1,max_length=3000)
    knowledge:bool=False

async def parse_text(request):
    raw=await bounded_body(request,16000)
    try: message=ChatInput.model_validate_json(raw)
    except Exception: raise HTTPException(422,'Informe um texto de até 3.000 caracteres.')
    text=message.text.strip()
    if not text: raise HTTPException(422,'Digite uma mensagem.')
    return text,message.knowledge

def stream_response(session,text=None,data=None,knowledge=False):
    reserve(session)
    loop=asyncio.get_running_loop()
    queue=asyncio.Queue()
    cancelled=threading.Event()
    previous_context=(session.context.last_route,session.context.expert_context)
    def emit(event,value):
        if not cancelled.is_set():
            loop.call_soon_threadsafe(queue.put_nowait,(event,value))
    def worker():
        try:
            question=text
            if data is not None:
                session.state='listening'; emit('state',{'state':'listening'})
                question=audio.transcribe(data)
                if len(question)>3000: raise ValueError('Transcrição longa demais.')
                emit('transcription',{'text':question})
            session.state='thinking'; emit('state',{'state':'thinking'})
            if knowledge:respond(session,question,emit,cancelled,knowledge=True)
            else:respond(session,question,emit,cancelled)
            session.state='idle'; emit('done',{'state':'idle'})
        except InterruptedError:
            session.context.last_route,session.context.expert_context=previous_context
            session.state='idle'
        except Exception as exc:
            session.context.last_route,session.context.expert_context=previous_context
            session.state='error'
            # Do not expose service traces, prompts, document contents or secrets.
            detail=str(exc) if isinstance(exc,ValueError) else ('Whisper CUDA indisponível no servidor.' if data is not None and audio.stt_error else 'Não consegui concluir a resposta. Verifique os serviços locais e tente novamente.')
            emit('error',{'detail':detail})
            log.warning('Falha de solicitação: %s',type(exc).__name__)
        finally:
            release(session)
            emit('_end',{})
    threading.Thread(target=worker,daemon=True).start()
    async def events():
        try:
            yield ': connected\n\n'
            while True:
                try: event,value=await asyncio.wait_for(queue.get(),15)
                except asyncio.TimeoutError:
                    yield ': keepalive\n\n'; continue
                if event=='_end': break
                yield 'event: '+event+'\ndata: '+json.dumps(value,ensure_ascii=False)+'\n\n'
        finally: cancelled.set()
    return StreamingResponse(events(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

@app.post('/api/chat')
async def chat(request:Request):
    session=session_for(request)
    text,knowledge=await parse_text(request)
    return stream_response(session,text=text,knowledge=knowledge)

@app.post('/api/audio')
async def speech(request:Request):
    session=session_for(request)
    data=await bounded_body(request)
    if not data: raise HTTPException(422,'Envie uma gravação de áudio.')
    return stream_response(session,data=data)

@app.post('/api/transcribe')
async def transcribe(request:Request):
    session=session_for(request)
    data=await bounded_body(request); reserve(session)
    # Keep the lock until native work ends, even if the HTTP client disconnects.
    def work():
        try:
            session.state='listening'
            return audio.transcribe(data)
        finally:
            session.state='idle'; release(session)
    try: return {'text':await asyncio.shield(asyncio.to_thread(work))}
    except ValueError as exc: raise HTTPException(422,str(exc))
    except Exception: raise HTTPException(503,'Whisper CUDA indisponível no servidor.')

@app.post('/api/tts')
async def tts(request:Request):
    session=session_for(request)
    raw=await bounded_body(request,1024)
    try: message_id=json.loads(raw)['message_id']
    except Exception: raise HTTPException(422,'Informe a resposta para reprodução.')
    if not isinstance(message_id,str): raise HTTPException(422,'Identificador inválido.')
    entry=session.answers.get(message_id)
    if entry is None: raise HTTPException(404,'Resposta não encontrada nesta sessão.')
    reserve(session)
    def work():
        try:
            session.state='speaking'
            return audio.synthesize(entry['text'])
        finally:
            session.state='idle'; release(session)
    try: data=await asyncio.shield(asyncio.to_thread(work))
    except Exception: raise HTTPException(503,'Kokoro indisponível no servidor.')
    return Response(data,media_type='audio/wav')

@app.get('/api/access')
async def access_info(request:Request):
    try: current=session_for(request)
    except HTTPException:current=None
    return {'login_required':access.required(),'authenticated':bool(current and current.username),
            'username':current.username if current else None,'role':current.role if current else None}

@app.post('/api/login')
async def login(request:Request):
    raw=await bounded_body(request,2048)
    try:
        data=json.loads(raw);username=data['username'];password=data['password']
        if not isinstance(username,str) or not isinstance(password,str) or not 1<=len(username)<=40 or not 1<=len(password)<=200:raise ValueError()
    except (ValueError,KeyError,TypeError):raise HTTPException(422,'Informe usuário e senha.')
    try: role=await asyncio.to_thread(access.authenticate,username,password,request.client.host)
    except RuntimeError as exc:raise HTTPException(429,str(exc))
    if role is None:raise HTTPException(401,'Usuário ou senha inválidos.')
    try: session=store.create()
    except RuntimeError as exc:raise HTTPException(429,str(exc))
    session.username=username;session.role=role
    return {'token':session.token,'username':username,'role':role}

@app.post('/api/logout')
async def logout(request:Request):
    session=session_for(request)
    if session.lock.locked():raise HTTPException(409,'Aguarde a resposta terminar.')
    with store.lock:store.sessions.pop(session.token,None)
    return {'ok':True}

def teacher(request):
    session=session_for(request)
    if session.role!='admin':raise HTTPException(403,'Somente administradores podem ensinar e publicar.')
    return session

@app.get('/api/teaching')
async def list_teaching(request:Request):
    teacher(request)
    from app.knowledge.teaching import teachings
    from app.knowledge.training_pdf import documents
    return {'lessons':await asyncio.to_thread(teachings.list),'documents':await asyncio.to_thread(documents)}

class LessonInput(BaseModel):
    question:str=Field(min_length=3,max_length=1000)
    answer:str=Field(min_length=1,max_length=4000)
    active:bool=False
    id:str|None=None

@app.post('/api/teaching')
async def save_teaching(request:Request):
    session=teacher(request)
    try: value=LessonInput.model_validate_json(await bounded_body(request,20000))
    except Exception:raise HTTPException(422,'Preencha pergunta e resposta dentro dos limites.')
    from app.knowledge.text_learning import save
    try: identifier=await asyncio.to_thread(save,value.question,value.answer,session.username,value.active,value.id)
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception:
        raise HTTPException(503,'Não consegui indexar o ensinamento. Verifique os serviços locais e tente novamente.')
    return {'id':identifier,'active':value.active}


@app.post('/api/upload/pdf')
async def upload_pdf_direct(request:Request):
    session = session_for(request)

    data = await bounded_body(
        request,
        MAX_BODY,
    )

    filename = request.headers.get(
        'X-Filename',
        'documento.pdf',
    )

    from urllib.parse import unquote
    from app.knowledge.training_pdf import upload_and_publish

    try:
        identifier = await asyncio.to_thread(
            upload_and_publish,
            data,
            unquote(filename),
            session.username or 'unknown',
        )

        return {
            'status': 'ok',
            'id': identifier,
            'message': 'PDF indexado e disponível no RAG.',
        }

    except ValueError as exc:
        raise HTTPException(
            422,
            str(exc),
        )

    except Exception:
        log.exception(
            'Falha ao indexar PDF direto.'
        )
        raise HTTPException(
            503,
            'Não consegui indexar o PDF.',
        )


@app.post('/api/teaching/pdf')
async def upload_pdf(request:Request):
    session=teacher(request);data=await bounded_body(request)
    from app.knowledge.training_pdf import upload
    from urllib.parse import unquote
    reserve(session)
    def work():
        try:return upload(data,unquote(request.headers.get('X-Filename','documento.pdf')),session.username)
        finally:release(session)
    try:return {'id':await asyncio.shield(asyncio.to_thread(work)),'status':'draft'}
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception:raise HTTPException(503,'Não consegui processar o PDF. Verifique Ollama e Qdrant.')

class ValidationInput(BaseModel):
    question:str=Field(min_length=3,max_length=1000)
    expected:str=Field(min_length=2,max_length=300)

@app.post('/api/teaching/pdf/{identifier}/validate')
async def validate_pdf(identifier:str,request:Request):
    session=teacher(request)
    try:value=ValidationInput.model_validate_json(await bounded_body(request,8000))
    except Exception:raise HTTPException(422,'Informe pergunta e um trecho curto esperado na resposta.')
    from app.knowledge.training_pdf import validate
    reserve(session)
    def work():
        try:return validate(identifier,value.question.strip(),value.expected.strip())
        finally:release(session)
    try:return await asyncio.shield(asyncio.to_thread(work))
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception:raise HTTPException(503,'Falha ao validar. Verifique os serviços locais.')

@app.post('/api/teaching/pdf/{identifier}/publish')
async def publish_pdf(identifier:str,request:Request):
    teacher(request)
    try:
        data=json.loads(await bounded_body(request,1024));active=data['active']
        if not isinstance(active,bool):raise ValueError()
    except (ValueError,KeyError,TypeError):raise HTTPException(422,'Informe active: true ou false.')
    from app.knowledge.training_pdf import publish
    try:await asyncio.to_thread(publish,identifier,active)
    except ValueError as exc:raise HTTPException(422,str(exc))
    return {'active':active}

@app.websocket('/api/chat/ws')
async def websocket_chat(ws:WebSocket):
    response=None
    try:
        host=urlsplit('//'+ws.headers.get('host','')).hostname
        client=ipaddress.ip_address(ws.client.host)
        scheme='https' if ws.url.scheme=='wss' or host in remote_hosts() else 'http'
        if host not in HOSTS | remote_hosts() or not any(client in network for network in NETWORKS):
            await ws.close(code=1008);return
        if ws.headers.get('origin')!=scheme+'://'+ws.headers.get('host',''):
            await ws.close(code=1008);return
        await ws.accept()
        data=await asyncio.wait_for(ws.receive_json(),10)
        if not isinstance(data,dict):raise ValueError()
        session=store.get(data.get('token',''))
        if not session or (access.required() and not session.username):
            await ws.send_json({'error':'Entre com seu usuário e senha.'});await ws.close(code=1008);return
        message=ChatInput.model_validate(data)
        if not message.text.strip():raise ValueError()
        response=stream_response(session,text=message.text.strip(),knowledge=message.knowledge)
        async for chunk in response.body_iterator:
            await ws.send_text(chunk)
        await ws.close()
    except HTTPException as exc:
        await ws.send_json({'error':exc.detail});await ws.close(code=1008)
    except (WebSocketDisconnect,RuntimeError):pass
    except Exception as exc:
        log.exception(
            "WebSocket falhou: %s | host=%s | origin=%s | client=%s",
            exc,
            ws.headers.get('host'),
            ws.headers.get('origin'),
            ws.client.host if ws.client else '?',
        )
        try:await ws.close(code=1008)
        except RuntimeError:pass
    finally:
        if response is not None:await response.body_iterator.aclose()

@app.post('/api/vision')
async def describe_camera(request:Request):
    session=session_for(request)
    data=await bounded_body(request,3*1024*1024)
    reserve(session)
    def work():
        from app.vision.describe import describe
        try:
            session.state='thinking'
            return describe(data)
        finally:
            session.state='idle';release(session)
    try:return {'description':await asyncio.shield(asyncio.to_thread(work))}
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception:raise HTTPException(503,'Visão indisponível. Tente novamente em instantes.')

@app.get('/health')
async def health():
    return {'status':'ok','name':'Arka'}

@app.get('/face')
async def face():
    return FileResponse(ROOT/'web'/'face.html')

@app.get('/')
async def index():
    return FileResponse(ROOT/'web'/'index.html')

app.mount('/assets',StaticFiles(directory=ROOT/'web'/'assets'),name='assets')
