(() => {
  const stage = document.querySelector('#stage');
  const eyes = stage?.querySelector('.eyes');
  if (!eyes) return;
  let timer, wink;
  const wake = () => {
    stage.classList.remove('sleepy');
    clearTimeout(timer);
    if (stage.dataset.state === 'idle') timer = setTimeout(() => {
      if (stage.dataset.state === 'idle') stage.classList.add('sleepy');
    }, 60000);
  };
  for (const event of ['pointerdown', 'keydown', 'input', 'pointermove']) document.addEventListener(event, wake, {passive:true});
  window.addEventListener('focus', wake);
  new MutationObserver(wake).observe(stage, {attributes:true, attributeFilter:['data-state']});
  eyes.tabIndex = 0; eyes.setAttribute('role', 'button'); eyes.setAttribute('aria-label', 'Acordar a Arka e receber uma piscadinha');
  const greet = () => { wake(); if (stage.dataset.state !== 'idle') return;
    stage.classList.add('wink'); clearTimeout(wink); wink = setTimeout(() => stage.classList.remove('wink'), 550);
  };
  eyes.addEventListener('click', greet);
  eyes.addEventListener('keydown', event => {if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); greet(); }});
  wake();
})();
