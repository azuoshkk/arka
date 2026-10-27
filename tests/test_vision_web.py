import io,os,sys,unittest
from pathlib import Path
from unittest.mock import patch,Mock
os.environ['ARCANJO_SKIP_WARMUP']='1'
os.environ.setdefault('ARCANJO_LAN_HOSTS','testserver')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'robot-server'))
from PIL import Image
from fastapi.testclient import TestClient
from app.api import web
from app.vision import describe as vision

class VisionTests(unittest.TestCase):
 def image(self):
  out=io.BytesIO();Image.new('RGB',(100,100)).save(out,format='JPEG');return out.getvalue()
 def test_cpu_only_and_bounded_generation(self):
  response=Mock();response.json.return_value={'response':'A red box.'}
  with patch.object(vision.requests,'post',return_value=response) as post:
   self.assertEqual(vision.describe(self.image()),'A red box.')
   data=post.call_args.kwargs['json']
   self.assertEqual(data['options']['num_gpu'],0)
   self.assertEqual(data['keep_alive'],0)
   self.assertLessEqual(data['options']['num_predict'],200)
 def test_reject_invalid_and_large_images(self):
  for data in (b'not an image',b'x'*(3*1024*1024+1)):
   with self.assertRaises(ValueError):vision.normalize(data)
 def test_authentication_and_session_release(self):
  client=TestClient(web.app,base_url='http://localhost',client=('127.0.0.1',50000))
  with patch.object(web.access,'required',return_value=True):
   self.assertEqual(client.post('/api/vision',content=self.image()).status_code,401)
   session=web.store.create();session.username='pi-test';session.role='viewer'
   headers={'Authorization':'Bearer '+session.token}
   with patch.object(vision,'describe',side_effect=RuntimeError('private detail')):
    result=client.post('/api/vision',headers=headers,content=self.image())
   self.assertEqual(result.status_code,503)
   self.assertNotIn('private detail',result.text)
   self.assertFalse(session.lock.locked())
   with patch.object(vision,'describe',return_value='A room.'):
    self.assertEqual(client.post('/api/vision',headers=headers,content=self.image()).json(),{'description':'A room.'})
