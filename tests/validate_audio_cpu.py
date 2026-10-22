"""Supplemental codec/STT integration test in the GPU-restricted test environment.
Production remains Whisper small/CUDA. No production configuration is changed.
"""
from pathlib import Path
import os, sys, json, io
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'robot-server'))
os.environ['ARCANJO_SKIP_WARMUP']='1'
os.environ['ARCANJO_LAN_HOSTS']='testserver'
os.environ['HF_HUB_OFFLINE']='1'
from faster_whisper import WhisperModel
from fastapi.testclient import TestClient
from app.api import web
import soundfile as sf

web.audio.whisper=WhisperModel('small',device='cpu',compute_type='int8',local_files_only=True)
client=TestClient(web.app,client=('127.0.0.1',50001))
token=client.post('/api/sessions').json()['token'];headers={'Authorization':'Bearer '+token,'Content-Type':'audio/wav'}
wav=(ROOT/'logs'/'stt-test-input.wav').read_bytes()
r=client.post('/api/audio',headers=headers,content=wav)
assert r.status_code==200
entries=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
assert 'event: transcription' in r.text and 'event: done' in r.text, r.text
answer=next(x for x in entries if 'id' in x)
r=client.post('/api/tts',headers={'Authorization':'Bearer '+token},json={'message_id':answer['id']})
assert r.status_code==200,r.text
samples,rate=sf.read(io.BytesIO(r.content))
assert rate==24000 and len(samples)>rate/2 and abs(samples).max()>0.01
result={'status':'PASS','device':'CPU TEST ONLY; production CUDA unchanged','transcription':entries[1] if len(entries)>1 else entries,'answer':answer['text'],'tts_seconds':round(len(samples)/rate,2),'sample_rate':rate}
(ROOT/'logs'/'audio-cpu-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
