"""Isolated incremental PDF collection, with draft validation before publication."""
from contextvars import ContextVar
from pathlib import Path
import hashlib, json, os, sqlite3, subprocess, sys, threading, uuid
from app.knowledge.chunker import chunk_text
from app.knowledge.embedder import embed_texts
from app.knowledge.teaching import teachings, normalize
from qdrant_client import models
COLLECTION='arka_training'
preview_document=ContextVar('preview_document',default=None)
_lock=threading.RLock()
ROOT=Path(__file__).resolve().parents[3]
UPLOADS=ROOT/'robot-server'/'data'/'training_uploads'

def connect():
    c=teachings.connect()
    c.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, name TEXT, sha256 TEXT UNIQUE, pages INTEGER, chunks INTEGER, status TEXT, author TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS validations (document_id TEXT, question TEXT, expected TEXT, result TEXT, passed INTEGER, updated TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(document_id,question))')
    return c

def documents():
    with connect() as c:
        rows=[dict(row) for row in c.execute('SELECT * FROM documents ORDER BY created DESC LIMIT 100')]
        for row in rows:
            row['validations']=[json.loads(v[0]) for v in c.execute('SELECT result FROM validations WHERE document_id=?',(row['id'],))]
        return rows

def upload(data,name,author):
    from app.knowledge.vector_store import client
    if not data.startswith(b'%PDF-'):raise ValueError('Envie um arquivo PDF válido.')
    digest=hashlib.sha256(data).hexdigest()
    with _lock,connect() as c:
        previous=c.execute('SELECT id FROM documents WHERE sha256=?',(digest,)).fetchone()
        if previous:raise ValueError('Este PDF já foi importado. Use o documento existente.')
        if c.execute('SELECT count(*) FROM documents').fetchone()[0]>=100:raise ValueError('Limite de 100 PDFs atingido.')
        identifier=uuid.uuid4().hex
        UPLOADS.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=UPLOADS/(identifier+'.pdf');path.write_bytes(data);os.chmod(path,0o600)
        try:
            result=subprocess.run([sys.executable,'-m','app.knowledge.pdf_extract',str(path)],cwd=ROOT/'robot-server',capture_output=True,text=True,timeout=25)
            if result.returncode:
                detail=result.stderr.splitlines()[-1] if result.stderr else 'PDF inválido ou limite de extração excedido.'
                raise ValueError(detail.removeprefix('ValueError: ')[:200])
            parsed=json.loads(result.stdout)
            chunks=[{**part,'page':page['page']} for page in parsed['pages'] for part in chunk_text(page['text'])]
            if len(chunks)>100:raise ValueError('PDF muito extenso: divida em arquivos menores.')
            vectors=embed_texts([x['text'] for x in chunks])
            if not client.collection_exists(COLLECTION):
                client.create_collection(COLLECTION,vectors_config=models.VectorParams(size=len(vectors[0]),distance=models.Distance.COSINE))
            safe_name=Path(name.replace('\\','/')).name[:150]
            safe_name=''.join(ch for ch in safe_name if ch.isprintable()) or 'documento.pdf'
            points=[models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL,identifier+':'+str(i))),vector=vector,payload={
                'project':'t800','access':'internal','category':'training','importance':'normal',
                'state':'draft','approved':False,'document_id':identifier,'source':safe_name,
                'package_path':'training/'+identifier+'/'+safe_name,'text':chunk['text'],'page':chunk['page'],
                'chunk_index':i,'chunk_sha256':hashlib.sha256(chunk['text'].encode()).hexdigest(),
            }) for i,(chunk,vector) in enumerate(zip(chunks,vectors))]
            client.upsert(COLLECTION,points=points,wait=True)
            c.execute('INSERT INTO documents(id,name,sha256,pages,chunks,status,author) VALUES (?,?,?,?,?,?,?)',(identifier,safe_name,digest,parsed['page_count'],len(chunks),'draft',author))
        except Exception:
            # Retain uploaded source for diagnosis; it is never published on failure.
            raise
    return identifier


def upload_and_publish(data, name, author):
    """
    Importa PDF, gera embeddings e publica imediatamente
    na base corporativa usada pelo RAG.
    """
    identifier = upload(
        data,
        name,
        author,
    )

    from app.knowledge.vector_store import client

    with _lock, connect() as c:
        client.set_payload(
            COLLECTION,
            payload={
                "approved": True,
                "state": "published",
            },
            points=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(
                            value=identifier
                        ),
                    )
                ]
            ),
            wait=True,
        )

        c.execute(
            "UPDATE documents SET status=? WHERE id=?",
            (
                "published",
                identifier,
            ),
        )

    return identifier


def validate(identifier,question,expected):
    from app.agents.expert import answer,retrieve
    from app.core.web_conversation import MODEL_LOCK,display_name,public_sources
    with _lock,connect() as c:
        row=c.execute('SELECT * FROM documents WHERE id=?',(identifier,)).fetchone()
        if not row:raise ValueError('PDF não encontrado.')
        marker=preview_document.set(identifier)
        try:
            with MODEL_LOCK:
                result=answer(question,'t800')
                evidence=retrieve(question,'t800')
            own=[r for r in evidence if (r.payload or {}).get('document_id')==identifier]
            evidence_match=any(normalize(expected) in normalize((r.payload or {}).get('text','')) for r in own)
            answer_match=normalize(expected) in normalize(result['answer'])
            source_match=any('/'+identifier+'/' in (s.get('path') or '') for s in result.get('sources',[]))
            passed=bool(evidence_match and answer_match and source_match)
            report={'question':question,'expected':expected,'passed':passed,'answer':display_name(result['answer']),
                    'sources':public_sources(result.get('sources',[])),
                    'checks':{'evidence_in_pdf':evidence_match,'expected_in_answer':answer_match,'pdf_cited':source_match},
                    'note':'Verificação de evidência e trecho esperado; revise a resposta antes de publicar.'}
            c.execute('INSERT INTO validations(document_id,question,expected,result,passed) VALUES (?,?,?,?,?) ON CONFLICT(document_id,question) DO UPDATE SET expected=excluded.expected,result=excluded.result,passed=excluded.passed,updated=CURRENT_TIMESTAMP',(identifier,question,expected,json.dumps(report,ensure_ascii=False),int(passed)))
            return report
        finally:preview_document.reset(marker)

def publish(identifier,active):
    from app.knowledge.vector_store import client
    with _lock,connect() as c:
        if not c.execute('SELECT id FROM documents WHERE id=?',(identifier,)).fetchone():raise ValueError('PDF não encontrado.')
        checks=c.execute('SELECT passed FROM validations WHERE document_id=?',(identifier,)).fetchall()
        if active and (not checks or not all(row[0] for row in checks)):
            raise ValueError('Valide pelo menos uma pergunta; todos os testes salvos devem passar antes de publicar.')
        client.set_payload(COLLECTION,payload={'approved':bool(active),'state':'published' if active else 'draft'},points=models.Filter(must=[models.FieldCondition(key='document_id',match=models.MatchValue(value=identifier))]),wait=True)
        c.execute('UPDATE documents SET status=? WHERE id=?',('published' if active else 'draft',identifier))
