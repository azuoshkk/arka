#!/usr/bin/env python3
"""Launch the LAN server with local TLS and one shared model process."""
from pathlib import Path
import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]

def lan_config():
    routes=json.loads(subprocess.check_output(['ip','-j','route','get','1.1.1.1']))
    address=os.getenv('ARCANJO_LAN_IP') or routes[0].get('prefsrc')
    if not address or not ipaddress.ip_address(address).is_private:
        raise SystemExit('Defina ARCANJO_LAN_IP com o endereço privado da interface LAN.')
    interfaces=json.loads(subprocess.check_output(['ip','-j','-4','addr']))
    for interface in interfaces:
        for entry in interface.get('addr_info',[]):
            if entry['local']==address:
                return address,str(ipaddress.ip_network(address+'/'+str(entry['prefixlen']),strict=False))
    raise SystemExit('ARCANJO_LAN_IP não pertence a uma interface local.')

def certificates(address):
    tls=ROOT/'.local'/'tls'; tls.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(tls,0o700)
    key=tls/'server.key'; cert=tls/'server.crt'; ca=tls/'arcanjo-local-ca.crt'; ca_key=tls/'ca.key'
    def run(*args): subprocess.run(['openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if not ca.exists():
        run('req','-x509','-newkey','rsa:3072','-nodes','-sha256','-days','3650',
            '-subj','/CN=Arcanjo LAN Local CA','-addext','basicConstraints=critical,CA:TRUE',
            '-addext','keyUsage=critical,keyCertSign,cRLSign','-keyout',ca_key,'-out',ca)
        os.chmod(ca_key,0o600)
    marker=tls/'lan-address'
    valid=cert.exists() and subprocess.run(['openssl','x509','-checkend','86400','-noout','-in',str(cert)],stdout=subprocess.DEVNULL).returncode==0
    if not valid or not marker.exists() or marker.read_text()!=address:
        ext=tls/'server.ext'
        ext.write_text('subjectAltName=DNS:localhost,IP:127.0.0.1,IP:'+address+'\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
        run('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=Arcanjo LAN','-keyout',key,'-out',tls/'server.csr')
        run('x509','-req','-in',tls/'server.csr','-CA',ca,'-CAkey',ca_key,'-CAcreateserial','-out',cert,'-days','825','-sha256','-extfile',ext)
        marker.write_text(address); os.chmod(key,0o600)
    return cert,key,ca

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8444); parser.add_argument('--http-port',type=int,default=8082);parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args(); address,network=lan_config();cert,key,ca=certificates(address)
    url=f'https://{address}:{args.port}'
    os.environ['ARCANJO_LAN_HOSTS']=address
    os.environ['ARCANJO_LAN_NETWORKS']='127.0.0.0/8,'+network
    os.environ['ARKA_EMBED_NUM_GPU']='0';os.environ['ARKA_EMBED_KEEP_ALIVE']='-1'
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['PYTHONUNBUFFERED']='1'
    # CUDA user-space libraries already installed in the existing environment.
    libs=[
        str(p)
        for p in (ROOT/'.venv'/'lib').glob(
            'python*/site-packages/nvidia/*/lib'
        )
    ]

    cublas = (
        ROOT
        / '.venv'
        / 'lib'
        / 'python3.12'
        / 'site-packages'
        / 'nvidia'
        / 'cublas'
        / 'lib'
    )

    if cublas.exists():
        libs.insert(0, str(cublas))
    if libs and not os.getenv('ARCANJO_LD_READY'):
        os.environ['LD_LIBRARY_PATH']=':'.join(libs+[os.getenv('LD_LIBRARY_PATH','')])
        os.environ['ARCANJO_LD_READY']='1'
        os.execv(sys.executable,[sys.executable,*sys.argv])
    print('Arcanjo LAN:',url,flush=True)
    print('Certificado público:',ca,flush=True)
    (ROOT/'.local'/'lan.json').write_text(json.dumps({'url':url,'ip':address,'network':network},indent=2))
    if args.prepare_only:return
    class SetupHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try: allowed=ipaddress.ip_address(self.client_address[0]) in ipaddress.ip_network(network) or ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:allowed=False
            if not allowed:self.send_error(403);return
            if self.path=='/arcanjo-local-ca.crt':
                data=ca.read_bytes();content='application/x-x509-ca-cert'
            elif self.path=='/':
                data=f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Arcanjo · Acesso local</title><h1>Arcanjo</h1><p>Para usar o microfone, instale e confie no certificado local deste servidor.</p><p><a href="/arcanjo-local-ca.crt">Baixar certificado público local</a></p><p><a href="{url}">Abrir Arcanjo</a></p><p>Consulte o README do projeto para instruções por dispositivo.</p></html>'.encode();content='text/html; charset=utf-8'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    setup=ThreadingHTTPServer(('0.0.0.0',args.http_port),SetupHandler)
    threading.Thread(target=setup.serve_forever,daemon=True).start()
    os.chdir(ROOT/'robot-server');sys.path.insert(0,str(ROOT/'robot-server'))
    import uvicorn
    from logging.handlers import RotatingFileHandler
    import logging
    handler=RotatingFileHandler(ROOT/'logs'/'web.log',maxBytes=5*1024*1024,backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger('arcanjo').addHandler(handler)
    tunnel = None
    tunnel_log = None
    remote_enabled = os.getenv('ARKA_REMOTE_ACCESS', '1' if (ROOT/'.local/remote-enabled').exists() else '0') == '1'
    if remote_enabled:
        tunnel_log = (ROOT/'logs/remote-access.log').open('a')
        tunnel = subprocess.Popen([sys.executable, '-u', str(ROOT/'scripts/start-demo.py')],
                                  stdout=tunnel_log, stderr=subprocess.STDOUT)
        print('Acesso externo ativo quando conectado. URL: .local/demo-url; status: logs/remote-access.log', flush=True)
    try:
        uvicorn.run('app.api.web:app',host='0.0.0.0',port=args.port,workers=1,
                    ssl_certfile=str(cert),ssl_keyfile=str(key),proxy_headers=False,access_log=False)
    finally:
        setup.shutdown();setup.server_close()
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:tunnel.wait(timeout=12)
            except subprocess.TimeoutExpired:tunnel.kill();tunnel.wait()
        if tunnel_log:tunnel_log.close()

if __name__=='__main__':main()
