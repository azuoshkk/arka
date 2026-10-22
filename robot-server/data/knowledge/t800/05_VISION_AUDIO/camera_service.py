#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Gerenciamento de Câmeras e Visão Computacional.
Localização: modules_dashboard/camera/camera_service.py
Responsável por:
1. Subscrição e conversão de frames das câmeras ROS 2 (cam0, cam1, gray).
2. Compressão dinâmica de JPEG e redimensionamento sob demanda.
3. Watchdog e ciclo de vida do driver de câmera (odin_ros_driver_rev1).
4. Gravação nativa em MP4 e servidor REST na porta 5050.
"""

import os
import time
import base64
import struct
import threading
import subprocess
from typing import Optional, Dict, Any, List, Callable
from modules_dashboard.common.base_module import BaseModule
from modules_dashboard.camera.video_recorder import RobotVideoRecorder, start_recorder_server, HTTP_RECORDER_PORT

# Configurações padrão de alta performance e alta fidelidade (1280px @ 30 FPS)
DEFAULT_CAMERA_FPS = 30.0
DEFAULT_IMAGE_WIDTH = 1280
DEFAULT_IMAGE_HEIGHT = 720
DEFAULT_JPEG_QUALITY = 85

# Constantes do Protocolo Binário de Câmeras (Zero-Copy)
CAMERA_MAGIC_BYTE = 0x43  # 'C'
CAMERA_PROTOCOL_VERSION = 1

CAMERA_KEY_TO_ID: Dict[str, int] = {
    "cam0": 0,
    "cam1": 1,
    "gray": 2,
    "overlay": 3,
    "person_annotated": 4
}
CAMERA_ID_TO_KEY: Dict[int, str] = {v: k for k, v in CAMERA_KEY_TO_ID.items()}

# Header Format (24 bytes Little-Endian '<BBBBIIId'):
# [0]  uint8   magic (0x43)
# [1]  uint8   version (1)
# [2]  uint8   cam_id (0: cam0, 1: cam1, 2: gray, 3: overlay, 4: person_annotated, 255: outro)
# [3]  uint8   format (0: jpeg, 1: png)
# [4]  uint32  width
# [8]  uint32  height
# [12] uint32  seq
# [16] float64 timestamp (epoch seconds)
CAMERA_HEADER_FORMAT = "<BBBBIIId"
CAMERA_HEADER_SIZE = struct.calcsize(CAMERA_HEADER_FORMAT)
assert CAMERA_HEADER_SIZE == 24

def pack_camera_binary(
    cam_key: str,
    img_bytes: bytes,
    width: int = 0,
    height: int = 0,
    seq: int = 0,
    timestamp: Optional[float] = None,
    is_png: bool = False
) -> bytes:
    """Empacota frame de câmera em protocolo binário Zero-Copy (24 bytes header + bytes puros)."""
    if timestamp is None:
        timestamp = time.time()
    cam_id = CAMERA_KEY_TO_ID.get(cam_key, 255)
    fmt_id = 1 if is_png else 0
    header = struct.pack(
        CAMERA_HEADER_FORMAT,
        CAMERA_MAGIC_BYTE,
        CAMERA_PROTOCOL_VERSION,
        cam_id,
        fmt_id,
        int(width),
        int(height),
        int(seq),
        float(timestamp)
    )
    return header + img_bytes

def get_camera_key(topic_name: str) -> Optional[str]:
    """Mapeia o nome do tópico ROS 2 para a chave do dashboard ('cam0', 'cam1', 'gray', 'overlay', 'person_annotated')."""
    t_lower = topic_name.lower()
    if 'pessoa' in t_lower or 'person' in t_lower or 'annotated' in t_lower:
        return 'person_annotated'
    elif 'reprojection' in t_lower or 'overlay' in t_lower:
        return 'overlay'
    elif 'camera0' in t_lower or 'cam0' in t_lower:
        return 'cam0'
    elif 'camera1' in t_lower or 'cam1' in t_lower:
        return 'cam1'
    elif 'gray' in t_lower:
        return 'gray'
    return None

class CameraService(BaseModule):
    """Serviço unificado de processamento de vídeo, gravação e driver watchdog."""
    def __init__(self, logger: Optional[Any] = None, auto_start_driver: bool = True):
        super().__init__("camera", logger)
        self.lock = threading.RLock()
        self.auto_start_driver = auto_start_driver
        self.driver_process = None
        
        # Gravador nativo e servidor HTTP 5050
        self.video_recorder = RobotVideoRecorder(logger=self.log)
        self.http_server = None
        
        # Configurações dinâmicas de renderização: Zero-Copy nativo direto em 1280px para máxima performance (30 FPS)
        self.active_tab = "overview"
        self.active_cam = "cam0"
        self.compress_and_resize = False
        self.target_image_width = DEFAULT_IMAGE_WIDTH
        self.jpeg_quality = DEFAULT_JPEG_QUALITY
        self.max_camera_fps = DEFAULT_CAMERA_FPS
        
        # Modo de transmissão: 'both' por padrão (compatibilidade total),
        # clientes de alta performance mudam dinamicamente para 'binary' (Zero-Copy)
        self.stream_mode = "both"
        self.on_frame_ready: Optional[Callable[[bytes], None]] = None
        self.pending_binary_frames: Dict[str, bytes] = {}
        self.frame_seq: Dict[str, int] = {k: 0 for k in CAMERA_KEY_TO_ID}

        # Buffers de quadros e metadados
        self.pending_cameras: Dict[str, str] = {}
        self.camera_info: Dict[str, Dict[str, Any]] = {}
        self.camera_stats: Dict[str, Dict[str, Any]] = {
            "cam0": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "cam1": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "gray": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "overlay": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "person_annotated": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0}
        }
        self.has_connected_clients = True
        self.latest_cloud_points = None
        self.last_native_overlay_time = 0.0

    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if context:
            self.auto_start_driver = context.get("auto_start_driver", self.auto_start_driver)
            self.max_camera_fps = context.get("max_fps", self.max_camera_fps)
            self.stream_mode = context.get("stream_mode", self.stream_mode)
        
        # Inicia o servidor HTTP de gravação na porta 5050
        speech_cb = context.get("speech_callback") if context else None
        self.http_server = start_recorder_server(self.video_recorder, speech_cb=speech_cb, port=HTTP_RECORDER_PORT)
        if self.http_server:
            self.log(f"Servidor REST de gravação ativo na porta {HTTP_RECORDER_PORT}.")
            
        self.is_initialized = True
        self.status = "INITIALIZED"
        return True

    def start(self) -> bool:
        self.is_running = True
        self.start_time = time.time()
        self.status = "RUNNING"
        self.log("Módulo de câmeras ativo.")
        return True

    def set_has_clients(self, has_clients: bool):
        self.has_connected_clients = has_clients

    def set_stream_mode(self, mode: str):
        with self.lock:
            if mode in ["binary", "base64", "both"]:
                self.stream_mode = mode
                self.log(f"Modo de stream de câmera alterado para: {mode}")

    def set_frame_callback(self, cb: Optional[Callable[[bytes], None]]):
        """Define o callback de despacho imediato de frames binários (Event-Driven Zero-Copy)."""
        self.on_frame_ready = cb

    def set_camera_config(self, target_width: Optional[int] = None, jpeg_quality: Optional[int] = None, max_fps: Optional[float] = None, compress_and_resize: Optional[bool] = None):
        with self.lock:
            if compress_and_resize is not None:
                self.compress_and_resize = bool(compress_and_resize)
            elif isinstance(target_width, int) and target_width > 0:
                self.target_image_width = target_width
                # Para resoluções nativas (1280px), desativa software resize para manter Zero-Copy e 30 FPS pleno
                self.compress_and_resize = (target_width < 1280)
            if isinstance(jpeg_quality, int) and 0 < jpeg_quality <= 100:
                self.jpeg_quality = jpeg_quality
            if isinstance(max_fps, (int, float)) and max_fps > 0:
                self.max_camera_fps = float(max_fps)
        self.log(f"Configuração atualizada: Width={self.target_image_width}, Quality={self.jpeg_quality}%, MaxFPS={self.max_camera_fps}, CompressAndResize={self.compress_and_resize}")

    def set_active_view(self, active_tab: Optional[str] = None, active_cam: Optional[str] = None):
        with self.lock:
            if active_tab:
                self.active_tab = active_tab
            if active_cam:
                self.active_cam = active_cam
        self.log(f"Visualização ativa: Tab={self.active_tab}, Cam={self.active_cam}")

    def is_camera_active(self, key: str) -> bool:
        """Determina de forma inteligente e sob demanda se uma câmera deve ser processada e enviada."""
        # 1. Se estiver gravando vídeo nativo, a câmera da gravação deve estar ativa
        if self.video_recorder.is_recording:
            rec_cam = getattr(self.video_recorder, 'recording_camera', self.active_cam)
            if key == rec_cam or rec_cam == "all":
                return True

        # 2. Se nenhum dashboard estiver conectado, interrompe processamento de vídeo para economizar CPU
        if not self.has_connected_clients:
            return False

        # 3. Transmissão forçada de todas as câmeras
        if self.active_cam == "all":
            return True

        # 4. Modo estéreo explícito
        if self.active_cam == "stereo" and key in ["cam0", "cam1"]:
            return True

        # 5. Abas de Standby sem viewport de vídeo (Hardware, Watchdog, Logs)
        if self.active_tab in ["hardware", "watchdog", "logs", "settings"]:
            return False

        # 6. Aba de Teste de Visão / Detecção de Pessoas (cv_test)
        if self.active_tab in ["cv_test", "people_vision"]:
            return key == "person_annotated" or (key == "cam0" and getattr(self, 'cv_split_view', False))

        # 7. Aba de Mapeamento 3D / PointCloud: PiP suporta CAM0 e LiDAR Overlay simultaneamente
        if self.active_tab in ["pointcloud", "map3d", "map_3d"]:
            return key in ["cam0", "overlay"]

        # 8. Abas de Cockpit e Visão (Overview, Perception):
        # Transmite APENAS a câmera ativamente selecionada pelo operador (economiza 50-70% de banda)
        return key == self.active_cam

    def _raw_msg_to_cv2(self, msg):
        """Converte sensor_msgs/msg/Image para imagem OpenCV (BGR8) de forma robusta e sem travar."""
        try:
            import numpy as np
            import cv2
            h = int(msg.height)
            w = int(msg.width)
            enc = getattr(msg, 'encoding', 'bgr8').lower()
            data = np.frombuffer(bytes(msg.data), dtype=np.uint8)

            if 'mono8' in enc or '8uc1' in enc or enc == 'gray':
                cv_img = data[:h * w].reshape((h, w))
                return cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
            elif 'bgr8' in enc or enc == 'bgr':
                return data[:h * w * 3].reshape((h, w, 3))
            elif 'rgb8' in enc or enc == 'rgb':
                cv_img = data[:h * w * 3].reshape((h, w, 3))
                return cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
            elif 'bgra8' in enc:
                cv_img = data[:h * w * 4].reshape((h, w, 4))
                return cv2.cvtColor(cv_img, cv2.COLOR_BGRA2BGR)
            elif 'rgba8' in enc:
                cv_img = data[:h * w * 4].reshape((h, w, 4))
                return cv2.cvtColor(cv_img, cv2.COLOR_RGBA2BGR)
            elif 'mono16' in enc or '16uc1' in enc:
                data16 = np.frombuffer(bytes(msg.data), dtype=np.uint16)
                cv_img = (data16[:h * w].reshape((h, w)) // 256).astype(np.uint8)
                return cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
            elif 'yuv' in enc or 'yuyv' in enc:
                cv_img = data[:h * w * 2].reshape((h, w, 2))
                return cv2.cvtColor(cv_img, cv2.COLOR_YUV2BGR_YUYV)
        except Exception:
            pass

        try:
            from cv_bridge import CvBridge
            bridge = CvBridge()
            return bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception:
            return None

    def update_point_cloud(self, points_or_msg):
        """Atualiza o buffer de nuvem de pontos 3D para reprojeção no feed de câmera."""
        if not self.is_camera_active('overlay'):
            return

        try:
            import numpy as np
            if hasattr(points_or_msg, 'data') and hasattr(points_or_msg, 'point_step'):
                point_step = points_or_msg.point_step
                x_offset = next((f.offset for f in points_or_msg.fields if f.name == 'x'), 0)
                y_offset = next((f.offset for f in points_or_msg.fields if f.name == 'y'), 4)
                z_offset = next((f.offset for f in points_or_msg.fields if f.name == 'z'), 8)
                endian = '<f4' if not getattr(points_or_msg, 'is_bigendian', False) else '>f4'
                dt = np.dtype({
                    'names': ['x', 'y', 'z'],
                    'formats': [endian, endian, endian],
                    'offsets': [x_offset, y_offset, z_offset],
                    'itemsize': point_step
                })
                cloud = np.frombuffer(bytes(points_or_msg.data), dtype=dt)
                pts = np.column_stack((cloud['x'], cloud['y'], cloud['z']))
                valid = ~np.isnan(pts).any(axis=1)
                pts = pts[valid]
                if len(pts) > 2500:
                    pts = pts[::max(1, len(pts) // 2500)]
                with self.lock:
                    self.latest_cloud_points = pts
            elif isinstance(points_or_msg, (list, tuple, np.ndarray)):
                arr = np.asarray(points_or_msg)
                if arr.ndim == 1 and len(arr) % 3 == 0:
                    arr = arr.reshape(-1, 3)
                if arr.ndim == 2 and arr.shape[1] >= 3:
                    valid = ~np.isnan(arr[:, :3]).any(axis=1)
                    pts = arr[valid, :3]
                    if len(pts) > 2500:
                        pts = pts[::max(1, len(pts) // 2500)]
                    with self.lock:
                        self.latest_cloud_points = pts
        except Exception as e:
            self.record_error(e, "update_point_cloud")

    def _synthesize_lidar_overlay(self, cv_img, points_3d):
        """Projeta a nuvem de pontos 3D LiDAR sobre o frame CAM0 com mapa de cores de profundidade."""
        try:
            import cv2
            import numpy as np

            if cv_img is None or points_3d is None or len(points_3d) == 0:
                return

            overlay = cv_img.copy()
            h, w = overlay.shape[:2]

            cam_info = self.camera_info.get('cam0', {})
            fx = float(cam_info.get('fx', w * 0.75))
            fy = float(cam_info.get('fy', w * 0.75))
            cx = float(cam_info.get('cx', w / 2.0))
            cy = float(cam_info.get('cy', h / 2.0))

            x = points_3d[:, 0]
            y = points_3d[:, 1]
            z = points_3d[:, 2]

            # Detecta eixo para frente (+X ou +Z)
            x_pos = np.sum((x > 0.3) & (x < 20.0))
            z_pos = np.sum((z > 0.3) & (z < 20.0))

            if x_pos >= z_pos:
                depth = x
                horiz = -y
                vert = -z
            else:
                depth = z
                horiz = x
                vert = y

            valid_depth = (depth > 0.3) & (depth < 18.0)
            if not np.any(valid_depth):
                return

            d = depth[valid_depth]
            hx = horiz[valid_depth]
            vy = vert[valid_depth]

            u = (cx + fx * (hx / d)).astype(np.int32)
            v = (cy + fy * (vy / d)).astype(np.int32)

            in_frame = (u >= 0) & (u < w) & (v >= 0) & (v < h)
            if not np.any(in_frame):
                return

            u = u[in_frame]
            v = v[in_frame]
            d = d[in_frame]

            norm_d = np.clip((d - 0.4) / 10.0, 0.0, 1.0)
            lut_idx = (norm_d * 255).astype(np.uint8).reshape(-1, 1)
            colormap = cv2.applyColorMap(lut_idx, cv2.COLORMAP_TURBO)

            sort_idx = np.argsort(-d)
            u = u[sort_idx]
            v = v[sort_idx]
            colors = colormap[sort_idx, 0]

            # Renderização in-place vetorizada de alto desempenho (< 0.1 ms)
            overlay[v, u] = colors

            # Adiciona carimbo de overlay
            pts_count = len(u)
            cv2.putText(
                overlay,
                f"LIDAR OVERLAY: {pts_count} PTS",
                (12, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
                cv2.LINE_AA
            )

            # Redimensiona se compress_and_resize estiver ativo
            if self.compress_and_resize and w > self.target_image_width:
                new_h = int(h * (self.target_image_width / w))
                overlay = cv2.resize(overlay, (self.target_image_width, new_h), interpolation=cv2.INTER_AREA)

            quality = self.jpeg_quality if self.compress_and_resize else 85
            success, encoded_img = cv2.imencode('.jpg', overlay, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if success:
                raw_bytes = encoded_img.tobytes()
                now_ts = time.time()
                with self.lock:
                    if 'overlay' not in self.camera_stats:
                        self.camera_stats['overlay'] = {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0}
                    self.camera_stats['overlay']['msg_count'] += 1
                    self.camera_stats['overlay']['last_msg_time'] = now_ts
                    
                    # 1. Empacotamento binário de alta performance
                    if self.stream_mode in ["binary", "both"]:
                        seq = self.frame_seq.get('overlay', 0) + 1
                        self.frame_seq['overlay'] = seq
                        bframe = pack_camera_binary('overlay', raw_bytes, width=w, height=h, seq=seq, timestamp=now_ts)
                        self.pending_binary_frames['overlay'] = bframe
                        if self.on_frame_ready:
                            try:
                                self.on_frame_ready(bframe)
                            except Exception:
                                pass

                    # 2. Base64 apenas se solicitado explicitamente
                    if self.stream_mode in ["base64", "both"]:
                        b64_str = base64.b64encode(raw_bytes).decode('utf-8')
                        self.pending_cameras['overlay'] = f"data:image/jpeg;base64,{b64_str}"
        except Exception as e:
            self.record_error(e, "synthesize_lidar_overlay")

    # --------------------------------------------------------------------------
    # Callbacks de Imagem
    # --------------------------------------------------------------------------
    def process_compressed_image(self, msg, topic_name: str):
        key = get_camera_key(topic_name)
        if not key:
            return

        now = time.time()
        if key == 'overlay':
            self.last_native_overlay_time = now

        if key not in self.camera_stats:
            self.camera_stats[key] = {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0}
        stats = self.camera_stats[key]
        
        # Otimização Inteligente: ignora se a câmera não for a ativa no momento
        if not self.is_camera_active(key):
            return

        # Otimização: ignora se nenhum dashboard estiver conectado
        if not self.has_connected_clients:
            stats['last_msg_time'] = now
            stats['msg_count'] += 1
            return

        # Cadência com tolerância para baixa largura de banda (se max_fps < 30)
        # Se max_camera_fps >= 30.0, nunca descarta frames por jitter temporal (stream 30+ FPS fluido nativo)
        if self.max_camera_fps < 30.0:
            min_interval = (1.0 / self.max_camera_fps) * 0.70
            if stats['msg_count'] > 0 and (now - stats['last_msg_time']) < min_interval:
                return

        dt = now - stats['last_msg_time'] if stats['last_msg_time'] > 0 else 0.033
        stats['last_msg_time'] = now
        stats['msg_count'] += 1
        if dt > 0.001:
            instant_fps = 1.0 / dt
            stats['fps'] = round(stats['fps'] * 0.85 + instant_fps * 0.15, 1)

        try:
            img_bytes = bytes(msg.data)
            
            # Alimenta o gravador nativo de vídeo
            if self.video_recorder.is_recording:
                self.video_recorder.add_jpeg_bytes(img_bytes, key)

            fmt = getattr(msg, 'format', 'jpeg').lower()
            is_png = 'png' in fmt
            mime = 'image/png' if is_png else 'image/jpeg'

            cv_img = None
            need_overlay_synth = (key == 'cam0' and self.active_cam == 'overlay' and self.latest_cloud_points is not None and (now - self.last_native_overlay_time) >= 3.0)
            if self.compress_and_resize or need_overlay_synth:
                try:
                    import cv2
                    import numpy as np
                    np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
                    cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if cv_img is not None and self.compress_and_resize:
                        h, w = cv_img.shape[:2]
                        if w > self.target_image_width:
                            new_h = int(h * (self.target_image_width / w))
                            cv_img = cv2.resize(cv_img, (self.target_image_width, new_h), interpolation=cv2.INTER_LINEAR)
                            success, encoded_img = cv2.imencode('.jpg', cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                            if success:
                                img_bytes = encoded_img.tobytes()
                                mime = 'image/jpeg'
                                is_png = False
                except Exception:
                    pass

            # Informações de resolução precisas
            cam_info = self.camera_info.get(key, {})
            cw = cam_info.get("width", 0)
            ch = cam_info.get("height", 0)
            if cv_img is not None:
                ch, cw = cv_img.shape[:2]

            with self.lock:
                # 1. Empacotamento binário de altíssimo desempenho (Zero-Copy)
                if self.stream_mode in ["binary", "both"]:
                    seq = self.frame_seq.get(key, 0) + 1
                    self.frame_seq[key] = seq
                    bframe = pack_camera_binary(
                        key,
                        img_bytes,
                        width=cw,
                        height=ch,
                        seq=seq,
                        timestamp=now,
                        is_png=is_png
                    )
                    self.pending_binary_frames[key] = bframe
                    if self.on_frame_ready:
                        try:
                            self.on_frame_ready(bframe)
                        except Exception:
                            pass

                # 2. Base64 legado (apenas se modo base64 ou both)
                if self.stream_mode in ["base64", "both"]:
                    b64_str = base64.b64encode(img_bytes).decode('utf-8')
                    self.pending_cameras[key] = f"data:{mime};base64,{b64_str}"

            # Síntese autônoma de LiDAR Overlay (amortecida a no máximo 5 Hz para zero impacto na CPU do robô)
            if key == 'cam0' and self.is_camera_active('overlay'):
                native_active = (now - self.last_native_overlay_time) < 3.0 if self.last_native_overlay_time > 0 else False
                if not native_active and self.latest_cloud_points is not None and (now - getattr(self, '_last_synth_time', 0.0) >= 0.2):
                    self._last_synth_time = now
                    if cv_img is None:
                        try:
                            import cv2
                            import numpy as np
                            np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
                            cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                        except Exception:
                            pass
                    if cv_img is not None:
                        self._synthesize_lidar_overlay(cv_img, self.latest_cloud_points)
        except Exception as e:
            self.record_error(e, f"process_compressed_image {key}")

    def process_raw_image(self, msg, topic_name: str):
        key = get_camera_key(topic_name)
        if not key:
            return

        now = time.time()
        if key == 'overlay':
            self.last_native_overlay_time = now

        if key not in self.camera_stats:
            self.camera_stats[key] = {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0}
        stats = self.camera_stats[key]

        if not self.is_camera_active(key):
            return

        if not self.has_connected_clients:
            stats['last_msg_time'] = now
            stats['msg_count'] += 1
            return

        # Cadência com tolerância para baixa largura de banda (se max_fps < 30)
        # Se max_camera_fps >= 30.0, nunca descarta frames por jitter temporal (stream 30+ FPS fluido nativo)
        if self.max_camera_fps < 30.0:
            min_interval = (1.0 / self.max_camera_fps) * 0.70
            if stats['msg_count'] > 0 and (now - stats['last_msg_time']) < min_interval:
                return

        dt = now - stats['last_msg_time'] if stats['last_msg_time'] > 0 else 0.033
        stats['last_msg_time'] = now
        stats['msg_count'] += 1
        if dt > 0.001:
            instant_fps = 1.0 / dt
            stats['fps'] = round(stats['fps'] * 0.85 + instant_fps * 0.15, 1)

        try:
            import cv2
            cv_img = self._raw_msg_to_cv2(msg)
            if cv_img is not None:
                if self.video_recorder.is_recording:
                    self.video_recorder.add_frame(cv_img, key)

                # Síntese autônoma de LiDAR Overlay antes de redimensionar
                if key == 'cam0' and self.is_camera_active('overlay'):
                    native_active = (now - self.last_native_overlay_time) < 3.0 if self.last_native_overlay_time > 0 else False
                    if not native_active and self.latest_cloud_points is not None:
                        self._synthesize_lidar_overlay(cv_img, self.latest_cloud_points)

                h, w = cv_img.shape[:2]
                if self.compress_and_resize and w > self.target_image_width:
                    new_h = int(h * (self.target_image_width / w))
                    cv_img = cv2.resize(cv_img, (self.target_image_width, new_h), interpolation=cv2.INTER_LINEAR)
                    h, w = new_h, self.target_image_width

                quality = self.jpeg_quality if self.compress_and_resize else 85
                success, encoded_img = cv2.imencode('.jpg', cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if success:
                    raw_bytes = encoded_img.tobytes()
                    with self.lock:
                        # 1. Empacotamento binário de alta performance
                        if self.stream_mode in ["binary", "both"]:
                            seq = self.frame_seq.get(key, 0) + 1
                            self.frame_seq[key] = seq
                            bframe = pack_camera_binary(
                                key,
                                raw_bytes,
                                width=w,
                                height=h,
                                seq=seq,
                                timestamp=now,
                                is_png=False
                            )
                            self.pending_binary_frames[key] = bframe
                            if self.on_frame_ready:
                                try:
                                    self.on_frame_ready(bframe)
                                except Exception:
                                    pass

                        # 2. Base64
                        if self.stream_mode in ["base64", "both"]:
                            b64_str = base64.b64encode(raw_bytes).decode('utf-8')
                            self.pending_cameras[key] = f"data:image/jpeg;base64,{b64_str}"
        except Exception as e:
            self.record_error(e, f"process_raw_image {key}")

    def process_camera_info(self, msg, topic_name: str):
        key = get_camera_key(topic_name)
        if not key:
            return
        with self.lock:
            info = {
                "width": int(msg.width),
                "height": int(msg.height)
            }
            if hasattr(msg, 'k') and len(msg.k) >= 9:
                info["fx"] = float(msg.k[0])
                info["fy"] = float(msg.k[4])
                info["cx"] = float(msg.k[2])
                info["cy"] = float(msg.k[5])
            self.camera_info[key] = info

    def pop_pending_binary_frames(self) -> List[bytes]:
        """Retorna os frames binários mais recentes para broadcast rápido, esvaziando a fila."""
        with self.lock:
            if not self.pending_binary_frames:
                return []
            frames = list(self.pending_binary_frames.values())
            self.pending_binary_frames.clear()
            return frames

    def extract_pending_cameras(self) -> Optional[Dict[str, str]]:
        with self.lock:
            # Em modo 'binary' puro, não envia base64 redundante no JSON para poupar CPU e banda
            if self.stream_mode == "binary" and not getattr(self, '_force_json_cameras', False):
                return None
            if not self.pending_cameras:
                return None
            res = self.pending_cameras.copy()
            self.pending_cameras.clear()
            return res

    def get_camera_info_payload(self) -> Dict[str, Dict[str, int]]:
        with self.lock:
            payload = {}
            for k, v in self.camera_info.items():
                if self.compress_and_resize and v.get("width", 0) > 0:
                    w = self.target_image_width
                    h = int(v["height"] * (w / v["width"])) if v["width"] > 0 else DEFAULT_IMAGE_HEIGHT
                    payload[k] = {"width": w, "height": h}
                else:
                    payload[k] = dict(v)
            return payload

    def get_camera_stats_payload(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        with self.lock:
            res = {}
            for k, v in self.camera_stats.items():
                is_active = (now - v['last_msg_time']) < 3.0 if v['last_msg_time'] > 0 else False
                res[k] = {
                    "active": is_active,
                    "msg_count": v['msg_count'],
                    "fps": v.get('fps', 0.0)
                }
            return res

    # --------------------------------------------------------------------------
    # Watchdog do Driver de Câmera
    # --------------------------------------------------------------------------
    def check_and_start_driver(self, has_publishers: bool = True):
        if not self.auto_start_driver:
            return

        now = time.time()
        last_attempt = getattr(self, '_last_driver_attempt', 0.0)
        if now - last_attempt < 15.0:
            return

        if self.driver_process is not None:
            ret = self.driver_process.poll()
            if ret is None:
                return
            else:
                self.log(f"⚠️ Driver de câmera parou (código: {ret}).", level="WARNING")
                self.driver_process = None

        if has_publishers:
            return

        try:
            pgrep = subprocess.run(["pgrep", "-f", "odin_ros_driver_rev1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            if pgrep.returncode == 0 and pgrep.stdout.strip():
                return
        except Exception:
            pass

        self._last_driver_attempt = now
        self.log("🚀 Iniciando driver odin_ros_driver_rev1...")
        try:
            domain = os.environ.get("ROS_DOMAIN_ID", "69")
            rmw = os.environ.get("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")
            launch_cmd = (
                "bash -c 'source /opt/ros/humble/setup.bash 2>/dev/null; "
                "for ws in ~/odin_ws ~/ros2_ws ~/scripts-ipq /app/applications /home/ubuntu/odin_ws /home/ubuntu/ros2_ws /home/ubuntu/scripts-ipq; do "
                "[ -f $ws/install/setup.bash ] && source $ws/install/setup.bash 2>/dev/null; done; "
                f"export ROS_DOMAIN_ID={domain}; export RMW_IMPLEMENTATION={rmw}; "
                "[ -f /etc/cyclonedds/cyclonedds.xml ] && export CYCLONEDDS_URI=file:///etc/cyclonedds/cyclonedds.xml; "
                "exec ros2 launch odin_ros_driver_rev1 driver.launch.py "
                "image_width:=1280 image_height:=1088 image_fps:=30 image_format:=mjpeg start_rviz:=false "
                "enable_reprojection:=true enable_colored_cloud:=true'"
            )
            log_file = open('/tmp/odin_driver.log', 'a')
            self.driver_process = subprocess.Popen(
                launch_cmd,
                shell=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            self.log(f"✅ Driver de câmera iniciado (PID: {self.driver_process.pid})")
        except Exception as e:
            self.record_error(e, "launch_camera_driver")

    def stop(self) -> bool:
        self.is_running = False
        if self.video_recorder.is_recording:
            self.video_recorder.stop()
        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None
        if self.driver_process and self.driver_process.poll() is None:
            try:
                import signal
                os.killpg(os.getpgid(self.driver_process.pid), signal.SIGTERM)
                self.driver_process.wait(timeout=3)
            except Exception:
                pass
            self.driver_process = None
        self.status = "STOPPED"
        self.log("Módulo de câmeras finalizado com sucesso.")
        return True

    def get_status(self) -> Dict[str, Any]:
        st = super().get_status()
        st.update({
            "active_tab": self.active_tab,
            "active_cam": self.active_cam,
            "target_width": self.target_image_width,
            "jpeg_quality": self.jpeg_quality,
            "recorder": self.video_recorder.get_status(),
            "camera_stats": {k: {"msgs": v["msg_count"]} for k, v in self.camera_stats.items()}
        })
        return st
