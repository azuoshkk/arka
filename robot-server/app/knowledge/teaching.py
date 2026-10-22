"""Editable, exact-match FAQs. Technical routes still use existing RAG guards.
No weight training, no existing collection changes, no automatic ingestion.
"""
from pathlib import Path
import sqlite3, unicodedata, re, uuid
ROOT=Path(__file__).resolve().parents[3]
DB=ROOT/'robot-server'/'data'/'teaching.sqlite3'

def normalize(text):
    text=unicodedata.normalize('NFKD',text.lower())
    text=''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+',text))

class TeachingStore:
    def __init__(self,path=DB):self.path=Path(path)
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path,timeout=10)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, question TEXT NOT NULL, normalized TEXT NOT NULL, answer TEXT NOT NULL, active INTEGER NOT NULL, author TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS active_question ON lessons(normalized) WHERE active=1')
        conn.execute('CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, lesson_id TEXT, snapshot TEXT, changed TEXT DEFAULT CURRENT_TIMESTAMP)')
        return conn
    def list(self):
        with self.connect() as c:return [dict(row) for row in c.execute('SELECT * FROM lessons ORDER BY updated DESC LIMIT 500')]
    def save(self,question,answer,author,active=True,lesson_id=None):
        import json
        question,answer=question.strip(),answer.strip()
        if not normalize(question) or not answer:raise ValueError('Preencha a pergunta e a resposta.')
        with self.connect() as c:
            if lesson_id:
                previous=c.execute('SELECT * FROM lessons WHERE id=?',(lesson_id,)).fetchone()
                if previous is None:raise ValueError('Ensinamento não encontrado.')
                c.execute('INSERT INTO revisions(lesson_id,snapshot) VALUES (?,?)',(lesson_id,json.dumps(dict(previous),ensure_ascii=False)))
            else:
                if c.execute('SELECT count(*) FROM lessons').fetchone()[0]>=500:raise ValueError('Limite de 500 ensinamentos. Edite os existentes.')
                lesson_id=uuid.uuid4().hex
            try:
                c.execute('INSERT INTO lessons(id,question,normalized,answer,active,author) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET question=excluded.question, normalized=excluded.normalized, answer=excluded.answer, active=excluded.active, author=excluded.author, updated=CURRENT_TIMESTAMP',(lesson_id,question,normalize(question),answer,int(active),author))
            except sqlite3.IntegrityError as exc:raise ValueError('Já existe uma resposta ativa para esta pergunta. Edite-a.') from exc
        return lesson_id
    def match(self,question):
        if not self.path.exists():return None
        with self.connect() as c:
            row=c.execute('SELECT id,question,answer FROM lessons WHERE normalized=? AND active=1',(normalize(question),)).fetchone()
            return dict(row) if row else None

teachings=TeachingStore()
