"""Ephemeral, per-tab sessions. Run one Uvicorn worker."""
from dataclasses import dataclass, field
from threading import Lock
import secrets
import time
from app.core.voice_bridge import VoiceContext

@dataclass
class Session:
    token: str
    username: str | None = None
    role: str = 'guest'
    context: VoiceContext = field(default_factory=VoiceContext)
    history: list = field(default_factory=list)
    answers: dict = field(default_factory=dict)
    lock: object = field(default_factory=Lock)
    state: str = 'idle'
    touched: float = field(default_factory=time.monotonic)

class SessionStore:
    def __init__(self, ttl=7200, capacity=128):
        self.ttl, self.capacity = ttl, capacity
        self.sessions = {}
        self.lock = Lock()

    def create(self):
        with self.lock:
            now = time.monotonic()
            for key, value in list(self.sessions.items()):
                if now - value.touched > self.ttl and not value.lock.locked():
                    del self.sessions[key]
            if len(self.sessions) >= self.capacity:
                raise RuntimeError('Limite de sessões atingido. Tente mais tarde.')
            session = Session(secrets.token_urlsafe(32))
            self.sessions[session.token] = session
            return session

    def get(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if session is None:
                return None
            if time.monotonic() - session.touched > self.ttl and not session.lock.locked():
                del self.sessions[token]
                return None
            session.touched = time.monotonic()
            return session
