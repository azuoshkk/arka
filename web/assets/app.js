'use strict';
const $=id=>document.getElementById(id);
const input=$('input'), player=$('player');
let token=sessionStorage.getItem('arka-session'), busy=false, recorder=null, recordingStream=null, recordingTimer=null;
let audioURL=null, currentAudio=null;
const states={idle:'Pronto para conversar',listening:'Estou ouvindo…',thinking:'Pensando na sua pergunta…',speaking:'Falando com você',error:'Vamos tentar de novo'};
function state(value){$('stage').dataset.state=value;$('state-label').textContent=states[value]||value;}
function notice(text){$('notice').textContent=text;$('notice').hidden=!text;}
function controls(value){busy=value;input.disabled=value;$('send').disabled=value;$('new-chat').disabled=value;$('new-chat-mobile').disabled=value;$('mic').disabled=value;document.querySelectorAll('[data-prompt]').forEach(b=>b.disabled=value);}
function scroll(){const el=$('conversation-scroll');el.scrollTop=el.scrollHeight;}
async function api(path,options={}){
 const headers=new Headers(options.headers||{});if(token)headers.set('Authorization','Bearer '+token);
 const response=await fetch(path,{...options,headers,cache:'no-store'});
 if(!response.ok){let data;try{data=await response.json();}catch{data={detail:'Não foi possível acessar o servidor.'};}
 if(response.status===401){sessionStorage.removeItem('arka-session');token=null;}
 if(response.status===401 && path!=='/api/login')showLogin();
 throw new Error(data.detail||'Falha na solicitação.');}return response;
}
async function session(){if(!token){const response=await api('/api/sessions',{method:'POST'});token=(await response.json()).token;sessionStorage.setItem('arka-session',token);}}
function message(role,text=''){
 $('welcome').hidden=true;document.querySelector('.app').classList.add('in-conversation');
 const el=document.createElement('article');el.className='message '+role;
 const label=document.createElement('div');label.className='message-label';label.textContent=role==='user'?'Você':'Arka';
 const content=document.createElement('div');content.className='content';content.textContent=text;el.append(label,content);$('messages').append(el);scroll();return {el,content};
}
function finishMessage(target,entry){
 target.content.textContent=entry.text;
 if(entry.sources?.length){const details=document.createElement('details');details.className='sources';const summary=document.createElement('summary');summary.textContent='FONTES CONSULTADAS · '+entry.sources.length;const list=document.createElement('ol');
 for(const source of entry.sources){const item=document.createElement('li');item.value=source.number;item.textContent=source.source+(source.page?' · página '+source.page:'');list.append(item);}details.append(summary,list);target.el.append(details);}
 const replay=document.createElement('button');replay.className='replay';replay.textContent='Ouvir resposta';replay.addEventListener('click',async()=>{if(busy)return;controls(true);try{await speak(entry.id);}catch(error){notice(error.message);state('error');}finally{controls(false);}});target.el.append(replay);
}
function stopAudio(){window.arkaFaceBridge?.stop();player.pause();if(audioURL){URL.revokeObjectURL(audioURL);audioURL=null;}player.removeAttribute('src');player.hidden=true;currentAudio=null;}
async function speak(messageId){
 stopAudio();state('thinking');
 const response=await api('/api/tts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:messageId})});
 const blob=await response.blob();
 if(await window.arkaFaceBridge?.play(blob)){state('idle');return;}
 audioURL=URL.createObjectURL(blob);player.src=audioURL;currentAudio=messageId;
 try{await window.arkaSpectrum?.resume();await player.play();state('speaking');}
 catch{player.hidden=false;state('idle');notice('Áudio pronto. Toque em reproduzir para ouvir.');}
}
player.addEventListener('play',()=>state('speaking'));player.addEventListener('ended',()=>{state('idle');player.hidden=true;});player.addEventListener('pause',()=>{if(!busy)state('idle');});
async function exchange(path,options,userText){
 if(busy)return;controls(true);notice('');stopAudio();state(path==='/api/audio'?'listening':'thinking');let target=null,entry=null,completed=false;
 try{
  await session();if(userText){message('user',userText);$('session-title').textContent=userText;}
  let text=userText;
  if(path==='/api/audio'){
    const transcription=await (await api('/api/transcribe',options)).json();text=transcription.text;
    message('user',text);$('session-title').textContent=text;state('thinking');
  }
  const reader=await websocketReader(text,false),decoder=new TextDecoder();let buffer='';
  while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});let end;
   while((end=buffer.indexOf('\n\n'))!==-1){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);let event='',payload='';for(const line of frame.split('\n')){if(line.startsWith('event: '))event=line.slice(7);if(line.startsWith('data: '))payload+=line.slice(6);}
    if(!payload)continue;const data=JSON.parse(payload);
    if(event==='state')state(data.state);
    if(event==='route'){$('route').textContent=data.route;$('route').classList.toggle('expert',data.route==='EXPERT');}
    if(event==='transcription'){message('user',data.text);$('session-title').textContent=data.text;}
    if(event==='token'){if(!target)target=message('assistant');target.content.textContent+=data.text;scroll();}
    if(event==='answer'){entry=data;if(!target)target=message('assistant');finishMessage(target,entry);}
    if(event==='error')throw new Error(data.detail);
    if(event==='done')completed=true;
   }
   if(done)break;
  }
  if(!completed||!entry)throw new Error('A conexão foi interrompida. Tente novamente.');
  await speak(entry.id);
 }catch(error){notice(error.message);state('error');}
 finally{controls(false);input.focus();scroll();}
}
function submit(text){text=text.trim();if(!text||busy)return;input.value='';input.style.height='';exchange('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})},text);}
$('composer').addEventListener('submit',event=>{event.preventDefault();submit(input.value);});
input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();submit(input.value);}});
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,130)+'px';});
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>submit(button.dataset.prompt)));
async function newChat(){if(busy)return;try{await session();await api('/api/history',{method:'DELETE'});stopAudio();$('messages').replaceChildren();$('welcome').hidden=false;document.querySelector('.app').classList.remove('in-conversation');$('session-title').textContent='Conversa atual';$('route').textContent='CHAT';$('route').classList.remove('expert');notice('');state('idle');}catch(error){notice(error.message);}}
$('new-chat').addEventListener('click',newChat);$('new-chat-mobile').addEventListener('click',newChat);
function releaseMic(){clearTimeout(recordingTimer);recordingStream?.getTracks().forEach(track=>track.stop());recordingStream=null;$('mic').classList.remove('recording');$('mic').setAttribute('aria-label','Gravar mensagem');$('input-hint').textContent='Enter para enviar · Shift + Enter para nova linha';}
$('mic').addEventListener('click',async()=>{
 if(recorder?.state==='recording'){recorder.stop();return;}if(busy)return;
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){notice('O microfone precisa de HTTPS com o certificado local confiável. Abra a URL HTTPS e confie na autoridade local conforme o README.');return;}
 if(!window.MediaRecorder){notice('Este navegador não oferece gravação de áudio. Use um navegador atualizado.');return;}
 try{
  stopAudio();notice('');controls(true);recordingStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
  recorder=new MediaRecorder(recordingStream,mime?{mimeType:mime}:{});const chunks=[];let bytes=0,oversize=false;
  recorder.ondataavailable=event=>{if(event.data.size){bytes+=event.data.size;if(bytes>12*1024*1024){oversize=true;recorder.stop();}else chunks.push(event.data);}};
  recorder.onstop=()=>{const type=recorder.mimeType;releaseMic();controls(false);if(oversize){notice('Gravação excedeu 12 MB. Grave uma mensagem mais curta.');state('error');return;}const blob=new Blob(chunks,{type});exchange('/api/audio',{method:'POST',headers:{'Content-Type':type||'application/octet-stream'},body:blob});};
  recorder.onerror=()=>{releaseMic();controls(false);notice('Não foi possível gravar o áudio.');state('error');};
  recorder.start(1000);$('mic').disabled=false;$('mic').classList.add('recording');$('mic').setAttribute('aria-label','Parar gravação e enviar');$('input-hint').textContent='Gravando · toque no microfone para enviar · máximo 60 s';state('listening');recordingTimer=setTimeout(()=>{if(recorder?.state==='recording')recorder.stop();},59000);
 }catch(error){releaseMic();controls(false);notice(error.name==='NotAllowedError'?'Permita o microfone nas configurações deste navegador.':'Não foi possível acessar o microfone deste dispositivo.');state('error');}
});
window.addEventListener('pagehide',()=>{releaseMic();stopAudio();});
async function init(){try{const access=await (await api('/api/access')).json();updateAccess(access);if(access.login_required&&!access.authenticated){showLogin();return;}await session();let response;try{response=await api('/api/history');}catch(error){if(token)throw error;await session();response=await api('/api/history');}const data=await response.json();for(const item of data.messages){const target=message(item.role,item.content);if(item.role==='assistant'){const entry=data.answers.find(answer=>answer.text===item.content);if(entry)finishMessage(target,entry);}}const status=await (await api('/api/state')).json();if(status.stt==='unavailable')notice('O reconhecimento de voz aguarda Whisper na GPU do servidor. Você pode conversar por texto.');}catch(error){notice(error.message);state('error');}}



