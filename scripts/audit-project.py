#!/usr/bin/env python3
"""Read-only inventory and exact duplicates; never deletes or reindexes."""
from pathlib import Path
import os, hashlib, json, csv
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1]
rows=[];hashes=defaultdict(list)
for base,dirs,files in os.walk(ROOT,followlinks=False):
    for name in files:
        path=Path(base)/name;relative=path.relative_to(ROOT);parts=relative.parts
        if path.is_symlink():
            rows.append([str(relative),'ativo','Link de compatibilidade',0]);continue
        kind='ativo';reason='Dependência, configuração, código ou documento preservado'
        if 'backups' in parts or 'source-snapshots' in parts:kind='backup';reason='Recuperação preservada'
        elif '__pycache__' in parts or name.endswith('.pyc'):kind='temporário';reason='Cache regenerável'
        elif 'archive' in parts:kind='legado';reason='Histórico/patch arquivado'
        elif name.startswith(('test_','validate')) or 'tests' in parts or 'test_results' in parts:kind='teste';reason='Validação/resultado preservado'
        elif name.endswith('.log'):reason='Log centralizado'
        size=path.stat().st_size
        rows.append([str(relative),kind,reason,size])
        # Dependencies and versioned backups have intentional duplicates; do not hash 7GB of models.
        if not any(x in parts for x in ('.venv','.local','backups','logs','qdrant_storage','__pycache__')) and size:
            digest=hashlib.sha256(path.read_bytes()).hexdigest();hashes[digest].append(str(relative))
duplicates=[{'sha256':key,'files':files,'action':'preservado: pode haver referências distintas no RAG'} for key,files in hashes.items() if len(files)>1]
duplicate_paths={path for group in duplicates for path in group['files'][1:]}
for row in rows:
    if row[0] in duplicate_paths and row[1]=='ativo':row[1]='duplicado';row[2]='Cópia idêntica preservada; referências do RAG podem depender do caminho'
with (ROOT/'archive/inventory-final.csv').open('w') as f:
    w=csv.writer(f);w.writerow(['path','classification','reason','bytes']);w.writerows(rows)
(ROOT/'archive/duplicates.json').write_text(json.dumps(duplicates,ensure_ascii=False,indent=2))
counts=dict(Counter(row[1] for row in rows));counts.setdefault('descartável',0)
(ROOT/'archive/audit-summary.json').write_text(json.dumps({'files':len(rows),'classifications':counts,'duplicate_groups':len(duplicates),'disposable_policy':'Somente caches comprovados removidos após backup; nenhum documento do RAG removido.'},ensure_ascii=False,indent=2))
print(json.dumps(counts,ensure_ascii=False));print('Exact duplicate groups:',len(duplicates))
