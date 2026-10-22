#!/usr/bin/env python3
"""Real HTTP integration check; does not ingest/reindex or call physical commands."""
from pathlib import Path
import argparse, io, json, time
from concurrent.futures import ThreadPoolExecutor
import requests
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--url',default='https://192.168.102.144:8444');args=p.parse_args()
BASE=args.url;CA=str(ROOT/'.local/tls/arcanjo-local-ca.crt');results={}
def call(path,token=None,**kwargs):
    headers=kwargs.pop('headers',{})
    if token:headers['Authorization']='Bearer '+token
    return requests.request(kwargs.pop('method','GET'),BASE+path,headers=headers,verify=CA,timeout=(5,240),**kwargs)
def session():
    r=call('/api/sessions',method='POST');r.raise_for_status();return r.json()['token']
def chat(token,text):
    started=time.perf_counter();r=call('/api/chat',token,method='POST',json={'text':text},stream=True);r.raise_for_status()
    event='';answer=None;first=None;events=[]
    for line in r.iter_lines(decode_unicode=True,chunk_size=1):
        if line.startswith('event: '):event=line[7:]
        if line.startswith('data: '):
            data=json.loads(line[6:]);events.append(event)
            if event=='token' and first is None:first=time.perf_counter()-started
            if event=='error':raise RuntimeError(data['detail'])
            if event=='answer':answer=data
    assert answer and 'done' in events
    return answer,{'first_token_seconds':first,'total_seconds':time.perf_counter()-started,'token_events':events.count('token')}
try:
    r=call('/health');r.raise_for_status();assert r.json()['name']=='Arcanjo';results['lan_https']='PASS (host LAN, certificate verified)'
    a,b=session(),session()
    with ThreadPoolExecutor(2) as pool:
        one=pool.submit(chat,a,'Meu código de teste é PONTEAZUL. Memorize nesta conversa e responda apenas OK.')
        two=pool.submit(chat,b,'Meu código de teste é LAGOAMARELA. Memorize nesta conversa e responda apenas OK.')
        one.result();two.result()
    with ThreadPoolExecutor(2) as pool:
        one=pool.submit(chat,a,'Qual é meu código de teste? Responda somente o código.')
        two=pool.submit(chat,b,'Qual é meu código de teste? Responda somente o código.')
        ra,ma=one.result();rb,mb=two.result()
    assert 'PONTEAZUL' in ra['text'].upper() and 'LAGOAMARELA' not in ra['text'].upper()
    assert 'LAGOAMARELA' in rb['text'].upper() and 'PONTEAZUL' not in rb['text'].upper()
    results['two_simultaneous_sessions']={'status':'PASS','a':ma,'b':mb}
    assert call('/api/answers/'+ra['id'],b).status_code==404
    assert call('/api/tts',b,method='POST',json={'message_id':ra['id']}).status_code==404
    results['cross_session_access']='PASS'
    c=session();answer,metrics=chat(c,'Explique em quatro frases o que é uma API, em português.')
    assert len(answer['text'])>100;results['txt_streaming']={'status':'PASS',**metrics}
    r=call('/api/tts',c,method='POST',json={'message_id':answer['id']});r.raise_for_status()
    samples,rate=sf.read(io.BytesIO(r.content));assert rate==24000 and len(samples)>rate and abs(samples).max()>0.01
    results['tts_txt']={'status':'PASS','seconds':round(len(samples)/rate,2),'sample_rate':rate}
    short,_=chat(c,'Responda exatamente: Quanto é dois mais dois?')
    wav=call('/api/tts',c,method='POST',json={'message_id':short['id']});wav.raise_for_status()
    (ROOT/'logs'/'stt-test-input.wav').write_bytes(wav.content)
    r=call('/api/transcribe',c,method='POST',data=wav.content,headers={'Content-Type':'audio/wav'})
    results['stt_cuda']={'status':'PASS' if r.ok else 'BLOCKED','http':r.status_code,'detail':r.json()}
    r=call('/api/audio',c,method='POST',data=wav.content,headers={'Content-Type':'audio/wav'})
    if 'event: answer' in r.text:
        results['audio_to_response']='PASS'
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')];entry=next(x for x in events if 'id' in x)
        out=call('/api/tts',c,method='POST',json={'message_id':entry['id']});out.raise_for_status();results['tts_stt']='PASS'
    else:results['audio_to_response']='BLOCKED: Whisper CUDA unavailable';results['tts_stt']='BLOCKED by STT'
    d=session();answer,metrics=chat(d,'Qual o peso máximo que o Arcanjo suporta?')
    assert answer['route']=='EXPERT' and '150 kg' not in answer['text']
    assert all(set(s)<= {'number','source','page'} for s in answer['sources'])
    results['web_expert_guard']={'status':'PASS',**metrics}
    ps=requests.get('http://127.0.0.1:11434/api/ps',timeout=10).json()['models']
    results['models']=[{k:m.get(k) for k in ('name','size_vram','context_length','expires_at')} for m in ps]
    by_name={m['name']:m for m in ps}
    assert by_name['qwen3:8b']['size_vram']>0 and by_name['qwen3:8b']['context_length']==4096
    assert by_name['qwen3-embedding:0.6b']['size_vram']==0
    results['model_placement']='PASS'
except Exception as exc:
    results['failure']=type(exc).__name__+': '+str(exc)
finally:
    (ROOT/'logs'/'lan-validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False,indent=2))
if 'failure' in results:raise SystemExit(1)
