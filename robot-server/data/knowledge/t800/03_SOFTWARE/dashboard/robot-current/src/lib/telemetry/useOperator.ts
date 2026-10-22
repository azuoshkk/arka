'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { T800Telemetry } from './types';

type Control = { capabilities?: Record<string, {available: boolean; external: string[]}>; enabled: boolean; owner_id?: string | null; owner_name?: string | null };
export function useOperator(camera: string, video: boolean) {
  const socket = useRef<WebSocket | null>(null);
  const client = useRef('');
  const [online, setOnline] = useState(false);
  const [receivedAt, setReceivedAt] = useState(0);
  const [telemetry, setTelemetry] = useState<T800Telemetry | null>(null);
  const [control, setControl] = useState<Control>({ enabled: false });
  const [error, setError] = useState('');
  const [latency, setLatency] = useState<number | null>(null);
  const [images, setImages] = useState<Record<string, {url: string; time: number}>>({});
  const preference = useRef({camera, video});
  preference.current = {camera, video};
  const mine = online && !!client.current && control.owner_id === client.current;
  const mineRef = useRef(false);
  mineRef.current = mine;
  const send = useCallback((action: string, data: Record<string, unknown> = {}) => {
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 16384) return false;
    ws.send(JSON.stringify({action, client_id: client.current, ...data}));
    return true;
  }, []);
  useEffect(() => {
    send('set_active_view', { active_tab: video ? 'overview' : 'watchdog', active_cam: video ? camera : 'none' });
  }, [camera, video, online, send]);
  useEffect(() => {
    client.current = globalThis.crypto?.randomUUID?.() || `client-${Date.now()}-${Math.random()}`;
    let disposed = false, attempts = 0, lastMessage = 0;
    let retry: ReturnType<typeof setTimeout>;
    const urls = new Set<string>();
    const currentImages: Record<string, string> = {};
    const releases = new Set<ReturnType<typeof setTimeout>>();
    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/ws`);
      socket.current = ws;
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => { if (disposed) { ws.close(); return; } attempts = 0; lastMessage = Date.now(); setOnline(true); setError(''); send('ping', {timestamp: Date.now()}); };
      ws.onmessage = event => {
        if (disposed) return;
        lastMessage = Date.now();
        if (event.data instanceof ArrayBuffer) {
          const b = new Uint8Array(event.data);
          if (b.length < 9 || b[0] !== 84 || b[1] !== 56 || b[2] !== 86 || b[3] !== 49) return;
          const key = ['cam0','cam1','gray','overlay'][b[4]];
          if (!key || b[5] > 1) return;
          const url = URL.createObjectURL(new Blob([event.data.slice(8)], {type: b[5] === 1 ? 'image/png' : 'image/jpeg'}));
          urls.add(url);
          const old = currentImages[key]; currentImages[key] = url;
          setImages(prev => ({...prev, [key]: {url, time: Date.now()}}));
          if (old) { const timer = setTimeout(() => { URL.revokeObjectURL(old); urls.delete(old); releases.delete(timer); }, 1000); releases.add(timer); }
          return;
        }
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong') setLatency(Math.max(0, Date.now() - data.client_timestamp));
          else if (data.type === 'control_state') setControl(data);
          else if (data.type === 'command_error' || data.type === 'control_busy') setError(data.error || 'Controle indisponível');
          else if (data.timestamp && data.status) { setTelemetry(prev => ({...prev, ...data})); setReceivedAt(Date.now()); }
        } catch { setError('Resposta inválida do servidor'); }
      };
      ws.onclose = () => {
        if (disposed) return;
        setOnline(false); setControl({enabled:false}); setLatency(null); setImages({});
        retry = setTimeout(connect, Math.min(5000, 1000 * 2 ** attempts++) + Math.random() * 250);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    const heartbeat = setInterval(() => {
      if (socket.current?.readyState !== WebSocket.OPEN) return;
      if (Date.now() - lastMessage > 5000) { socket.current.close(); return; }
      send('ping', {timestamp: Date.now()});
      if (mineRef.current) send('renew_control');
    }, 1000);
    return () => { disposed = true; clearTimeout(retry); clearInterval(heartbeat); releases.forEach(clearTimeout); socket.current?.close(); urls.forEach(URL.revokeObjectURL); };
  }, [send]);
  return { online, receivedAt, telemetry, control, mine, error, latency, images, send, setError };
}
