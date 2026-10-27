const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
(async()=>{
 const elements=new Map(),timers=[];let frameRequests=0,revoked=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'',removeAttribute(){},getBoundingClientRect:()=>({width:640,height:480}),getContext:()=>new Proxy({measureText:()=>({width:1})},{get:(o,k)=>o[k]||(()=>{})}),set src(v){queueMicrotask(()=>this.onload?.());}});return elements.get(id);};
 const context={document:{hidden:false,getElementById:element,documentElement:{}},performance:{now:()=>0},Date,Math,Promise,Error,AbortSignal,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>revoked++},setTimeout:(fn,delay)=>{timers.push({fn,delay});return timers.length;},clearTimeout:()=>{},fetch:async path=>{
  if(path==='/monitor/state')return {ok:true,json:async()=>({status:{camera:true},age:0,detectionAge:9})};
  frameRequests++;if(frameRequests===1)throw Error('Network timeout');
  return {status:200,headers:{get:()=>String(frameRequests)},blob:async()=>({})};
 }};
 vm.runInNewContext(fs.readFileSync('web/assets/monitor.js','utf8'),context);
 const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};await flush();
 for(let i=0;i<2;i++){const index=timers.findIndex(t=>t.fn.name==='videoLoop');assert(index>=0);timers.splice(index,1)[0].fn();await flush();}
 assert.equal(frameRequests,2,'Video retries after a failed request');assert.equal(revoked,1,'Decoded frame blob is released');
 console.log('PASS: frame failure retries; successful frame decodes and releases memory');
})();
