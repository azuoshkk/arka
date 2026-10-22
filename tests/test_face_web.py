"""Dedicated face route does not grant API access or change the chat transport."""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
os.environ['ARCANJO_SKIP_WARMUP']='1'
os.environ.setdefault('ARCANJO_LAN_HOSTS','testserver')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'robot-server'))
from fastapi.testclient import TestClient
from app.api import web

class FaceWebTests(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(web.app,base_url='http://localhost',client=('127.0.0.1',50000))
 def test_face_public_shell_does_not_bypass_api_auth(self):
  with patch.object(web.access,'required',return_value=True):
   page=self.client.get('/face')
   self.assertEqual(page.status_code,200)
   for item in ['id="voice-spectrum"','id="player"','/assets/style.css','/assets/spectrum.js']:
    self.assertIn(item,page.text)
   for item in ['login-dialog','id="composer"','id="messages"']:
    self.assertNotIn(item,page.text)
   self.assertEqual(self.client.get('/api/history').status_code,401)
   self.assertEqual(self.client.post('/api/tts',json={'message_id':'fake'}).status_code,401)
 def test_existing_websocket_still_streams(self):
  session=web.store.create();session.username='face-test';session.role='viewer'
  def answer(session,text,emit,cancelled,knowledge=False):
   emit('answer',{'id':'test','text':'Olá','sources':[]})
  with patch.object(web,'respond',side_effect=answer):
   with self.client.websocket_connect('ws://localhost/api/chat/ws',headers={'Origin':'http://localhost'}) as ws:
    ws.send_json({'token':session.token,'text':'Olá','knowledge':False})
    chunks=[]
    while True:
     frame=ws.receive_text();chunks.append(frame)
     if 'event: done' in frame:break
   self.assertTrue(any('event: answer' in frame for frame in chunks))

if __name__=='__main__':unittest.main()
