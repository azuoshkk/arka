#!/usr/bin/env python3
"""Executar no Orin: preserva o legado e habilita exclusividade + serviço headFollow.
Não inicia serviço nem envia comandos. Deve ser seguido por parada do processo
legado identificado e systemctl --user enable --now headfollow.service.
"""
import hashlib
import json
from pathlib import Path
import time

root=Path('/home/ubuntu/headFollow')
legacy=Path('/home/ubuntu/scripts-ipq/beniFiles/neck_controller.py')
marker=root/'controle_exclusivo.json'
sentinel='# HEADFOLLOW_EXCLUSIVE_GUARD'
source=legacy.read_text()
old='if __name__ == "__main__":\n    main()'
new='''if __name__ == "__main__":
    # HEADFOLLOW_EXCLUSIVE_GUARD
    if os.path.exists("/home/ubuntu/headFollow/controle_exclusivo.json"):
        import runpy
        runpy.run_path("/home/ubuntu/headFollow/standby_legacy.py", run_name="__main__")
    else:
        main()'''
if sentinel not in source:
    if source.count(old)!=1:raise SystemExit('Entrada do legado mudou; nenhuma alteração feita.')
    backup=root/('neck_controller.before_headfollow.'+time.strftime('%Y%m%d_%H%M%S')+'.py')
    backup.write_text(source)
    patched=source.replace(old,new)
    compile(patched,str(legacy),'exec')
    legacy.write_text(patched)
    marker.write_text(json.dumps({'backup':str(backup),'legacy':str(legacy),
        'sha256_before':hashlib.sha256(source.encode()).hexdigest(),
        'sha256_after':hashlib.sha256(patched.encode()).hexdigest()},indent=2))
elif not marker.exists():
    raise SystemExit('Guard existente sem registro; verificar backup antes de reativar.')
unit=Path.home()/'.config/systemd/user/headfollow.service'
unit.parent.mkdir(parents=True,exist_ok=True)
unit.write_text('''[Unit]
Description=headFollow - controle exclusivo do pescoco T800
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/headFollow
ExecStart=/bin/bash /home/ubuntu/headFollow/iniciar_robo.sh --enable-motion --port 8766
Restart=on-failure
RestartSec=3
TimeoutStopSec=5

[Install]
WantedBy=default.target
''')
print(marker.read_text())
print('Unidade criada:',unit)
