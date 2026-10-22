#!/usr/bin/env python3
"""Reversão opcional, executar NO ORIN: python3 restaurar_legado.py --execute.
Para apenas o headFollow, restaura o arquivo anterior e deixa a ponte reiniciar
o controlador legado. Não publica modo corporal nem comandos de movimento.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',required=True)
    parser.parse_args()
    root=Path('/home/ubuntu/headFollow')
    marker=root/'controle_exclusivo.json'
    data=json.loads(marker.read_text())
    legacy=Path(data['legacy']);backup=Path(data['backup'])
    assert hashlib.sha256(legacy.read_bytes()).hexdigest()==data['sha256_after'],'Arquivo legado foi editado novamente; abortando.'
    assert hashlib.sha256(backup.read_bytes()).hexdigest()==data['sha256_before'],'Backup não confere; abortando.'
    subprocess.run(['systemctl','--user','disable','--now','headfollow.service'],check=True)
    legacy.write_bytes(backup.read_bytes())
    marker.rename(root/('controle_exclusivo.restaurado.'+str(int(time.time()))+'.json'))
    print('Legado restaurado. O processo em espera sairá e a ponte poderá iniciá-lo novamente.')

if __name__=='__main__':main()
