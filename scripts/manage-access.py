#!/usr/bin/env python3
"""Create/update local accounts. Passwords are never command-line arguments."""
from pathlib import Path
import argparse, getpass, json, os, secrets, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'robot-server'))
from app.core.access import ACCESS_FILE,make_user
p=argparse.ArgumentParser();p.add_argument('--user',required=True);p.add_argument('--role',choices=['admin','viewer'],default='viewer');p.add_argument('--generate',action='store_true');a=p.parse_args()
if not a.user.isalnum() or len(a.user)>40:raise SystemExit('Use nome de usuário alfanumérico, até 40 caracteres.')
password=secrets.token_urlsafe(18) if a.generate else getpass.getpass('Senha (mínimo 12 caracteres): ')
if len(password)<12:raise SystemExit('Senha muito curta.')
if not a.generate and password!=getpass.getpass('Repita a senha: '):raise SystemExit('Senhas diferentes.')
ACCESS_FILE.parent.mkdir(mode=0o700,exist_ok=True)
data=json.loads(ACCESS_FILE.read_text()) if ACCESS_FILE.exists() else {'users':{}}
data['users'][a.user]=make_user(password,a.role)
tmp=ACCESS_FILE.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2));os.chmod(tmp,0o600);tmp.replace(ACCESS_FILE)
if a.generate:
    dest=ACCESS_FILE.parent/(a.user+'-login.txt');dest.write_text('Usuário: '+a.user+'\nSenha: '+password+'\n');os.chmod(dest,0o600)
    print('Credenciais gravadas somente no servidor:',dest)
print('Conta configurada. Reinicie a aplicação para invalidar sessões antigas.')
