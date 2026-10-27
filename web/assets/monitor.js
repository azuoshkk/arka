(() => {
 const el=id=>document.getElementById(id);
 const names={idle:'STANDBY / DIGA ARKA',listening:'CAPTURANDO VOZ',thinking:'PROCESSANDO',speaking:'TTS / FALANDO',error:'FALHA'};
 let cameraReady=false,frameSequence=null,lastFrameAt=0;
 // One bounded request per frame: a stalled MJPEG connection cannot pin the image.
 async function videoLoop(){
  const start=performance.now();
  if(cameraReady&&!document.hidden){
   let url;
   try{
    const response=await fetch('/monitor/frame',{cache:'no-store',signal:AbortSignal.timeout(2000)});
    if(response.status!==200)throw Error('Câmera sem imagem');
    const sequence=response.headers.get('X-Frame-Sequence');
    if(sequence!==frameSequence){
     url=URL.createObjectURL(await response.blob());
     const image=el('camera');
     await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>finish(Error('Quadro não decodificado')),2000);
      function finish(error){clearTimeout(timer);image.onload=image.onerror=null;error?reject(error):resolve();}
      image.onload=()=>finish();image.onerror=()=>finish(Error('Imagem inválida'));image.src=url;
     });
     frameSequence=sequence;lastFrameAt=Date.now();
    }
    if(Date.now()-lastFrameAt>3000){el('camera').removeAttribute('src');el('cameraState').textContent='CÂMERA SEM QUADROS NOVOS';}
   }catch(e){el('camera').removeAttribute('src');frameSequence=null;el('cameraState').textContent='RECONECTANDO CÂMERA';}
   finally{if(url)URL.revokeObjectURL(url);}
  }
  setTimeout(videoLoop,Math.max(50,125-(performance.now()-start)));
 }
 function boxes(detection,age){
  const c=el('boxes'),rect=c.getBoundingClientRect();c.width=Math.round(rect.width);c.height=Math.round(rect.height);
  const ctx=c.getContext('2d'),scale=Math.min(c.width/640,c.height/480),w=640*scale,h=480*scale,ox=(c.width-w)/2,oy=(c.height-h)/2;
  ctx.strokeStyle='#ffffff99';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(c.width/2-12,c.height/2);ctx.lineTo(c.width/2+12,c.height/2);ctx.moveTo(c.width/2,c.height/2-12);ctx.lineTo(c.width/2,c.height/2+12);ctx.stroke();
  const items=age<1.5?(detection?.objects||[]):[];
  el('detector').textContent=age<1.5?`${items.length} OBJETOS // ${detection.ms} ms // 80 CATEGORIAS`:'DETECTOR SEM ATUALIZAÇÃO';
  el('objects').textContent=items.map(o=>o.label).join(' · ');
  ctx.font='12px monospace';
  for(const o of items){
   const [x1,y1,x2,y2]=o.box,x=ox+x1*w,y=oy+y1*h,bw=(x2-x1)*w,bh=(y2-y1)*h;
   const color=o.confidence>=.6?'#55ffd2':'#ffcb66';
   ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(x,y,bw,bh);
   const label=`${o.label.toUpperCase()} ${Math.round(o.confidence*100)}%`,tw=ctx.measureText(label).width+10;
   const lx=Math.min(x,c.width-tw),ly=Math.max(oy,y-19);
   ctx.fillStyle='#00100ee6';ctx.fillRect(lx,ly,tw,19);ctx.fillStyle=color;ctx.fillText(label,lx+5,ly+14);
  }
 }

 el('fullscreen').onclick=()=>document.documentElement.requestFullscreen();
 el('analyze').onclick=async()=>{try{await fetch('/monitor/analyze',{method:'POST'});el('visionStatus').textContent='NA FILA';}catch(e){el('error').textContent=e.message;}};
 async function poll(){
  try{
   const r=await fetch('/monitor/state',{signal:AbortSignal.timeout(3000)});if(!r.ok)throw Error('Painel indisponível');
   const {status:s,age,detection,detectionAge}=await r.json();boxes(detection,detectionAge);
   el('connection').textContent=age<3?'LINK SSH // ONLINE':'LINK // SEM TELEMETRIA';
   el('state').textContent=age<3?(s.armedUntil>Date.now()?'ARKA ATIVADA / FALE':names[s.state]||'INICIANDO'):'OFFLINE';
   el('level').value=age<3?Math.min(1,(s.level||0)*5):0;
   el('mic').textContent=s.ready?'MIC ONLINE | RUÍDO: '+(s.audioSettings?.noiseSuppression?'SUPRIMIDO':'FILTRO DE VOZ'):'MIC DESCONECTADO';
   for(const key of ['heard','answer'])if(s[key])el(key).textContent=s[key];
   el('vision').textContent=s.visionState==='analyzing'?'CAPTURANDO E ANALISANDO NOVA IMAGEM…':s.vision||'Aguardando análise.';
   el('error').textContent=s.cameraError||s.error||(s.piTemperature>=78?`RASPBERRY ${s.piTemperature} °C / VÍDEO REDUZIDO PARA RESFRIAMENTO`:'');
   el('cameraState').textContent=s.camera&&age<3?`CAM 01 // ${s.fps||0} FPS // 640×480`:'CAM 01 // AGUARDANDO';
   el('visionStatus').textContent=s.visionState==='analyzing'?'ANALISANDO NO SERVIDOR…':s.visionState==='ready'?`CAPTURA ${new Date(s.visionCapturedAt||s.visionAt).toLocaleTimeString('pt-BR')} // ${(s.visionMs/1000).toFixed(1)} s // ${s.visionFrame||''}`:s.visionState==='error'?'ERRO NA ANÁLISE':'PRONTA';
   el('analyze').disabled=s.visionState==='analyzing';
   cameraReady=!!s.camera&&age<3;
   if(!cameraReady){el('camera').removeAttribute('src');frameSequence=null;}
  }catch(e){el('connection').textContent='LINK INTERROMPIDO';el('error').textContent=e.message;cameraReady=false;el('camera').removeAttribute('src');frameSequence=null;}
  setTimeout(poll,500);
 }
 void poll();void videoLoop();
})();
