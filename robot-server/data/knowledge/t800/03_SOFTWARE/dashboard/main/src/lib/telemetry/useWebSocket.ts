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
import { cameraFrameEmitter } from './cameraEvents';

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

const STORAGE_KEY = 't800_ws_url';
const DEFAULT_BASE_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://192.168.102.133:8090';

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
  const [baseUrl, setBaseUrlState] = useState<string>(() => {
    if (initialUrl) return initialUrl;
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) return saved;
        if (window.location.hostname) {
          const detected = `ws://${window.location.hostname}:8090`;
          localStorage.setItem(STORAGE_KEY, detected);
          return detected;
        }
      } catch {}
    }
    return DEFAULT_BASE_URL;
  });

  const [telemetry, setTelemetry] = useState<T800Telemetry | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('DISCONNECTED');
  const [diagnostics, setDiagnostics] = useState<NetworkDiagnostics>(DEFAULT_DIAGNOSTICS);
  const [cameraQualityMode, setCameraQualityMode] = useState<'auto' | 'low' | 'high'>('auto');

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

  // Buffer amortecedor para limitar reconciliações do React raiz a ~10 Hz (100ms)
  const latestTelemetryDataRef = useRef<T800Telemetry | null>(null);
  const telemetryFlushTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastTelemetryCommitTimeRef = useRef<number>(0);

  const commitTelemetry = useCallback((data: T800Telemetry) => {
    const prev = latestTelemetryDataRef.current;
    const merged: T800Telemetry = prev ? {
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
            ...(data.cameras.person_annotated ? { person_annotated: data.cameras.person_annotated } : {}),
          }
        : prev.cameras,
      camera_info: data.camera_info ? { ...prev.camera_info, ...data.camera_info } : prev.camera_info,
      cloud_points: data.cloud_points || prev.cloud_points,
    } : data;

    latestTelemetryDataRef.current = merged;

    const now = Date.now();
    const elapsed = now - lastTelemetryCommitTimeRef.current;

    // Garante no máximo 10 atualizações de estado do React por segundo
    if (elapsed >= 100) {
      if (telemetryFlushTimerRef.current) {
        clearTimeout(telemetryFlushTimerRef.current);
        telemetryFlushTimerRef.current = null;
      }
      lastTelemetryCommitTimeRef.current = now;
      setTelemetry(merged);
    } else if (!telemetryFlushTimerRef.current) {
      telemetryFlushTimerRef.current = setTimeout(() => {
        telemetryFlushTimerRef.current = null;
        lastTelemetryCommitTimeRef.current = Date.now();
        if (latestTelemetryDataRef.current) {
          setTelemetry(latestTelemetryDataRef.current);
        }
      }, 100 - elapsed);
    }
  }, []);

  // Sincroniza a qualidade da câmera com o robô de forma dinâmica (mantendo 1280px de alta fidelidade)
  useEffect(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    let width = 1280;
    let quality = 85;
    
    if (cameraQualityMode === 'low') {
      width = 640;
      quality = 60;
    } else if (cameraQualityMode === 'high') {
      width = 1280;
      quality = 90;
    } else {
      // Modo Auto / Padrão: Mantém fidelidade nativa em 1280px
      width = 1280;
      quality = 85;
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
  }, [cameraQualityMode, connectionStatus, diagnostics.latencyMs, baseUrl, activeTab]);

  const wsRef = useRef<WebSocket | null>(null);
  const frameCountRef = useRef<number>(0);
  const byteCountRef = useRef<number>(0);
  const lastMetricsTimeRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayMs = useRef<number>(1000); // Start with 1s
  const wasConnectedRef = useRef<boolean>(false);
  const cameraBlobUrlsRef = useRef<Record<string, string>>({});
  const lastCameraStateUpdateRef = useRef<Record<string, number>>({});
  const lastCloudUiUpdateRef = useRef<number>(0);

  const activeTabRef = useRef<string>(activeTab);
  const activeCamRef = useRef<string>(activeCam);

  // Sincroniza a aba e câmera ativas com o robô em tempo real (para economia de CPU/Rede de bordo)
  useEffect(() => {
    activeTabRef.current = activeTab;
    activeCamRef.current = activeCam;

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    const effectiveCam = activeTab === 'cv_test' ? 'person_annotated' : activeCam;
    try {
      wsRef.current.send(JSON.stringify({
        action: 'set_active_view',
        active_tab: activeTab,
        active_cam: effectiveCam
      }));
    } catch (e) {
      console.error('Falha ao enviar comando de visualização ativa:', e);
    }
  }, [activeTab, activeCam, connectionStatus, baseUrl]);

  const setBaseUrl = useCallback((newUrl: string) => {
    if (!newUrl) return;
    const sanitized = newUrl.trim();
    setBaseUrlState(sanitized);
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, sanitized);
    }
  }, []);

  useEffect(() => {
    lastMetricsTimeRef.current = Date.now();
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
        // Sincroniza visualização ativa e modo binário de alta performance
        try {
          const tab = activeTabRef.current;
          const cam = activeCamRef.current;
          const effectiveCam = tab === 'cv_test' ? 'person_annotated' : cam;
          ws.send(JSON.stringify({ action: 'set_camera_stream_mode', mode: 'binary' }));
          ws.send(JSON.stringify({ action: 'set_active_view', active_tab: tab, active_cam: effectiveCam }));
        } catch {
          // ignore
        }

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

        // 1. Processamento de Frames Binários de Alto Desempenho (Zero-Copy)
        if (event.data instanceof ArrayBuffer) {
          const buffer = event.data;
          if (buffer.byteLength >= 24) {
            const dataView = new DataView(buffer);
            const magic = dataView.getUint8(0);

            // 1a. Stream Binário de Câmeras (0x43 = 'C' Zero-Copy)
            if (magic === 0x43) {
              const camId = dataView.getUint8(2);
              const format = dataView.getUint8(3);
              const width = dataView.getUint32(4, true);
              const height = dataView.getUint32(8, true);
              const seq = dataView.getUint32(12, true);
              const timestamp = dataView.getFloat64(16, true);

              const CAM_ID_MAP: Record<number, string> = {
                0: 'cam0',
                1: 'cam1',
                2: 'gray',
                3: 'overlay',
                4: 'person_annotated'
              };
              const camKey = CAM_ID_MAP[camId] || 'cam0';

              // Extrai fatia de bytes de imagem pura sem base64 (Zero-Copy)
              const imgBytes = new Uint8Array(buffer, 24);
              const mimeType = format === 1 ? 'image/png' : 'image/jpeg';
              const blob = new Blob([imgBytes], { type: mimeType });

              // 1. Descodificação de alta performance assíncrona (GPU / Off-Main-Thread)
              if (typeof createImageBitmap !== 'undefined') {
                createImageBitmap(blob).then((bitmap) => {
                  cameraFrameEmitter.emit(camKey, bitmap, {
                    width: width || bitmap.width,
                    height: height || bitmap.height,
                    seq,
                    timestamp,
                    mimeType,
                    blob
                  });
                }).catch(() => {
                  // ignore decode failure
                });
              }

              // 2. Atualização amortecida de telemetria (1 Hz) para não travar o React com 30 re-renders/s
              const nowTs = Date.now();
              const lastUpdate = lastCameraStateUpdateRef.current[camKey] || 0;
              if (nowTs - lastUpdate > 1000) {
                lastCameraStateUpdateRef.current[camKey] = nowTs;
                const blobUrl = URL.createObjectURL(blob);
                cameraFrameEmitter.setLatestBlobUrl(camKey, blobUrl);

                // Revogação segura após delay para não abortar leituras em andamento
                const oldUrl = cameraBlobUrlsRef.current[camKey];
                if (oldUrl && oldUrl !== blobUrl) {
                  setTimeout(() => {
                    try { URL.revokeObjectURL(oldUrl); } catch {}
                  }, 2500);
                }
                cameraBlobUrlsRef.current[camKey] = blobUrl;

                setTelemetry(prev => {
                  if (!prev) return prev;
                  return {
                    ...prev,
                    cameras: {
                      ...(prev.cameras || {}),
                      [camKey]: blobUrl
                    },
                    camera_info: (width > 0 && height > 0) ? {
                      ...(prev.camera_info || {}),
                      [camKey]: { width, height }
                    } : prev.camera_info
                  };
                });
              }
              return;
            }

            // 1b. Mapeamento 3D Nuvem de Pontos (0x3D = '=')
            if (magic === 0x3d && buffer.byteLength >= 36) {
              const pointCount = dataView.getUint32(4, true);
              // offset 8: scanId uint32 (reservado)
              const t0Sensor = dataView.getFloat64(12, true);
              const t2Backend = dataView.getFloat64(20, true);
              const zMin = dataView.getFloat32(28, true);
              const zMax = dataView.getFloat32(32, true);

              // View direta TypedArray sem cópia de memória
              const pointsFloat = new Float32Array(buffer, 36, pointCount * 3);

              const t3Browser = Date.now() / 1000;
              // Sanitização contra relógios descalibrados ou timestamps não-epoch
              let wsLatencyMs = 0;
              if (typeof t2Backend === 'number' && t2Backend > 1_000_000_000) {
                const diff = (t3Browser - t2Backend) * 1000;
                if (diff >= 0 && diff < 10000) {
                  wsLatencyMs = Math.round(diff);
                }
              }

              let sensorToBackendMs = 0;
              if (
                typeof t0Sensor === 'number' &&
                typeof t2Backend === 'number' &&
                t0Sensor > 1_000_000_000 &&
                t2Backend > 1_000_000_000
              ) {
                const diff = (t2Backend - t0Sensor) * 1000;
                if (diff >= 0 && diff < 10000) {
                  sensorToBackendMs = Math.round(diff);
                }
              }

              if (activeTabRef.current === 'pointcloud') {
                const nowCloudUi = Date.now();
                if (nowCloudUi - lastCloudUiUpdateRef.current >= 180) {
                  lastCloudUiUpdateRef.current = nowCloudUi;
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
                    const backendMs = (typeof prevLat.backend_processing_ms === 'number' && prevLat.backend_processing_ms >= 0 && prevLat.backend_processing_ms < 10000)
                      ? prevLat.backend_processing_ms
                      : 0;
                    const renderMs = Math.round(frontendRenderMsRef.current || 0);
                    const totalMs = sensorToBackendMs + backendMs + wsLatencyMs + renderMs;
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
                        backend_processing_ms: backendMs,
                        websocket_latency_ms: wsLatencyMs,
                        frontend_render_ms: renderMs,
                        total_latency_ms: totalMs
                      }
                    };
                  });
                }
              }
              return;
            }
          }
        }

        try {
          const rawData = JSON.parse(event.data);

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
            const is3DTab = activeTabRef.current === 'pointcloud';
            if (rawData.type === 'map_3d/pointcloud') {
              if (is3DTab) setMap3DPointCloud(rawData);
            } else if (rawData.type === 'map_3d/pose') {
              if (is3DTab) setMap3DPose(rawData);
            } else if (rawData.type === 'map_3d/trajectory') {
              if (is3DTab) setMap3DTrajectory(rawData);
            } else if (rawData.type === 'map_3d/lidar_status') {
              setMap3DStatus(prev => prev ? { ...prev, lidar_enabled: !!rawData.enabled } : null);
            } else if (rawData.type === 'map_3d/status') {
              if (is3DTab) {
                setMap3DStatus(prev => {
                  const rawLat = rawData.latency || {};
                  const prevLat = prev?.latency || {};

                  const sensorMs = (typeof rawLat.sensor_to_backend_ms === 'number' && rawLat.sensor_to_backend_ms >= 0 && rawLat.sensor_to_backend_ms < 10000)
                    ? rawLat.sensor_to_backend_ms
                    : ((typeof prevLat.sensor_to_backend_ms === 'number' && prevLat.sensor_to_backend_ms >= 0 && prevLat.sensor_to_backend_ms < 10000)
                        ? prevLat.sensor_to_backend_ms
                        : 0);

                  const backendMs = (typeof rawLat.backend_processing_ms === 'number' && rawLat.backend_processing_ms >= 0 && rawLat.backend_processing_ms < 10000)
                    ? rawLat.backend_processing_ms
                    : ((typeof prevLat.backend_processing_ms === 'number' && prevLat.backend_processing_ms >= 0 && prevLat.backend_processing_ms < 10000)
                        ? prevLat.backend_processing_ms
                        : 0);

                  const wsMs = (typeof prevLat.websocket_latency_ms === 'number' && prevLat.websocket_latency_ms >= 0 && prevLat.websocket_latency_ms < 10000)
                    ? prevLat.websocket_latency_ms
                    : 0;
                  const renderMs = Math.round(frontendRenderMsRef.current || 0);
                  const totalMs = sensorMs + backendMs + wsMs + renderMs;

                  return {
                    ...prev,
                    ...rawData,
                    latency: {
                      ...prevLat,
                      ...rawLat,
                      sensor_to_backend_ms: sensorMs,
                      backend_processing_ms: backendMs,
                      websocket_latency_ms: wsMs,
                      frontend_render_ms: renderMs,
                      total_latency_ms: totalMs
                    }
                  };
                });
              }
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

          const imu = rawData.imu;
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

          commitTelemetry(data);
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
        
        // Exponential backoff up to max 30s + random jitter for smoother reconnects
        const jitter = Math.random() * 500;
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectDelayMs.current = Math.min(reconnectDelayMs.current * 2, 30000);
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
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (telemetryFlushTimerRef.current) {
        clearTimeout(telemetryFlushTimerRef.current);
        telemetryFlushTimerRef.current = null;
      }
      if (wsRef.current) {
        if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
          wsRef.current.close();
        }
      }
      // Revoga URLs de blob criadas para evitar vazamento de memória
      Object.values(cameraBlobUrlsRef.current).forEach(url => {
        if (url) {
          try {
            URL.revokeObjectURL(url);
          } catch {}
        }
      });
      cameraBlobUrlsRef.current = {};
      cameraFrameEmitter.clear();
    };
  }, [baseUrl]);

  const sendSpeech = useCallback((text: string, voice: string = 'pt-BR-AntonioNeural', speed: string | number = '1.20') => {
    const cleanText = text.trim();
    if (!cleanText) return false;

    let sent = false;

    // 1. Envio via WebSocket (se conectado) - caminho prioritário de menor latência e sem sobrecarga TCP
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({
          action: 'speak',
          text: cleanText,
          voice: voice,
          speed: String(speed)
        }));
        sent = true;
      } catch (wsErr) {
        console.warn('Falha ao enviar áudio via WebSocket:', wsErr);
      }
    } else {
      // 2. Envio direto via HTTP REST (porta 5000 - speech_server.py / Flask) somente se WebSocket offline
      try {
        let host = '127.0.0.1';
        if (baseUrl) {
          const match = baseUrl.match(/:\/\/([^:/]+)/);
          if (match && match[1]) {
            host = match[1];
          }
        }
        const httpEndpoint = process.env.NEXT_PUBLIC_SPEECH_URL || `http://${host}:5000/speak`;
        fetch(httpEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: cleanText,
            voice: voice,
            rate: '+20%'
          }),
          mode: 'cors'
        }).then(() => {
          sent = true;
        }).catch((err) => {
          console.warn('Falha ao conectar no speech_server (porta 5000):', err);
        });
      } catch (e) {
        console.error('Erro ao enviar áudio via HTTP fallback:', e);
      }
    }

    return sent;
  }, [baseUrl]);

  const sendNeckMove = useCallback((pitch: number, yaw: number, duration: number = 1.5) => {
    let sent = false;
    // 1. Envio prioritário via WebSocket
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({
          action: 'neck_move',
          pitch: Number(pitch),
          yaw: Number(yaw),
          duration: Number(duration)
        }));
        sent = true;
      } catch (e) {
        console.warn('Falha ao enviar comando de pescoço via WS:', e);
      }
    } else {
      // 2. Fallback via HTTP REST direto para porta 5055 (neck_controller.py)
      try {
        let host = '127.0.0.1';
        if (baseUrl) {
          const match = baseUrl.match(/:\/\/([^:/]+)/);
          if (match && match[1]) host = match[1];
        }
        fetch(`http://${host}:5055/move`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pitch: Number(pitch), yaw: Number(yaw), duration: Number(duration) }),
          mode: 'cors'
        }).then(() => {
          sent = true;
        }).catch((err) => {
          console.warn('Falha HTTP neck_move:', err);
        });
      } catch (e) {
        console.error('Erro no fallback HTTP neck_move:', e);
      }
    }
    return sent;
  }, [baseUrl]);

  const sendNeckStep = useCallback((dPitch: number, dYaw: number, duration: number = 0.4) => {
    let sent = false;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({
          action: 'neck_step',
          d_pitch: Number(dPitch),
          d_yaw: Number(dYaw),
          duration: Number(duration)
        }));
        sent = true;
      } catch (e) {
        console.warn('Falha ao enviar passo de pescoço via WS:', e);
      }
    } else {
      try {
        let host = '127.0.0.1';
        if (baseUrl) {
          const match = baseUrl.match(/:\/\/([^:/]+)/);
          if (match && match[1]) host = match[1];
        }
        fetch(`http://${host}:5055/step`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ d_pitch: Number(dPitch), d_yaw: Number(dYaw), duration: Number(duration) }),
          mode: 'cors'
        }).then(() => {
          sent = true;
        }).catch((err) => {
          console.warn('Falha HTTP neck_step:', err);
        });
      } catch (e) {
        console.error('Erro no fallback HTTP neck_step:', e);
      }
    }
    return sent;
  }, [baseUrl]);

  const sendNeckCenter = useCallback((duration: number = 1.5) => {
    let sent = false;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({
          action: 'neck_center',
          duration: Number(duration)
        }));
        sent = true;
      } catch (e) {
        console.warn('Falha ao enviar comando de centralização via WS:', e);
      }
    } else {
      try {
        let host = '127.0.0.1';
        if (baseUrl) {
          const match = baseUrl.match(/:\/\/([^:/]+)/);
          if (match && match[1]) host = match[1];
        }
        fetch(`http://${host}:5055/center`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ duration: Number(duration) }),
          mode: 'cors'
        }).then(() => {
          sent = true;
        }).catch((err) => {
          console.warn('Falha HTTP neck_center:', err);
        });
      } catch (e) {
        console.error('Erro no fallback HTTP neck_center:', e);
      }
    }
    return sent;
  }, [baseUrl]);

  const sendNeckBalanceMode = useCallback((enable: boolean = true) => {
    let sent = false;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify({
          action: 'neck_balance',
          enable
        }));
        sent = true;
      } catch (e) {
        console.warn('Falha ao enviar comando neck_balance via WS:', e);
      }
    } else {
      try {
        let host = '127.0.0.1';
        if (baseUrl) {
          const match = baseUrl.match(/:\/\/([^:/]+)/);
          if (match && match[1]) host = match[1];
        }
        fetch(`http://${host}:5055/balance_mode`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enable }),
          mode: 'cors'
        }).then(() => {
          sent = true;
        }).catch((err) => {
          console.warn('Falha HTTP neck_balance:', err);
        });
      } catch (e) {
        console.error('Erro no fallback HTTP neck_balance:', e);
      }
    }
    return sent;
  }, [baseUrl]);

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
    startBagRecording: useCallback((filename?: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'start_bag_recording',
          filename: filename || ''
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar start_bag_recording:', e);
        return false;
      }
    }, []),
    stopBagRecording: useCallback(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'stop_bag_recording'
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar stop_bag_recording:', e);
        return false;
      }
    }, []),
    sendLedControl: useCallback((color: number) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'set_led',
          color
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar comando set_led:', e);
        return false;
      }
    }, []),

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
    startScan: useCallback((profile?: string, name?: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'map_3d/scan/start',
          profile: profile || 'STANDARD',
          name: name || ''
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/scan/start:', e);
        return false;
      }
    }, []),
    stopScan: useCallback(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({ action: 'map_3d/scan/stop' }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/scan/stop:', e);
        return false;
      }
    }, []),
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
    deleteScan: useCallback((scanId: string) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return false;
      try {
        wsRef.current.send(JSON.stringify({
          action: 'map_3d/scan/delete',
          scan_id: scanId
        }));
        return true;
      } catch (e) {
        console.warn('Falha ao enviar map_3d/scan/delete:', e);
        return false;
      }
    }, []),
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
    }, [])
  };
}
