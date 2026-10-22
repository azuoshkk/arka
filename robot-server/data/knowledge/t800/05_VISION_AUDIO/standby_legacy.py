#!/usr/bin/env python3
"""Mantém a porta esperada pela ponte, sem inicializar ROS nem publicar comandos."""
import json
import math
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen

MARKER = Path('/home/ubuntu/headFollow/controle_exclusivo.json')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status':'ok','service':'headfollow_legacy_standby'})
        if self.path != '/status':
            return self.reply(404, {'error':'Não encontrado'})
        try:
            with urlopen('http://127.0.0.1:8766/api/status',timeout=.5) as response:
                state=json.load(response)
            angles=state.get('actual') or [None,None]
            fresh=state.get('feedback_age') is not None and state['feedback_age'] <= .5
            data=dict(online=True, simulation=False, managed_by='headFollow',
                is_moving=state['moving'], has_hardware_feedback=fresh,
                balance_mode_requested=False, control_external=True,
                actual_pitch=math.radians(angles[0]) if angles[0] is not None else None,
                actual_yaw=math.radians(angles[1]) if angles[1] is not None else None,
                current_pitch_deg=angles[0], current_yaw_deg=angles[1],
                message='Controle transferido para headFollow. Use o painel na porta 8766.')
            self.reply(200,data)
        except Exception:
            self.reply(503,{'online':False,'managed_by':'headFollow','error':'headFollow indisponível; comandos bloqueados.'})

    def do_POST(self):
        self.close_connection=True
        self.reply(423,{'success':False,'error':'Pescoço sob controle do headFollow. Use o novo painel.'})


if __name__ == '__main__':
    server=HTTPServer(('0.0.0.0',5055),Handler)
    server.timeout=.5
    try:
        while MARKER.exists(): server.handle_request()
    finally:server.server_close()
