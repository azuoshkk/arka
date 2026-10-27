(() => {
 const clean=t=>t.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 const intent=text=>/\b(olhe|olha|analise|analisa|analisar|enxerga|enxergando|camera|vendo)\b|o que (voce )?ve\b|na (sua|minha) frente|descreva (a cena|o ambiente|a imagem)|que objeto|o que (e |eh )?(isso|isto|aquilo)|que (e |eh )?(esse|essa)|identifi(que|car)|na minha mao/.test(clean(text));
 intent.target=(text,objects)=>{
  if(!/\b(isso|isto|esse|essa|objeto)\b|minha mao/.test(clean(text)))return null;
  // Only crop a non-person object actually covering the center reticle.
  const candidates=objects.filter(o=>o.label!=='pessoa' && o.confidence>=.5 && o.box[0]<=.5 && o.box[2]>=.5 && o.box[1]<=.5 && o.box[3]>=.5);
  candidates.sort((a,b)=>(a.box[2]-a.box[0])*(a.box[3]-a.box[1])-(b.box[2]-b.box[0])*(b.box[3]-b.box[1]));
  return candidates[0]||null;
 };
 if(typeof module!=='undefined')module.exports=intent;else window.arkaVisionIntent=intent;
})();
