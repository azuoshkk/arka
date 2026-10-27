const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/assets/body-monitor.js','utf8');
const a=source.indexOf(' async function telemetry(){'),b=source.indexOf(" window.addEventListener('pagehide'",a);
let requested=1,resolveWork,calls=0;
const scope={fetch:async()=>({json:async()=>({active:true,request:requested,objects:[]})}),AbortSignal,JSON,
 send:async()=>{},setTimeout:()=>{},document:{getElementById:()=>({dataset:{state:'idle'}})},
 window:{arkaBody:{},arkaAnalyzeView:()=>{calls++;return new Promise(r=>resolveWork=r);}}};
vm.createContext(scope);
vm.runInContext('let active=false,command=0,done=0,analyzing=false,stopped=true,objects=[],stream={active:true},video={readyState:2},fps=10;'+source.slice(a,b)+'this.run=telemetry;this.state=()=>({done,analyzing});',scope);
(async()=>{
 await scope.run();assert.equal(calls,1);
 requested=2;await scope.run();assert.equal(calls,1);
 resolveWork(true);await new Promise(setImmediate);assert.equal(scope.state().done,1);
 await scope.run();assert.equal(calls,2);
 resolveWork(true);await new Promise(setImmediate);assert.equal(scope.state().done,2);
 console.log('Segunda análise não é descartada: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
