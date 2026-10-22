"""Server-only password verification and bounded login throttling."""
from pathlib import Path
import hashlib, hmac, json, os, secrets, threading, time
ROOT=Path(__file__).resolve().parents[3]
ACCESS_FILE=ROOT/'.local'/'access.json'
_lock=threading.Lock()
_attempts={}

def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def make_user(password,role='viewer'):
    salt=secrets.token_hex(16)
    return {'salt':salt,'hash':password_hash(password,salt),'role':role}

def users():
    try:return json.loads(ACCESS_FILE.read_text())['users']
    except (OSError,ValueError,KeyError):return {}

def required():
    return bool(users()) or os.getenv('ARKA_REQUIRE_LOGIN')=='1'

def authenticate(username,password,client):
    now=time.monotonic()
    with _lock:
        for key,entries in list(_attempts.items()):
            _attempts[key]=[value for value in entries if now-value<60]
            if not _attempts[key]:del _attempts[key]
        entries=_attempts.setdefault(client,[])
        if len(entries)>=5 or len(_attempts)>2048:raise RuntimeError('Muitas tentativas. Aguarde um minuto.')
        entries.append(now)
    account=users().get(username)
    salt=account['salt'] if account else '0'*32
    result=password_hash(password,salt)
    if account and hmac.compare_digest(result,account['hash']):
        return account['role']
    return None
