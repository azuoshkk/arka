(() => {
  const stage = document.getElementById('stage');
  const player = document.getElementById('player');
  const face = crypto.randomUUID();
  const channel = window.BroadcastChannel ? new BroadcastChannel('arka-face-v1') : null;
  let active = null, audioURL = null, generation = 0;
  const state = value => { stage.dataset.state = value; if (value !== 'idle') stopExpression(); };
  const send = type => { if (active) channel?.postMessage({type,id:active,face}); };
  function stop(type = 'ended') {
    generation++;
    send(type); active = null;
    player.pause(); player.removeAttribute('src'); player.load();
    if (audioURL) URL.revokeObjectURL(audioURL);
    audioURL = null; state('idle');
  }
  // Small, bounded performances: all movement stops as soon as speech begins.
  const eyes = stage.querySelector('.eyes');
  const pupils = [...eyes.querySelectorAll('i')];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let animations = [], playTimer, disposed = false, lastTouch = Date.now(), lastTrick = '';
  function stopExpression() {
    animations.forEach(animation => animation.cancel()); animations = [];
  }
  function animate(target, frames, duration, delay = 0) {
    const animation = target.animate(frames, {duration, delay, easing:'ease-in-out', fill:'none'});
    animations.push(animation);
  }
  function look(x, y, duration = 2500) {
    const scale = Math.min(stage.clientWidth, stage.clientHeight) / 350;
    const maxX = Math.max(0, stage.clientWidth / scale / 2 - 102);
    const maxY = Math.max(0, stage.clientHeight / scale / 2 - 60);
    const translation = `${x * maxX}px ${y * maxY}px`;
    animate(eyes, [{translate:'0px 0px',offset:0}, {translate:translation,offset:.22},
      {translate:translation,offset:.72}, {translate:'0px 0px',offset:1}], duration);
  }
  function perform(trick) {
    if (disposed || document.hidden || stage.dataset.state !== 'idle' || reducedMotion.matches) return;
    stopExpression(); lastTrick = trick;
    if (trick === 'peek') {
      look(Math.random() < .5 ? -.92 : .92, Math.random() < .5 ? -.85 : .85);
      animate(pupils[1], [{transform:'scale(1)'},{transform:'scale(.85,1.12)'},{transform:'scale(1)'}],2500);
    } else if (trick === 'scan') {
      look(-.85, -.35, 2200);
      // The second glance begins only after returning to center.
      const scale = Math.min(stage.clientWidth, stage.clientHeight) / 350;
      const x = Math.max(0, stage.clientWidth / scale / 2 - 102) * .85;
      animate(eyes,[{translate:'0px 0px'},{translate:`${x}px -20px`},{translate:`${x}px -20px`},{translate:'0px 0px'}],2200,2200);
    } else if (trick === 'bounce') {
      pupils.forEach((eye, index) => animate(eye, [
        {transform:'translateY(0) scale(1,1)',borderRadius:'45%'},
        {transform:'translateY(12px) scale(1.18,.65)',borderRadius:'50%'},
        {transform:'translateY(-38px) scale(1,.62)',borderRadius:'50%'},
        {transform:'translateY(12px) scale(1.24,.55)',borderRadius:'50%'},
        {transform:'translateY(-22px) scale(1,.66)',borderRadius:'50%'},
        {transform:'translateY(8px) scale(1.14,.78)'},
        {transform:'translateY(0) scale(1,1)',borderRadius:'45%'}],1800,index*180));
    } else if (trick === 'dance') {
      pupils.forEach((eye,index) => animate(eye, [
        {transform:'rotate(0deg) translateY(0)'},
        {transform:`rotate(${index ? -14 : 14}deg) translateY(-18px)`},
        {transform:`rotate(${index ? 14 : -14}deg) translateY(8px)`},
        {transform:`rotate(${index ? -10 : 10}deg) translateY(-12px)`},
        {transform:'rotate(0deg) translateY(0)'}],1900,index*120));
    } else if (trick === 'wink') {
      animate(pupils[Math.random()<.5 ? 0 : 1], [
        {transform:'scaleY(1)'},{transform:'scaleY(.12)'},
        {transform:'scaleY(.12)'},{transform:'scaleY(1)'}],850);
    } else if (trick === 'surprise') {
      pupils.forEach(eye => animate(eye,[{transform:'scale(1)'},
        {transform:'scale(1.2,1.12)'},{transform:'scale(1.2,1.12)'},
        {transform:'scale(1)'}],1400));
    } else if (trick === 'nap') {
      pupils.forEach(eye => animate(eye, [
        {transform:'scaleY(1)',offset:0}, {transform:'scaleY(.09)',offset:.12},
        {transform:'translateY(3px) scaleY(.13)',offset:.4},
        {transform:'scaleY(.09)',offset:.65}, {transform:'scaleY(.09)',offset:.85},
        {transform:'scaleY(1)',offset:1}],7500));
    }
  }
  function schedulePlay() {
    playTimer = setTimeout(() => {
      const choices = ['peek','scan','bounce','dance','wink','surprise'];
      if (Date.now() - lastTouch > 120000) choices.push('nap');
      const options = choices.filter(item => item !== lastTrick);
      perform(options[Math.floor(Math.random()*options.length)]);
      if (!disposed) schedulePlay();
    }, 6500 + Math.random()*5000);
  }
  schedulePlay();
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopExpression(); });
  reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) stopExpression(); });
  document.addEventListener('pointerdown', event => {
    lastTouch = Date.now();
    if (stage.dataset.state !== 'idle' || reducedMotion.matches) return;
    perform(['wink','bounce','surprise'][Math.floor(Math.random()*3)]);
    const rect = stage.getBoundingClientRect();
    look(Math.max(-.85,Math.min(.85,(event.clientX-rect.left)/rect.width*2-1)),
      Math.max(-.85,Math.min(.85,(event.clientY-rect.top)/rect.height*2-1)),1800);
  });
  if (channel) channel.onmessage = async ({data}) => {
    if (!data || typeof data.id !== 'string') return;
    if (data.type === 'probe') {
      channel.postMessage({type:'ready', id:data.id, face}); return;
    }
    if (data.face !== face) return;
    if (data.type === 'stop' && data.id === active) { stop(); return; }
    if (data.type !== 'audio' || !(data.blob instanceof Blob) || !data.blob.type.startsWith('audio/') || data.blob.size > 32*1024*1024) return;
    stop(); active = data.id;
    const version = generation;
    audioURL = URL.createObjectURL(data.blob); player.src = audioURL;
    try {
      await window.arkaSpectrum?.resume();
      if (version !== generation) return;
      await player.play();
      if (version !== generation) return;
    } catch { if (version === generation) stop('unavailable'); }
  };
  player.addEventListener('playing', () => {state('speaking'); send('playing');});
  player.addEventListener('waiting', () => state('idle'));
  player.addEventListener('pause', () => state('idle'));
  player.addEventListener('ended', () => stop());
  player.addEventListener('error', () => stop('unavailable'));
  function resize() {
    stage.style.setProperty('--face-scale', String(Math.min(stage.clientWidth, stage.clientHeight) / 350));
  }
  new ResizeObserver(resize).observe(stage); resize();
  for (const name of ['contextmenu','selectstart','dragstart']) document.addEventListener(name, event => event.preventDefault());
  // A touch unlocks browser audio and fullscreen without any visible controls.
  document.addEventListener('pointerup', () => {
    window.arkaSpectrum?.resume().catch(() => {});
    if (!document.fullscreenElement && document.fullscreenEnabled) document.documentElement.requestFullscreen().catch(() => {});
  });
  window.addEventListener('pagehide', () => { disposed = true; clearTimeout(playTimer); stopExpression(); stop('unavailable'); channel?.close(); });
})();
