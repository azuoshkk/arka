import os
os.environ['ARCANJO_SKIP_WARMUP']='1'
os.environ['ARCANJO_LAN_HOSTS']='testserver'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'robot-server'))
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.api import web
from app.core.voice_bridge import VoiceContext, prepare_voice_route
from app.core.web_conversation import display_name, public_sources
from app.speech.tts_fast import clean_for_speech

class WebTests(unittest.TestCase):
    def setUp(self):
        patcher=patch.object(web.access,"required",return_value=False);patcher.start();self.addCleanup(patcher.stop)
        self.client=TestClient(web.app,client=('127.0.0.1',50000))
        self.token=self.client.post('/api/sessions').json()['token']
        self.headers={'Authorization':'Bearer '+self.token}
    def test_context_isolation(self):
        a,b=VoiceContext(),VoiceContext()
        self.assertEqual(prepare_voice_route('Como funciona o ROS2 bridge do Arcanjo?',context=a)['route'],'expert')
        self.assertEqual(prepare_voice_route('E isso?',context=b)['route'],'chat')
        self.assertEqual(prepare_voice_route('E isso?',context=a)['route'],'expert')
    def test_speech_cleaner(self):
        text=clean_for_speech('🤖 O T800 pesa 84,5 kg [Fonte 1].')
        self.assertIn('oitenta e quatro vírgula cinco quilogramas',text)
        for forbidden in ('🤖','Fonte','T800'):self.assertNotIn(forbidden,text)
        self.assertIn('Arcanjo',text)
    def test_identity_preserves_literals(self):
        text=display_name('O T800 usa `T800` em /config/T800/robot.yaml e T800.py. Arka ajuda.')
        self.assertEqual(text,'O Arcanjo usa `T800` em /config/T800/robot.yaml e T800.py. Arka ajuda.')
    def test_source_minimization(self):
        result=public_sources([{'source':'/internal/manual.txt','text':'confidential','path':'/secret','page':2}])
        self.assertEqual(result,[{'number':1,'source':'manual.txt','page':2}])
    def test_lan_security(self):
        self.assertEqual(self.client.get('/health',headers={'Host':'evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/sessions',headers={'Origin':'https://evil.example'}).status_code,403)
        remote=TestClient(web.app,client=('8.8.8.8',12345))
        self.assertEqual(remote.get('/health').status_code,403)
        self.assertEqual(self.client.get('/api/history').status_code,401)
        self.assertEqual(self.client.get('/assets/../../robot-server/app/config.py').status_code,404)
    def test_oversize_and_empty(self):
        self.assertEqual(self.client.post('/api/audio',headers={**self.headers,'Content-Length':str(web.MAX_BODY+1)},content=b'x').status_code,413)
        self.assertEqual(self.client.post('/api/chat',headers=self.headers,json={'text':' '}).status_code,422)
        self.assertEqual(self.client.post('/api/chat',headers=self.headers,json={'text':'x'*3001}).status_code,422)
    def test_owner_only_answers_tts(self):
        session=web.store.get(self.token);session.answers['one']={'text':'one','sources':[]}
        other=self.client.post('/api/sessions').json()['token'];headers={'Authorization':'Bearer '+other}
        self.assertEqual(self.client.get('/api/answers/one',headers=headers).status_code,404)
        self.assertEqual(self.client.post('/api/tts',headers=headers,json={'message_id':'one'}).status_code,404)
    def test_same_session_busy(self):
        session=web.store.get(self.token);session.lock.acquire()
        try:self.assertEqual(self.client.post('/api/chat',headers=self.headers,json={'text':'Olá'}).status_code,409)
        finally:session.lock.release()
    def test_two_simultaneous_sessions(self):
        barrier=threading.Barrier(2)
        def fake_respond(session,text,emit,cancelled):
            barrier.wait(timeout=3)
            session.history.append({'role':'user','content':text})
            emit('answer',{'text':text,'sources':[]})
        other=self.client.post('/api/sessions').json()['token']
        def send(token,text):
            return self.client.post('/api/chat',headers={'Authorization':'Bearer '+token},json={'text':text})
        with patch.object(web,'respond',fake_respond),ThreadPoolExecutor(2) as pool:
            a=pool.submit(send,self.token,'ALFA');b=pool.submit(send,other,'BETA')
            self.assertIn('ALFA',a.result().text);self.assertIn('BETA',b.result().text)
        self.assertEqual(web.store.get(self.token).history,[{'role':'user','content':'ALFA'}])
        self.assertEqual(web.store.get(other).history,[{'role':'user','content':'BETA'}])
    def test_error_restores_context_and_releases_locks(self):
        def broken(session,*args):
            session.context.last_route='expert';raise RuntimeError('secret internal detail')
        with patch.object(web,'respond',broken):
            result=self.client.post('/api/chat',headers=self.headers,json={'text':'Olá'})
        self.assertIn('event: error',result.text);self.assertNotIn('secret internal detail',result.text)
        session=web.store.get(self.token)
        self.assertEqual(session.context.last_route,'chat');self.assertFalse(session.lock.locked())
    def test_transcription_and_audio_flow(self):
        with patch.object(web.audio,'transcribe',return_value='Olá por áudio'):
            result=self.client.post('/api/transcribe',headers=self.headers,content=b'fake')
            self.assertEqual(result.json()['text'],'Olá por áudio')
            def answer(session,text,emit,cancelled):
                self.assertEqual(text,'Olá por áudio');emit('answer',{'id':'1','text':'Olá','sources':[]})
            with patch.object(web,'respond',answer):
                result=self.client.post('/api/audio',headers=self.headers,content=b'fake')
                self.assertIn('event: transcription',result.text);self.assertIn('event: answer',result.text)
    def test_invalid_audio_is_rejected(self):
        response=self.client.post('/api/transcribe',headers=self.headers,content=b'not-audio')
        self.assertEqual(response.status_code,422)
    def test_clear_and_expiration(self):
        session=web.store.get(self.token);session.context.last_route='expert';session.history.append({'role':'user','content':'old'})
        self.assertEqual(self.client.delete('/api/history',headers=self.headers).status_code,200)
        self.assertEqual(session.history,[]);self.assertEqual(session.context.last_route,'chat')
        session.touched-=web.store.ttl+1
        self.assertEqual(self.client.get('/api/history',headers=self.headers).status_code,401)

if __name__=='__main__':unittest.main(verbosity=2)
