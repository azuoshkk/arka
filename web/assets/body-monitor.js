(() => {
 let objects=[],stream,video,stopped=false,active=false,command=0,done=0,analyzing=false,frames=0,last=performance.now(),fps=0,temperature=0;
 const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
 const ctx=canvas.getContext('2d');
 const send=(path,body)=>fetch(path,{method:'POST',body,signal:AbortSignal.timeout(4000)});
 async function freshSnapshot(target=null){
  if(!video || video.readyState<2)throw Error('Câmera indisponível');
  const current=video;
  await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Error('Câmera sem quadros novos')),2000);
   current.requestVideoFrameCallback(()=>{clearTimeout(timer);resolve();});
  });
  if(video!==current || !stream?.active)throw Error('Câmera desconectada');
  let x=0,y=0,w=1,h=1;
  if(target){const [x1,y1,x2,y2]=target.box,pad=.04;x=Math.max(0,x1-pad);y=Math.max(0,y1-pad);w=Math.min(1,x2+pad)-x;h=Math.min(1,y2+pad)-y;}
  const c=document.createElement('canvas');c.width=Math.max(1,Math.round(w*640));c.height=Math.max(1,Math.round(h*480));
  c.getContext('2d').drawImage(current,x*current.videoWidth,y*current.videoHeight,w*current.videoWidth,h*current.videoHeight,0,0,c.width,c.height);
  const blob=await new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.85));
  const hash=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
  window.arkaBody.visionFrame=[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,12);
  window.arkaBody.visionCapturedAt=Date.now();
  return blob;
 }
 function close(){stream?.getTracks().forEach(t=>t.stop());stream=null;video=null;}
 async function frame(){
  if(!video || video.readyState<2)return null;
  ctx.drawImage(video,0,0,640,480);
  return new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.5));
 }
 window.arkaObjectSnapshot=text=>{
  window.arkaBody.visualTarget=null;
  const target=window.arkaVisionIntent.target(text,objects);
  if(!target || !video || video.readyState<2)return null;
  window.arkaBody.visualTarget=target.label;
  return freshSnapshot(target);
 };
 window.arkaCameraSnapshot=()=>video?.readyState>=2?freshSnapshot():null;
 async function videoLoop(){
  const start=performance.now();
  try{
   if(active && !stream){
    const devices=await navigator.mediaDevices.enumerateDevices();
    const cam=devices.find(d=>d.kind==='videoinput'&&/C920/i.test(d.label));
    if(!cam)throw Error('C920 desconectada');
    stream=await navigator.mediaDevices.getUserMedia({video:{deviceId:{exact:cam.deviceId},width:{ideal:640},height:{ideal:480},frameRate:{ideal:10,max:10}},audio:false});
    video=document.createElement('video');video.muted=true;video.playsInline=true;video.srcObject=stream;await video.play();
    stream.getVideoTracks()[0].addEventListener('ended',close,{once:true});
   }
   if(!active)close();
   if(active){const jpeg=await frame();if(jpeg){await send('/monitor/frame',jpeg);frames++;}}
   window.arkaBody.cameraError=null;
  }catch(e){window.arkaBody.cameraError=e.message;if(!stream?.active)close();}
  if(performance.now()-last>=1000){fps=Math.round(frames*10000/(performance.now()-last))/10;frames=0;last=performance.now();}
  if(!stopped)setTimeout(videoLoop,Math.max(0,(temperature>=78?200:125)-(performance.now()-start)));
 }
 async function telemetry(){
  try{
   const info=await (await fetch('/monitor/enabled',{signal:AbortSignal.timeout(4000)})).json();active=info.active;command=info.request;objects=info.objects||[];temperature=info.temperature;window.arkaBody.piTemperature=temperature;
   await send('/monitor/status',JSON.stringify({...window.arkaBody,state:document.getElementById('stage').dataset.state,camera:!!stream?.active,fps,visionCommand:done}));
   if(active&&command>done&&!analyzing&&video?.readyState>=2){
    analyzing=true;const requested=command;
    window.arkaAnalyzeView().then(ok=>{if(ok)done=requested;}).finally(()=>{analyzing=false;});
   }
  }catch(e){active=false;}
  if(!stopped)setTimeout(telemetry,500);
 }
 window.addEventListener('pagehide',()=>{stopped=true;close();});
 void telemetry();void videoLoop();
})();
