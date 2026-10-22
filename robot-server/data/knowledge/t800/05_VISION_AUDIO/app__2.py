#!/usr/bin/env python3
"""Painel local + API, somente biblioteca padrão. ROS é importado apenas no modo ros2."""
import argparse
import json
import logging
from pathlib import Path
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from core import Controller, Refused

ROOT = Path(__file__).resolve().parent


def make_handler(controller, lock):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data, mime='application/json'):
            payload = json.dumps(data, allow_nan=False).encode() if mime == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            # Evita DNS rebinding; servidor e túnel usam exclusivamente localhost.
            if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                return self.reply(403, {'error':'Host inválido. Use localhost.'})
            if self.path == '/api/status':
                with lock:
                    status = controller.status()
                status['token'] = token
                return self.reply(200, status)
            assets = {'/': ('index.html','text/html; charset=utf-8'),
                      '/app.js': ('app.js','text/javascript; charset=utf-8'),
                      '/style.css': ('style.css','text/css; charset=utf-8')}
            if self.path not in assets:
                return self.reply(404, {'error':'Não encontrado.'})
            name,mime = assets[self.path]
            self.reply(200, (ROOT/'web'/name).read_bytes(), mime)

        def do_POST(self):
            self.connection.settimeout(2.)
            if not secrets.compare_digest(self.headers.get('X-HeadFollow-Token',''), token):
                return self.reply(403, {'error':'Token inválido. Reabra o painel.'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 2048:
                    raise Refused('Corpo da requisição inválido.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    raise Refused('Esperado um objeto JSON.')
                owner = body.get('client')
                if not isinstance(owner,str) or not 8 <= len(owner) <= 100:
                    raise Refused('Sessão do navegador inválida.')
                with lock:
                    if self.path == '/api/arm':
                        controller.arm(owner)
                    elif self.path == '/api/pulse':
                        controller.pulse(owner)
                    elif self.path == '/api/move':
                        controller.move(owner, body.get('pitch'), body.get('yaw'))
                    elif self.path == '/api/stop':
                        controller.disarm()
                    else:
                        return self.reply(404, {'error':'Não encontrado.'})
                    state = controller.status()
                if self.path != '/api/pulse':
                    logging.info('%s %s', self.path, {k:v for k,v in body.items() if k != 'client'})
                self.reply(200, state)
            except (ValueError, TypeError, TimeoutError) as exc:
                self.reply(409, {'error':str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['sim','ros2'], default='sim')
    parser.add_argument('--enable-motion', action='store_true', help='Habilita armar pelo painel; exige telemetria, balance e ausência de concorrentes.')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    c = Controller(simulation=args.mode=='sim', enabled=args.enable_motion)
    lock, done = threading.RLock(), threading.Event()
    backend = None
    if args.mode == 'ros2':
        from ros_backend import RosBackend
        backend = RosBackend(c,lock)  # Erro de ROS encerra: nunca troca silenciosamente para simulação.
    server = ThreadingHTTPServer(('127.0.0.1',args.port), make_handler(c,lock))
    server.daemon_threads = True
    def control_loop():
        try:
            while not done.is_set():
                if backend:
                    backend.step()
                else:
                    with lock:
                        c.tick()
                done.wait(.01)
        except Exception:
            logging.exception('Falha no loop de controle; servidor será encerrado.')
            done.set()
        finally:
            with lock:
                c.disarm('Loop encerrado.')
            if backend:
                backend.close()
    worker = threading.Thread(target=control_loop)
    worker.start()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    server.timeout = .2
    logging.info('headFollow em http://127.0.0.1:%d | modo %s | comandos %s', args.port,args.mode,c.enabled)
    try:
        while not done.is_set():
            server.handle_request()
    finally:
        done.set()
        worker.join(timeout=3.)
        server.server_close()


if __name__ == '__main__':
    main()
