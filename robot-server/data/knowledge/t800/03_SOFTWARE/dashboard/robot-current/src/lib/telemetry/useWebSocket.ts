'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  T800Telemetry,
  ConnectionStatus,
  NetworkDiagnostics,
  Map3DPointCloud,
  Map3DPose,
  Map3DTrajectory,
  Map3DStatus,
  ScanItem,
  ScanRecordingStatus,
  StorageInfo
} from './types';
import { quaternionToEuler, accelToEuler } from '../math/imuMath';
import { playSystemChime } from '../audio/soundEffects';

export interface UseTelemetryReturn {
  telemetry: T800Telemetry | null;
  connectionStatus: ConnectionStatus;
  diagnostics: NetworkDiagnostics;
  isSimulated: boolean;
  baseUrl: string;
  setBaseUrl: (newUrl: string) => void;
  cameraQualityMode: 'auto' | 'low' | 'high';
  setCameraQualityMode: (mode: 'auto' | 'low' | 'high') => void;
  sendSpeech: (text: string, voice?: string, speed?: string | number) => boolean;
  sendNeckMove: (pitch: number, yaw: number, duration?: number) => boolean;
  sendNeckStep: (dPitch: number, dYaw: number, duration?: number) => boolean;
  sendNeckCenter: (duration?: number) => boolean;
  sendNeckBalanceMode: (enable?: boolean) => boolean;
  startBagRecording: (filename?: string) => boolean;
  stopBagRecording: () => boolean;
  sendLedControl: (color: number) => boolean;
  // Mapeamento 3D (Foxglove Style)
  map3DPointCloud: Map3DPointCloud;
  map3DPose: Map3DPose | null;
  map3DTrajectory: Map3DTrajectory;
  map3DStatus: Map3DStatus | null;
  clear3DMap: () => boolean;
  pause3DMap: (paused?: boolean) => boolean;
  set3DMapConfig: (config: { voxel_size?: number; max_range?: number; max_points?: number }) => boolean;
  setLidarEnabled: (enabled: boolean) => boolean;
  controlState: { enabled: boolean; owner_id?: string | null; owner_name?: string | null; busy?: boolean };
  acquireControl: () => boolean;
  releaseControl: () => boolean;
  // Fase 2: Gravação Onboard e Gerenciamento de Scans 3D
  scanList: import('./types').ScanItem[];
  scanStatus: import('./types').ScanRecordingStatus | null;
  storageInfo: import('./types').StorageInfo | null;
  startScan: (profile?: string, name?: string) => boolean;
  stopScan: () => boolean;
  refreshScans: () => boolean;
  deleteScan: (scanId: string) => boolean;
  viewScan: (scanId: string) => boolean;
  refreshStorage: () => boolean;
  setRenderLatency: (renderMs: number) => void;
}

