/* Whisper may spell the same sound as Arca. Never match inside another word. */
(() => {
 const create=()=>{
  let until=0;
  return {accept(text,now=Date.now()){
   const match=/\b(ar[kc]a)\b/i.exec(text);
   if(match){
    const command=text.slice(match.index+match[0].length).replace(/^[\s,.:;!?-]+/,'').trim();
    until=command?0:now+8000;
    return {accepted:true,text:command,armedUntil:until};
   }
   if(until && now<=until){until=0;return {accepted:true,text:text.trim(),armedUntil:0};}
   until=0;return {accepted:false,text:'',armedUntil:0};
  }};
 };
 if(typeof module!=='undefined')module.exports=create;
 else window.arkaWakeGate=create;
})();
