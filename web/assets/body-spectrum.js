'use strict';
(() => {
 const canvas=document.getElementById('voice-spectrum'), audio=document.getElementById('player');
 if(!canvas||!audio)return;
 const ctx=canvas.getContext('2d');let audioCtx,analyser,source,bins,raf=null,lastFrame=0;
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 async function resume(){
  const AudioCtx=window.AudioContext||window.webkitAudioContext;if(!AudioCtx)return;
  if(!audioCtx){audioCtx=new AudioCtx();analyser=audioCtx.createAnalyser();analyser.fftSize=512;analyser.smoothingTimeConstant=.86;bins=new Uint8Array(analyser.frequencyBinCount);source=audioCtx.createMediaElementSource(audio);source.connect(analyser);analyser.connect(audioCtx.destination);}
  if(audioCtx.state==='suspended')await audioCtx.resume();
 }
 window.arkaSpectrum={resume};
 document.addEventListener('pointerdown',()=>{resume().catch(()=>{});},{once:true});
 document.addEventListener('keydown',()=>{resume().catch(()=>{});},{once:true});
 function draw(){
  if(!analyser||audio.paused){raf=null;return;}
  const now=performance.now();if(now-lastFrame<33){raf=requestAnimationFrame(draw);return;}lastFrame=now;
  analyser.getByteFrequencyData(bins);
  const size=320,dpr=Math.min(devicePixelRatio||1,2);
  if(canvas.width!==size*dpr){canvas.width=size*dpr;canvas.height=size*dpr;}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,size,size);
  let energy=0;for(let i=2;i<100;i++)energy+=bins[i]/255;energy/=98;
  const time=reduced.matches?0:audio.currentTime;
  const halo=ctx.createRadialGradient(160,160,60,160,160,154);halo.addColorStop(0,'rgba(38,130,237,0)');halo.addColorStop(.7,'rgba(50,146,255,'+(.025+energy*.08)+')');halo.addColorStop(1,'rgba(31,104,211,0)');ctx.fillStyle=halo;ctx.fillRect(0,0,size,size);
  const gradient=ctx.createLinearGradient(45,40,280,280);gradient.addColorStop(0,'#063f89');gradient.addColorStop(.3,'#168bea');gradient.addColorStop(.55,'#70d1ff');gradient.addColorStop(.76,'#2f77da');gradient.addColorStop(1,'#064b94');
  ctx.strokeStyle=gradient;ctx.lineWidth=.8;ctx.lineJoin='round';
  for(let strand=0;strand<22;strand++){
   const layer=strand/21,phase=layer*Math.PI*1.5;
   ctx.beginPath();
   for(let point=0;point<=140;point++){
    const angle=point/140*Math.PI*2;
    const index=3+Math.floor((.5+.5*Math.sin(angle*2+phase))*88);
    const level=bins[index]/255;
    const amplitude=5+energy*21+level*11;
    const radius=92+layer*13+Math.sin(angle*5+time*.95+phase)*amplitude+Math.sin(angle*3-time*.6+phase*1.4)*(5+energy*15)+Math.cos(angle*8+phase-time*.25)*level*7;
    const x=160+Math.cos(angle)*radius,y=160+Math.sin(angle)*radius;
    if(!point)ctx.moveTo(x,y);else ctx.lineTo(x,y);
   }
   ctx.closePath();ctx.globalAlpha=.12+.11*Math.sin(layer*Math.PI)+energy*.16;ctx.stroke();
  }
  ctx.globalAlpha=1;
  raf=requestAnimationFrame(draw);
 }
 audio.addEventListener('play',async()=>{try{await resume();if(!raf)draw();}catch{}});
 function stop(){if(raf)cancelAnimationFrame(raf);raf=null;ctx.clearRect(0,0,canvas.width,canvas.height);}
 audio.addEventListener('pause',stop);audio.addEventListener('ended',stop);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else if(!audio.paused&&!raf)draw();});
})();
