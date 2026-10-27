#!/usr/bin/env python3
"""Loopback device adapter: holds credentials outside Chromium, reuses Arka APIs."""
import json
import os
import threading
import time
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home()/'.config/arka-body/client.json'
ORIGIN = 'http://127.0.0.1:8765'
ALLOWED = {'/api/transcribe': 4*1024*1024, '/api/chat': 16000,
           '/api/tts': 1024, '/api/vision': 3*1024*1024}

class Upstream:
    def __init__(self, config):
        self.config = config
        self.token = None
        self.lock = threading.Lock()
    def call(self, path, data, content_type):
        cfg = self.config
        for attempt in range(2):
            if not self.token:
                r = requests.post(cfg['url']+'/api/login', json={
                    'username': cfg['username'], 'password': cfg['password']},
                    verify=cfg['ca'], timeout=(5,15), allow_redirects=False)
                r.raise_for_status()
                self.token = r.json()['token']
            r = requests.post(cfg['url']+path, data=data,
                headers={'Authorization':'Bearer '+self.token, 'Content-Type':content_type},
                verify=cfg['ca'], timeout=(5,240), stream=True, allow_redirects=False)
            if r.status_code != 401:
                return r
            r.close();self.token=None
        raise RuntimeError('Autenticação do dispositivo indisponível')