function gatewayUrl() {
  if (typeof window === 'undefined') return '';
  if (process.env.NEXT_PUBLIC_T800_WS_URL) return process.env.NEXT_PUBLIC_T800_WS_URL;
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/ws`;
}

const DEFAULT_DIAGNOSTICS: NetworkDiagnostics = {
  latencyMs: null,
  packetRateHz: 0,
  bandwidthKbps: 0,
  totalPackets: 0,
  lastPacketTime: null,
  reconnectAttempts: 0
};

export function useWebSocketTelemetry(
  activeTab: string,
  activeCam: string,
  initialUrl?: string
): UseTelemetryReturn {
  const [baseUrl, setBaseUrlState] = useState<string>('');
  useEffect(() => { setBaseUrlState(gatewayUrl()); }, []);

  const [telemetry, setTelemetry] = useState<T800Telemetry | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('DISCONNECTED');
  const [diagnostics, setDiagnostics] = useState<NetworkDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [cameraQualityMode, setCameraQualityMode] = useState<'auto' | 'low' | 'high'>('auto');
  const clientIdRef = useRef<string>(`dash-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`);
  const [controlState, setControlState] = useState<{ enabled: boolean; owner_id?: string | null; owner_name?: string | null; busy?: boolean }>({ enabled: false });

  // Estados de Mapeamento 3D (Foxglove Style)
  const [map3DPointCloud, setMap3DPointCloud] = useState<Map3DPointCloud>({
    frame_id: 'map',
    points: [],
    point_count: 0
  });
  const [map3DPose, setMap3DPose] = useState<Map3DPose | null>(null);
  const [map3DTrajectory, setMap3DTrajectory] = useState<Map3DTrajectory>({
    frame_id: 'map',
    points: [],
    count: 0
  });
  const [map3DStatus, setMap3DStatus] = useState<Map3DStatus | null>({
    state: 'ACTIVE',
    active_frame: 'map',
    fps: 0,
    total_points: 0
  });

  // Fase 2: Estados de Gravação Local e Armazenamento Onboard
  const [scanList, setScanList] = useState<ScanItem[]>([]);
  const [scanStatus, setScanStatus] = useState<ScanRecordingStatus | null>(null);
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null);
  const frontendRenderMsRef = useRef<number>(0);
  const totalPacketsRef = useRef<number>(0);
  const lastPacketTimeRef = useRef<number | null>(null);

  // Sincroniza a qualidade da câmera com o robô de forma dinâmica
  useEffect(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    let width = 640;
    let quality = 50;
    
    if (cameraQualityMode === 'low') {
      width = 480;
      quality = 40;
    } else if (cameraQualityMode === 'high') {
      width = 1000;
      quality = 70;
    } else {
      // Modo Auto: decai para qualidade baixa se a conexão estiver degradada ou latência > 150ms
      const isConnectionDegraded = connectionStatus === 'DEGRADED' || (diagnostics.latencyMs !== null && diagnostics.latencyMs > 150);
      if (isConnectionDegraded) {
        width = 480;
        quality = 40;
      } else {
        width = 640;
        quality = 55;
      }
    }
    
    try {
      wsRef.current.send(JSON.stringify({
        action: 'set_camera_config',
        target_width: width,
        jpeg_quality: quality
      }));
    } catch (e) {
      console.error('Falha ao enviar configuração de câmera:', e);
    }
  }, [cameraQualityMode, connectionStatus, diagnostics.latencyMs, baseUrl]);

  const imageUrlsRef = useRef<Record<string, string>>({});
  const lastCameraUiUpdateRef = useRef<number>(0);
  const imageRevokeTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const liveImageUrlsRef = useRef<Set<string>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef<number>(0);
  const byteCountRef = useRef<number>(0);
  const lastMetricsTimeRef = useRef<number>(Date.now());
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayMs = useRef<number>(1000); // Start with 1s
  const wasConnectedRef = useRef<boolean>(false);

  // Sincroniza a aba e câmera ativas com o robô em tempo real (para economia de CPU/Rede de bordo)
  useEffect(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    try {
      wsRef.current.send(JSON.stringify({
        action: 'set_active_view',
        active_tab: activeTab,
        active_cam: activeCam
      }));
    } catch (e) {
      console.error('Falha ao enviar comando de visualização ativa:', e);
    }
  }, [activeTab, activeCam, connectionStatus, baseUrl]);

  const setBaseUrl = useCallback((_newUrl: string) => {
    setBaseUrlState(gatewayUrl());
  }, []);

  useEffect(() => {
    const ticker = setInterval(() => {
      const now = Date.now();
      const deltaSec = (now - lastMetricsTimeRef.current) / 1000;
      if (deltaSec > 0) {
        const hz = Math.round((frameCountRef.current / deltaSec) * 10) / 10;
        const kbps = Math.round((byteCountRef.current / deltaSec / 1024) * 10) / 10;

        setDiagnostics((prev) => ({
          ...prev,
          packetRateHz: hz,
          bandwidthKbps: kbps,
          totalPackets: totalPacketsRef.current,
          lastPacketTime: lastPacketTimeRef.current,
        }));

        frameCountRef.current = 0;
        byteCountRef.current = 0;
        lastMetricsTimeRef.current = now;
      }
    }, 1000);

    return () => clearInterval(ticker);
  }, []);

  useEffect(() => {
    if (!baseUrl) return;
    let active = true;
    let wsUrl = baseUrl;

    const connect = () => {
      if (!active) return;
      if (wsRef.current) {
        wsRef.current.close();
      }

      setConnectionStatus('WAITING');
      
      wsUrl = baseUrl;
      if (baseUrl.startsWith('http')) {
        wsUrl = baseUrl.replace(/^http/, 'ws');
      }
      
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      let pingInterval: NodeJS.Timeout | null = null;

      ws.onopen = () => {
        if (!active) return;
        setConnectionStatus('CONNECTED');
        setDiagnostics(prev => ({ ...prev, reconnectAttempts: 0 }));
        reconnectDelayMs.current = 1000; // Reset backoff

        // Toca sinal sonoro suave de conexão
        playSystemChime('connect');
        wasConnectedRef.current = true;

        // Solicita snapshot inicial do mapa e lista de gravações
        try {
          ws.send(JSON.stringify({ action: 'map_3d/request_snapshot' }));
          ws.send(JSON.stringify({ action: 'map_3d/scan/list' }));
          ws.send(JSON.stringify({ action: 'map_3d/storage/info' }));
        } catch {
          // ignore
        }

        // Envia primeiro ping imediatamente
        try {
          ws.send(JSON.stringify({
            action: 'ping',
            timestamp: Date.now()
          }));
        } catch {
          // ignore
        }

        // Loop de ping a cada 1.5s para medição contínua de latência RTT
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({
                action: 'ping',
                timestamp: Date.now()
              }));
            } catch {
              // ignore
            }
          }
        }, 1500);
      };

      ws.onmessage = (event) => {
        if (!active) return;
        
        const now = Date.now();
        frameCountRef.current += 1;
        totalPacketsRef.current += 1;
        lastPacketTimeRef.current = now;
        
        // Calculate bytes received
        const size = typeof event.data === 'string' ? event.data.length : (event.data.byteLength || 0);
        byteCountRef.current += size;

        // 1. Processamento de Frame Binário de Alto Desempenho (Zero-Copy)
        if (event.data instanceof ArrayBuffer) {
          const buffer = event.data;
          const bytes = new Uint8Array(buffer);
          if (buffer.byteLength > 8 && bytes[0] === 84 && bytes[1] === 56 && bytes[2] === 86 && bytes[3] === 49) {
            const camera = ['cam0', 'cam1', 'gray', 'overlay'][bytes[4]];
            if (!camera || bytes[5] > 1) return;
            const url = URL.createObjectURL(new Blob([buffer.slice(8)], {type: bytes[5] === 1 ? 'image/png' : 'image/jpeg'}));
            liveImageUrlsRef.current.add(url);
            const previous = imageUrlsRef.current[camera];
            imageUrlsRef.current[camera] = url;
            if (now - lastCameraUiUpdateRef.current >= 66) {
              lastCameraUiUpdateRef.current = now;
              setTelemetry(prev => prev ? {...prev, cameras: {...prev.cameras, [camera]: imageUrlsRef.current[camera]}} : prev);
            }
            if (previous) {
              const timer = setTimeout(() => {
                URL.revokeObjectURL(previous);
                liveImageUrlsRef.current.delete(previous);
                imageRevokeTimersRef.current.delete(timer);
              }, 1000);
              imageRevokeTimersRef.current.add(timer);
            }
            return;
          }
          if (buffer.byteLength >= 36) {
            const dataView = new DataView(buffer);
            const magic = dataView.getUint8(0);
            if (magic === 0x3d) { // 0x3D = 61 ('=')
              const pointCount = dataView.getUint32(4, true);
              const scanId = dataView.getUint32(8, true);
              const t0Sensor = dataView.getFloat64(12, true);
              const t2Backend = dataView.getFloat64(20, true);
              const zMin = dataView.getFloat32(28, true);
              const zMax = dataView.getFloat32(32, true);

              // View direta TypedArray sem cópia de memória
              const pointsFloat = new Float32Array(buffer, 36, pointCount * 3);

              const t3Browser = Date.now() / 1000;
              const wsLatencyMs = Math.max(0, Math.round((t3Browser - t2Backend) * 1000));
              const sensorToBackendMs = Math.max(0, Math.round((t2Backend - t0Sensor) * 1000));

              setMap3DPointCloud({
                type: 'map_3d/pointcloud',
                frame_id: 'map',
                points: pointsFloat,
                point_count: pointCount,
                min_z: zMin,
                max_z: zMax,
                t0_sensor: t0Sensor,
                t2_backend: t2Backend,
                is_binary: true
              });

              setMap3DStatus(prev => {
                const prevLat = prev?.latency || { backend_processing_ms: 0, frontend_render_ms: 0 };
                const totalMs = sensorToBackendMs + (prevLat.backend_processing_ms || 0) + wsLatencyMs + (frontendRenderMsRef.current || 0);
                return {
                  ...(prev || {
                    state: 'ACTIVE',
                    active_frame: 'map',
                    fps: 0,
                    total_points: pointCount,
                  }),
                  total_points: pointCount,
                  min_z: zMin,
                  max_z: zMax,
                  latency: {
                    ...prevLat,
                    sensor_to_backend_ms: sensorToBackendMs,
                    websocket_latency_ms: wsLatencyMs,
                    frontend_render_ms: Math.round(frontendRenderMsRef.current),
                    total_latency_ms: totalMs
                  }
                };
              });
              return;
            }
          }
        }

        try {
          const rawData = JSON.parse(event.data);
          if (rawData.type === 'command_error') return;
          if (rawData.type === 'control_state' || rawData.type === 'control_busy') {
            setControlState({
              enabled: !!rawData.enabled,
              owner_id: rawData.owner_id || null,
              owner_name: rawData.owner_name || null,
              busy: rawData.type === 'control_busy' || !!rawData.busy
            });
            return;
          }

          // 1. Resposta de Ping (Pong) -> Calcula latência real (RTT)
          if (rawData && rawData.type === 'pong' && rawData.client_timestamp) {
            const rtt = Math.max(1, Math.round(now - rawData.client_timestamp));
            setDiagnostics(prev => ({
              ...prev,
              latencyMs: prev.latencyMs !== null ? Math.round(prev.latencyMs * 0.6 + rtt * 0.4) : rtt,
            }));
            return;
          }

          // 2. Intercepta Mensagens de Mapeamento 3D (Foxglove Style)
          if (rawData && typeof rawData.type === 'string' && rawData.type.startsWith('map_3d/')) {
            if (rawData.type === 'map_3d/pointcloud') {
              setMap3DPointCloud(rawData);
            } else if (rawData.type === 'map_3d/pose') {
              setMap3DPose(rawData);
            } else if (rawData.type === 'map_3d/trajectory') {
              setMap3DTrajectory(rawData);
            } else if (rawData.type === 'map_3d/lidar_status') {
              setMap3DStatus(prev => prev ? { ...prev, lidar_enabled: !!rawData.enabled } : null);
            } else if (rawData.type === 'map_3d/status') {
              setMap3DStatus(prev => ({
                ...prev,
                ...rawData,
                latency: {
                  ...(prev?.latency || {}),
                  ...(rawData.latency || {}),
                  frontend_render_ms: Math.round(frontendRenderMsRef.current)
                }
              }));
              if (rawData.recorder) setScanStatus(rawData.recorder);
              if (rawData.storage) setStorageInfo(rawData.storage);
            } else if (rawData.type === 'map_3d/scan/list') {
              setScanList(rawData.scans || []);
            } else if (rawData.type === 'map_3d/scan/status') {
              setScanStatus(rawData);
            } else if (rawData.type === 'map_3d/storage/info') {
              setStorageInfo(rawData.storage || rawData);
            } else if (rawData.type === 'map_3d/scan/delete_response') {
              if (rawData.scans) setScanList(rawData.scans);
            }
            return;
          }

          // Fallback de latência baseado no timestamp do servidor se ainda não houver pong
          if (rawData.timestamp && typeof rawData.timestamp === 'number') {
            const transitMs = Math.round(now - rawData.timestamp * 1000);
            if (transitMs >= 0 && transitMs < 1000) {
              setDiagnostics(prev => ({
                ...prev,
                latencyMs: prev.latencyMs ?? transitMs,
              }));
            }
          }

          // Normalize fields from local T800 telemetry format
          const power = rawData.power || (rawData.battery ? {
            battery_pct: rawData.battery.percentage,
            voltage: rawData.battery.voltage,
            current: rawData.battery.current,
          } : undefined);

          let imu = rawData.imu;
          let quaternion = rawData.quaternion || imu?.orientation;

          // Se a odometria tiver orientação válida, usa como fallback
          const odomQuat = rawData.odometry?.standard?.orientation || rawData.odometry?.high_freq?.orientation;
          if (!quaternion && odomQuat && (odomQuat.x || odomQuat.y || odomQuat.z || odomQuat.w)) {
            quaternion = odomQuat;
          }

          let roll = imu?.roll ?? null;
          let pitch = imu?.pitch ?? null;
          let yaw = imu?.yaw ?? null;

          // Se tiver quaternion válido, calcula Euler exato
          if (quaternion && (quaternion.x !== 0 || quaternion.y !== 0 || quaternion.z !== 0 || quaternion.w !== 0)) {
            const euler = quaternionToEuler(quaternion);
            if (euler.roll !== null && (roll === null || roll === 0)) roll = euler.roll;
            if (euler.pitch !== null && (pitch === null || pitch === 0)) pitch = euler.pitch;
            if (euler.yaw !== null && (yaw === null || yaw === 0)) yaw = euler.yaw;
          }

          // Se roll e pitch estiverem em radianos (ex: magnitude <= PI e não nulos), converte para graus
          if (roll !== null && Math.abs(roll) <= Math.PI && pitch !== null && Math.abs(pitch) <= Math.PI && (roll !== 0 || pitch !== 0)) {
            roll = roll * (180 / Math.PI);
            pitch = pitch * (180 / Math.PI);
            if (yaw !== null && Math.abs(yaw) <= Math.PI && yaw !== 0) {
              yaw = yaw * (180 / Math.PI);
            }
          }

          // Se roll/pitch ainda forem nulos ou zerados, tenta Software AHRS via aceleração linear (gravidade)
          if ((roll === null || (roll === 0 && pitch === 0)) && imu?.linear_acceleration) {
            const accelEuler = accelToEuler(
              imu.linear_acceleration.x,
              imu.linear_acceleration.y,
              imu.linear_acceleration.z
            );
            if (accelEuler.roll !== null) roll = accelEuler.roll;
            if (accelEuler.pitch !== null) pitch = accelEuler.pitch;
          }

          const normalizedImu = {
            ...(imu || {}),
            roll: roll !== null ? Math.round(roll * 10) / 10 : 0.0,
            pitch: pitch !== null ? Math.round(pitch * 10) / 10 : 0.0,
            yaw: yaw !== null ? Math.round((yaw || 0) * 10) / 10 : 0.0,
            orientation: quaternion || imu?.orientation
          };

          const data: T800Telemetry = {
            ...rawData,
            power,
            imu: normalizedImu,
            quaternion: quaternion || rawData.quaternion,
          };

          setTelemetry(prev => {
            if (!prev) return data;
            return {
              ...prev,
              ...data,
              power: data.power ?? prev.power,
              battery: data.battery ?? prev.battery,
              joints: data.joints ?? prev.joints,
              gamepad: data.gamepad ?? prev.gamepad,
              bag_recorder: data.bag_recorder ?? prev.bag_recorder,
              imu_torso: data.imu_torso ?? prev.imu_torso,
              imu_head: data.imu_head ?? prev.imu_head,
              cloud_mode: data.cloud_mode ?? prev.cloud_mode,
              motion_state: data.motion_state ?? prev.motion_state,
              motion_plan: data.motion_plan ?? prev.motion_plan,
              motors_debug: data.motors_debug ?? prev.motors_debug,
              heartbeats: data.heartbeats ? { ...prev.heartbeats, ...data.heartbeats } : prev.heartbeats,
              cameras: data.cameras
                ? {
                    ...(prev.cameras || {}),
                    ...(data.cameras.cam0 ? { cam0: data.cameras.cam0 } : {}),
                    ...(data.cameras.cam1 ? { cam1: data.cameras.cam1 } : {}),
                    ...(data.cameras.gray ? { gray: data.cameras.gray } : {}),
                    ...(data.cameras.overlay ? { overlay: data.cameras.overlay } : {}),
                  }
                : prev.cameras,
              camera_info: data.camera_info ? { ...prev.camera_info, ...data.camera_info } : prev.camera_info,
              cloud_points: data.cloud_points || prev.cloud_points,
            };
          });
        } catch (e) {
          console.error('Failed to parse T800 JSON payload:', e);
        }
      };

      ws.onclose = () => {
        if (pingInterval) clearInterval(pingInterval);
        if (!active) return;
        setConnectionStatus('DISCONNECTED');
        setDiagnostics(prev => ({ ...prev, reconnectAttempts: prev.reconnectAttempts + 1 }));

        // Toca sinal sonoro apenas se estava conectado anteriormente
        if (wasConnectedRef.current) {
          playSystemChime('disconnect');
          wasConnectedRef.current = false;
        }
        
        // Exponential backoff up to max 5s + random jitter for smoother reconnects
        const jitter = Math.random() * 500;
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectDelayMs.current = Math.min(reconnectDelayMs.current * 2, 5000);
          connect();
        }, reconnectDelayMs.current + jitter);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
      };
    };

    connect();

    return () => {
      active = false;
      imageRevokeTimersRef.current.forEach(clearTimeout);
      imageRevokeTimersRef.current.clear();
      liveImageUrlsRef.current.forEach(url => URL.revokeObjectURL(url));
      liveImageUrlsRef.current.clear();
      imageUrlsRef.current = {};
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
          wsRef.current.close();
        }
      }
    };
  }, [baseUrl]);

  const sendJson = useCallback((payload: Record<string, unknown>) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
    try {
      wsRef.current.send(JSON.stringify({ ...payload, client_id: clientIdRef.current }));
      return true;
    } catch {
      return false;
    }
  }, []);

  const acquireControl = useCallback(() => sendJson({ action: 'acquire_control', name: 'dashboard' }), [sendJson]);
  const releaseControl = useCallback(() => sendJson({ action: 'release_control' }), [sendJson]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (controlState.owner_id === clientIdRef.current) {
        sendJson({ action: 'renew_control' });
      }
    }, 5000);
    return () => clearInterval(timer);
  }, [controlState.owner_id, sendJson]);

  const sendSpeech = useCallback((text: string, voice?: string, speed?: string | number) => sendJson({ action: 'speak', text, voice, speed }), [sendJson]);
  const sendNeckMove = useCallback((pitch: number, yaw: number, duration?: number) => sendJson({ action: 'neck_move', pitch, yaw, duration }), [sendJson]);
  const sendNeckStep = useCallback((dPitch: number, dYaw: number, duration?: number) => sendJson({ action: 'neck_step', d_pitch: dPitch, d_yaw: dYaw, duration }), [sendJson]);
  const sendNeckCenter = useCallback((duration?: number) => sendJson({ action: 'neck_center', duration }), [sendJson]);
  const sendNeckBalanceMode = useCallback((enable?: boolean) => sendJson({ action: 'neck_balance', enable }), [sendJson]);

  return {
    telemetry,
    connectionStatus,
    diagnostics,
    isSimulated: false,
    baseUrl,
    setBaseUrl,
    cameraQualityMode,
    setCameraQualityMode,
    sendSpeech,
    sendNeckMove,
    sendNeckStep,
    sendNeckCenter,
    sendNeckBalanceMode,
    startBagRecording: useCallback((filename?: string) => sendJson({ action: 'start_bag_recording', filename }), [sendJson]),
    stopBagRecording: useCallback(() => sendJson({ action: 'stop_bag_recording' }), [sendJson]),
    sendLedControl: useCallback((color: number) => sendJson({ action: 'set_led', color }), [sendJson]),

    // Mapeamento 3D (Foxglove Style)
    map3DPointCloud,
    map3DPose,
    map3DTrajectory,
    map3DStatus,
    clear3DMap: useCallback(() => {
      setMap3DPointCloud(prev => ({ ...prev, points: [], point_count: 0 }));
      setMap3DTrajectory(prev => ({ ...prev, points: [], count: 0 }));
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try { wsRef.current.send(JSON.stringify({ action: 'map_3d/clear' })); } catch {}
      }
      return true;
    }, []),
    pause3DMap: useCallback((paused?: boolean) => {
      setMap3DStatus(prev => prev ? { ...prev, state: paused === false ? 'ACTIVE' : 'PAUSED' } : null);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try { wsRef.current.send(JSON.stringify({ action: 'map_3d/pause', paused })); } catch {}
      }
      return true;
    }, []),
    set3DMapConfig: useCallback((config: { voxel_size?: number; max_range?: number; max_points?: number }) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try { wsRef.current.send(JSON.stringify({ action: 'map_3d/set_config', ...config })); } catch {}
      }
      return true;
    }, []),
    setLidarEnabled: useCallback((enabled: boolean) => {
      setMap3DStatus(prev => prev ? { ...prev, lidar_enabled: enabled } : null);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({ action: 'map_3d/enable_lidar', enabled }));
          return true;
        } catch (e) {
          console.warn('Falha ao enviar map_3d/enable_lidar:', e);
          return false;
        }
      }
      return false;
    }, []),

    // Fase 2: Métricas de renderização e Scan Manager Local
    scanList,
    scanStatus,
    storageInfo,
    startScan: useCallback(() => false, []),
    stopScan: useCallback(() => false, []),
    refreshScans: useCallback(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({ action: 'map_3d/scan/list' }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/scan/list:', e);
        return false;
      }
    }, []),
    deleteScan: useCallback(() => false, []),
    viewScan: useCallback((scanId: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'map_3d/scan/view',
          scan_id: scanId
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/scan/view:', e);
        return false;
      }
    }, []),
    refreshStorage: useCallback(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({ action: 'map_3d/storage/info' }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/storage/info:', e);
        return false;
      }
    }, []),
    setRenderLatency: useCallback((renderMs: number) => {
      frontendRenderMsRef.current = renderMs;
    }, []),
    controlState,
    acquireControl,
    releaseControl
  };
}
