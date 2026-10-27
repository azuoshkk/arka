#!/usr/bin/env python3
"""CPU-only notebook detector. Frames/results stay in RAM, via the SSH tunnel.
YOLOX-S model: OpenCV Zoo, Apache-2.0. See OBJECT-DETECTION.md.
"""
import io,json,time,os,sys
from pathlib import Path
import numpy as np
import onnxruntime as ort
import requests
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
LABELS='pessoa|bicicleta|carro|moto|avião|ônibus|trem|caminhão|barco|semáforo|hidrante|placa de pare|parquímetro|banco|pássaro|gato|cachorro|cavalo|ovelha|vaca|elefante|urso|zebra|girafa|mochila|guarda-chuva|bolsa|gravata|mala|frisbee|esquis|snowboard|bola|pipa|taco de beisebol|luva de beisebol|skate|prancha de surfe|raquete|garrafa|taça|copo|garfo|faca|colher|tigela|banana|maçã|sanduíche|laranja|brócolis|cenoura|cachorro-quente|pizza|rosquinha|bolo|cadeira|sofá|planta em vaso|cama|mesa|vaso sanitário|tela|notebook|mouse|controle remoto|teclado|celular|micro-ondas|forno|torradeira|pia|geladeira|livro|relógio|vaso|tesoura|urso de pelúcia|secador|escova de dentes'.split('|')

def nms(boxes,scores,classes,threshold=.5,limit=60):
    order=np.argsort(scores)[::-1];keep=[]
    while len(order) and len(keep)<limit:
        i=order[0];keep.append(i);order=order[1:]
        if not len(order):break
        lo=np.maximum(boxes[i,:2],boxes[order,:2]);hi=np.minimum(boxes[i,2:],boxes[order,2:])
        inter=np.prod(np.maximum(hi-lo,0),axis=1)
        area=np.prod(np.maximum(boxes[order,2:]-boxes[order,:2],0),axis=1)
        base=np.prod(np.maximum(boxes[i,2:]-boxes[i,:2],0))
        iou=inter/np.maximum(base+area-inter,1e-6)
        order=order[(iou<=threshold)|(classes[order]!=classes[i])]
    return keep

class Detector:
    def __init__(self,path):
        ort.disable_telemetry_events()
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.input=self.session.get_inputs()[0].name
        grids=[];strides=[]
        for stride in (8,16,32):
            x,y=np.meshgrid(np.arange(640//stride),np.arange(640//stride))
            grid=np.stack((x,y),axis=2).reshape(-1,2)
            grids.append(grid);strides.append(np.full((len(grid),1),stride))
        self.grid=np.concatenate(grids);self.strides=np.concatenate(strides)
    def detect(self,data):
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height>4000000:raise ValueError('Image too large')
            image=image.convert('RGB');w,h=image.size;ratio=min(640/w,640/h)
            image=image.resize((int(w*ratio),int(h*ratio)),Image.Resampling.BILINEAR)
            arr=np.full((640,640,3),114,dtype=np.float32)
            arr[:image.height,:image.width]=np.asarray(image)
        pred=self.session.run(None,{self.input:arr.transpose(2,0,1)[None]})[0][0]
        scores=pred[:,4,None]*pred[:,5:];classes=scores.argmax(axis=1);confidence=scores.max(axis=1)
        valid=confidence>=.35
        p=pred[valid];centers=(p[:,:2]+self.grid[valid])*self.strides[valid]
        sizes=np.exp(np.clip(p[:,2:4],-20,20))*self.strides[valid]
        boxes=np.concatenate((centers-sizes/2,centers+sizes/2),axis=1)/ratio
        boxes[:,[0,2]]=np.clip(boxes[:,[0,2]]/w,0,1);boxes[:,[1,3]]=np.clip(boxes[:,[1,3]]/h,0,1)
        scores=confidence[valid];classes=classes[valid]
        return [{'label':LABELS[int(classes[i])],'class':int(classes[i]),'confidence':round(float(scores[i]),3),'box':[round(float(v),4) for v in boxes[i]]} for i in nms(boxes,scores,classes) if boxes[i,2]>boxes[i,0] and boxes[i,3]>boxes[i,1]]

def main():
    import fcntl
    lock=(ROOT/'.local/detector.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Detector já ativo.')
    detector=Detector(ROOT/'.local/models/yolox-s.onnx')
    http=requests.Session();base='http://127.0.0.1:8765';last=None
    print('YOLOX-S: CPU, 80 categorias, sem gravação.',flush=True)
    while True:
        started=time.monotonic()
        try:
            info=http.get(base+'/monitor/enabled',timeout=3).json()
            if not info['active']:time.sleep(1);continue
            frame=http.get(base+'/monitor/frame',timeout=3)
            if frame.status_code!=200:time.sleep(.3);continue
            seq=frame.headers.get('X-Frame-Sequence')
            if seq is not None and seq==last:time.sleep(.1);continue
            last=seq
            objects=detector.detect(frame.content)
            elapsed=round((time.monotonic()-started)*1000)
            http.post(base+'/monitor/detections',json={'objects':objects,'ms':elapsed,'seq':seq,'model':'YOLOX-S / CPU'},headers={'Origin':base},timeout=3).raise_for_status()
        except (requests.RequestException,ValueError,OSError):
            time.sleep(1)
        time.sleep(max(0,.25-(time.monotonic()-started)))
if __name__=='__main__':main()