monitor = {'seen': 0, 'updated': 0, 'status': {}, 'frame': b'', 'seq': 0, 'request': 0, 'detection': {}, 'detection_time': 0}
monitor_lock = threading.Condition()
def pi_temperature():
    try:return round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000,1)
    except (OSError,ValueError):return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def log_message(self, *args):
        pass # Never log credentials, images, transcripts or URL query strings.
    def valid(self, post=False):
        return (self.headers.get('Host') == '127.0.0.1:8765'
                and (not post or self.headers.get('Origin') == ORIGIN))
    def reply(self, code, data, content_type, headers=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        for name,value in (headers or {}).items():self.send_header(name,str(value))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Permissions-Policy','microphone=(self), camera=(self)')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.valid():return self.reply(403,b'Forbidden','text/plain')
        if self.path == '/monitor':
            return self.reply(200,(ROOT/'web/monitor.html').read_bytes(),'text/html; charset=utf-8')
        if self.path == '/monitor/state':
            with monitor_lock:
                monitor['seen']=time.monotonic()
                data=json.dumps({'status':monitor['status'], 'age':time.monotonic()-monitor['updated'], 'detection':monitor['detection'], 'detectionAge':time.monotonic()-monitor['detection_time']}).encode()
            return self.reply(200,data,'application/json')
        if self.path == '/monitor/video':
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
            self.send_header('Connection','close');self.close_connection=True
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.connection.settimeout(5)
            seq=-1
            try:
                while True:
                    with monitor_lock:
                        if time.monotonic()-monitor['seen']>10: break
                        monitor_lock.wait_for(lambda: monitor['seq']!=seq,timeout=2)
                        if monitor['seq']==seq: continue
                        data=monitor['frame'];seq=monitor['seq']
                    if not data: continue
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                    self.wfile.flush()
            except (OSError,TimeoutError):pass
            return
        if self.path == '/monitor/frame':
            with monitor_lock: data=monitor['frame'];seq=monitor['seq']
            return self.reply(200 if data else 204,data,'image/jpeg',{'X-Frame-Sequence':seq})
        if self.path == '/monitor/enabled':
            with monitor_lock:
                active=time.monotonic()-monitor['seen']<5; command=monitor['request']
                objects=monitor['detection'].get('objects',[]) if time.monotonic()-monitor['detection_time']<1.5 else []
            return self.reply(200,json.dumps({'active':active,'request':command,'objects':objects,'temperature':pi_temperature()}).encode(),'application/json')
        if self.path == '/health':return self.reply(200,b'{"status":"ok"}','application/json')
        if self.path in ('/','/face'):
            data=(ROOT/'web/face.html').read_text().replace('/assets/spectrum.js','/assets/body-spectrum.js').replace('</head>',
                '<script src="/assets/vision-intent.js" defer></script><script src="/assets/wake.js" defer></script><script src="/assets/body.js" defer></script><script src="/assets/body-monitor.js" defer></script></head>').encode()
            return self.reply(200,data,'text/html; charset=utf-8')
        names={'style.css','face.css','face.js','spectrum.js','body.js','capture-worklet.js','body-monitor.js','body-spectrum.js','monitor.js','monitor.css','wake.js','vision-intent.js'}
        if self.path.startswith('/assets/') and self.path[8:] in names:
            name=self.path[8:]
            kind='text/css' if name.endswith('.css') else 'text/javascript'
            return self.reply(200,(ROOT/'web/assets'/name).read_bytes(),kind)
        self.reply(404,b'Not found','text/plain')
    def do_POST(self):
        if not self.valid(True):return self.reply(403,b'Forbidden','text/plain')
        if self.path == '/monitor/detections':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=24000:raise ValueError()
                self.connection.settimeout(5)
                value=json.loads(self.rfile.read(size))
                objects=value['objects']
                if not isinstance(objects,list) or len(objects)>60:raise ValueError()
                for obj in objects:
                    if not isinstance(obj['label'],str) or len(obj['label'])>40:raise ValueError()
                    if len(obj['box'])!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in obj['box']):raise ValueError()
                    if not 0<=obj['confidence']<=1:raise ValueError()
                clean={'objects':objects,'ms':min(10000,max(0,int(value['ms']))),'model':'YOLOX-S / CPU'}
                with monitor_lock: monitor['detection']=clean;monitor['detection_time']=time.monotonic()
                return self.reply(200,b'{}','application/json')
            except (ValueError,TypeError,KeyError,TimeoutError):return self.reply(400,b'Invalid detections','text/plain')
        if self.path == '/monitor/analyze':
            with monitor_lock: monitor['request']+=1
            return self.reply(200,b'{}','application/json')
        if self.path in ('/monitor/status','/monitor/frame'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=300000: return self.reply(413,b'Too large','text/plain')
                self.connection.settimeout(5)
                data=self.rfile.read(size)
                if self.path.endswith('/status'):
                    value=json.loads(data)
                    if not isinstance(value,dict): raise ValueError()
                    with monitor_lock: monitor['status']=value;monitor['updated']=time.monotonic()
                else:
                    if not data.startswith(b'\xff\xd8'): raise ValueError()
                    with monitor_lock:
                        monitor['frame']=data;monitor['seq']+=1;monitor_lock.notify_all()
                return self.reply(200,b'{}','application/json')
            except (ValueError,TimeoutError):return self.reply(400,b'Invalid','text/plain')
        limit=ALLOWED.get(self.path)
        if limit is None:return self.reply(404,b'Not found','text/plain')
        try:size=int(self.headers.get('Content-Length','-1'))
        except ValueError:size=-1
        if size<1 or size>limit:return self.reply(413,b'Invalid body size','text/plain')
        if not upstream.lock.acquire(blocking=False):return self.reply(409,b'Busy','text/plain')
        try:
            self.connection.settimeout(15)
            data=self.rfile.read(size)
            if len(data)!=size:raise ValueError('Incomplete request')
            with upstream.call(self.path,data,self.headers.get('Content-Type','application/octet-stream')) as r:
                if r.status_code>=300:
                    return self.reply(r.status_code,b'{"detail":"Solicitacao indisponivel"}','application/json')
                self.send_response(r.status_code)
                self.send_header('Content-Type',r.headers.get('Content-Type','application/octet-stream'))
                self.send_header('Connection','close');self.close_connection=True
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                for block in r.iter_content(chunk_size=1024):
                    self.wfile.write(block);self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            # Close incomplete streams; the client will retry on the next utterance.
            self.close_connection=True
            print('Falha de comunicação com o servidor; tente novamente.',flush=True)
        finally:upstream.lock.release()

if __name__ == '__main__':
    os.umask(0o077)
    upstream=Upstream(json.loads(CONFIG.read_text()))
    ThreadingHTTPServer.request_queue_size=64
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
    server.daemon_threads=True
    print('Arka corpo: http://127.0.0.1:8765/face',flush=True)
    server.serve_forever()
