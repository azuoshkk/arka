/* Audio handoff only between tabs in the same browser profile and origin. */
(() => {
  if (!window.BroadcastChannel) return;
  const channel = new BroadcastChannel('arka-face-v1');
  let active = null;
  const requests = new Map();
  function request(id, type, message, timeout) {
    return new Promise(resolve => {
      const timer = setTimeout(() => { requests.delete(id); resolve(null); }, timeout);
      requests.set(id, {type, resolve: value => { clearTimeout(timer); requests.delete(id); resolve(value); }});
      channel.postMessage(message);
    });
  }
  channel.onmessage = ({data}) => {
    if (!data || typeof data !== 'object') return;
    const pending = requests.get(data.id);
    if (pending && (data.type === pending.type || data.type === 'unavailable')) pending.resolve(data);
    if (active && data.id === active.id && ['ended','unavailable'].includes(data.type)) active = null;
  };
  function stop() {
    if (!active) return;
    channel.postMessage({type:'stop', ...active});
    active = null;
  }
  window.arkaFaceBridge = {
    stop,
    async play(blob) {
      stop();
      const id = crypto.randomUUID();
      const ready = await request(id, 'ready', {type:'probe',id}, 180);
      if (!ready?.face) return false;
      active = {id, face:ready.face};
      const played = await request(id, 'playing', {type:'audio', ...active, blob}, 1800);
      if (played?.type === 'playing') return true;
      stop(); // Cancel a delayed autoplay attempt before the chat plays its fallback.
      return false;
    }
  };
  window.addEventListener('pagehide', () => {stop(); channel.close();});
})();
