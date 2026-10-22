#!/usr/bin/env python3
"""Keep a HTTPS tunnel to the existing Arka server; never start another backend."""
from pathlib import Path
import fcntl, os, re, signal, subprocess, threading
import requests
ROOT=Path(__file__).resolve().parents[1]
CA=ROOT/'.local/tls/arcanjo-local-ca.crt'
URL=ROOT/'.local/demo-url'
stop=threading.Event()

def main():
    os.umask(0o077)
    lock=(ROOT/'.local/demo.lock').open('w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('O túnel da Arka já está rodando.')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    binary=ROOT/'.local/bin/cloudflared'
    if not binary.exists():raise SystemExit('cloudflared não encontrado em .local/bin.')
    delay=2
    while not stop.is_set():
        try:
            response=requests.get('https://127.0.0.1:8444/api/access',verify=str(CA),timeout=5)
            response.raise_for_status()
            if response.json().get('login_required') is not True:
                raise SystemExit('Acesso externo bloqueado: ative o login antes de abrir o túnel.')
        except requests.RequestException:
            print('Aguardando Arka HTTPS em :8444…',flush=True)
            stop.wait(5);continue
        process=subprocess.Popen([str(binary),'tunnel','--url','https://127.0.0.1:8444',
            '--origin-ca-pool',str(CA),'--no-autoupdate','--protocol','http2','--loglevel','info',
            '--metrics','127.0.0.1:0'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        def watch():
            # Do not persist HTTP headers, credentials or full cloudflared diagnostics.
            for line in process.stdout:
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match and match[0] != "https://api.trycloudflare.com":
                    temporary=URL.with_suffix('.tmp');temporary.write_text(match[0]);temporary.replace(URL)
                    print('Arka externa: '+match[0],flush=True)
        reader=threading.Thread(target=watch,daemon=True);reader.start()
        try:
            while not stop.wait(1):
                if process.poll() is not None:break
        finally:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            reader.join(timeout=2)
            if URL.exists():URL.replace(ROOT/'.local/demo-url.previous')
        if not stop.is_set():
            print('Reconectando túnel; uma nova URL pode ser gerada.',flush=True)
            stop.wait(delay);delay=min(delay*2,30)
if __name__=='__main__':main()