function showLogin(){if(!$('login-dialog').open)$('login-dialog').showModal();}
function updateAccess(info){$('teach-open').hidden=info.role!=='admin';$('logout').hidden=!info.authenticated;}
$('login-dialog').addEventListener('cancel',event=>event.preventDefault());
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault();$('login-submit').disabled=true;$('login-error').textContent='';
 try{const data=await (await api('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('login-user').value.trim(),password:$('login-password').value})})).json();token=data.token;sessionStorage.setItem('arka-session',token);$('login-password').value='';$('login-dialog').close();notice('');$('messages').replaceChildren();await init();}
 catch(error){$('login-error').textContent=error.message;}finally{$('login-submit').disabled=false;}
});
$('logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});stopAudio();token=null;sessionStorage.removeItem('arka-session');$('messages').replaceChildren();$('welcome').hidden=false;document.querySelector('.app').classList.remove('in-conversation');updateAccess({});showLogin();}catch(error){notice(error.message);}});
function websocketReader(text,knowledge){
 return new Promise((resolve,reject)=>{
  const socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/chat/ws');
  const queue=[];let waiting=null,closed=false,failure=null,opened=false;
  function wake(){if(waiting){const callback=waiting;waiting=null;callback();}}
  socket.onopen=()=>{opened=true;socket.send(JSON.stringify({token,text,knowledge}));resolve({read:async()=>{
    while(!queue.length&&!closed)await new Promise(r=>waiting=r);
    if(failure)throw failure;
    return queue.length?{value:new TextEncoder().encode(queue.shift()),done:false}:{done:true};
  }});};
  socket.onmessage=event=>{if(event.data.startsWith('{')){const data=JSON.parse(event.data);if(data.error){failure=new Error(data.error);socket.close();}}else queue.push(event.data);wake();};
  socket.onerror=()=>{failure=new Error('Não foi possível conectar à Arka.');if(!opened)reject(failure);wake();};
  socket.onclose=()=>{closed=true;if(!opened)reject(new Error('Conexão recusada. Entre novamente.'));wake();};
 });
}
init();

/* aprendizado contínuo */
(() => {
  const notice = document.getElementById('learning-notice');
  const close = document.getElementById('learning-notice-close');

  if (!notice || !close) return;

  if (sessionStorage.getItem('arka-learning-notice') === 'hidden') {
    notice.hidden = true;
  }

  close.addEventListener('click', () => {
    notice.hidden = true;
    sessionStorage.setItem('arka-learning-notice', 'hidden');
  });
})();

/* ===== PDF DIRECT UPLOAD ===== */

(() => {
  const attach = document.getElementById('attach');
  const fileInput = document.getElementById('pdf-attach');

  if (!attach || !fileInput) return;

  attach.addEventListener('click', () => {
    fileInput.click();
  });

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;

    if (
      file.type !== 'application/pdf' &&
      !file.name.toLowerCase().endsWith('.pdf')
    ) {
      notice('Envie apenas arquivos PDF.');
      fileInput.value = '';
      return;
    }

    if (file.size > 12 * 1024 * 1024) {
      notice('Use um PDF de até 12 MB.');
      fileInput.value = '';
      return;
    }

    try {
      controls(true);
      state('thinking');

      notice(`Lendo e indexando ${file.name}...`);

      const response = await api('/api/upload/pdf', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/pdf',
          'X-Filename': encodeURIComponent(file.name),
        },
        body: file,
      });

      const data = await response.json();

      notice(
        `✅ ${file.name} foi aprendido e já está disponível no RAG.`
      );

      state('idle');

    } catch (error) {
      notice(error.message || 'Falha ao indexar PDF.');
      state('error');

    } finally {
      controls(false);
      fileInput.value = '';
    }
  });
})();
