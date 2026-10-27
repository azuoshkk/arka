#!/usr/bin/env python3
"""Download only the public OpenCV Zoo ONNX; verify integrity before use."""
from pathlib import Path
import hashlib
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
URL='https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx'
SHA='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
p=ROOT/'.local/models/yolox-s.onnx'
if p.exists():
    if hashlib.sha256(p.read_bytes()).hexdigest()!=SHA:raise SystemExit('Modelo existente diferente; preserve-o antes de substituir.')
    print('Modelo já verificado.')
else:
    with urllib.request.urlopen(URL,timeout=90) as response:data=response.read(40*1024*1024)
    if hashlib.sha256(data).hexdigest()!=SHA:raise SystemExit('Integridade inválida; nada salvo.')
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);print('YOLOX-S verificado.')
