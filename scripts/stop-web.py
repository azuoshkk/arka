#!/usr/bin/env python3
"""Stop only this project's web processes; never touch Ollama/Qdrant/CLI voice."""
from pathlib import Path
import os, signal, time
ROOT=Path(__file__).resolve().parents[1]
found=[]
for directory in Path('/proc').iterdir():
    if not directory.name.isdigit() or int(directory.name)==os.getpid():continue
    try:
        args=(directory/'cmdline').read_bytes().split(b'\0')
        args=[a.decode(errors='replace') for a in args if a]
        cwd=(directory/'cwd').resolve()
        own_launcher=str(ROOT/'scripts/start-web.py') in args
        own_preview='app.api.web:app' in args and cwd==ROOT/'robot-server' and 'uvicorn' in args
        if own_launcher or own_preview:
            pid=int(directory.name)
            os.kill(pid,signal.SIGTERM);found.append(pid)
    except (OSError,ValueError):continue
for _ in range(300):
    if all(not Path('/proc',str(pid)).exists() for pid in found):break
    time.sleep(.1)
if any(Path('/proc',str(pid)).exists() for pid in found):
    raise SystemExit('O servidor ainda está encerrando. Aguarde antes de tentar novamente; nenhum processo foi forçado.')
print('Processos web encerrados:',len(found))
