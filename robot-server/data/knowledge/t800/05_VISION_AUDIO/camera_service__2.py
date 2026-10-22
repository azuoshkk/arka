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
import threading
import subprocess
from typing import Optional, Dict, Any
from modules_dashboard.common.base_module import BaseModule
from modules_dashboard.camera.video_recorder import RobotVideoRecorder, start_recorder_server, HTTP_RECORDER_PORT

# Configurações padrão
DEFAULT_CAMERA_FPS = 12.0
DEFAULT_IMAGE_WIDTH = 640
DEFAULT_IMAGE_HEIGHT = 480
DEFAULT_JPEG_QUALITY = 85

def get_camera_key(topic_name: str) -> Optional[str]:
    """Mapeia o nome do tópico ROS 2 para a chave do dashboard ('cam0', 'cam1', 'gray', 'overlay')."""
    t_lower = topic_name.lower()
    if 'reprojection' in t_lower or 'overlay' in t_lower:
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
        
        # Configurações dinâmicas de renderização
        self.active_tab = "overview"
        self.active_cam = "cam0"
        self.compress_and_resize = False
        self.target_image_width = DEFAULT_IMAGE_WIDTH
        self.jpeg_quality = DEFAULT_JPEG_QUALITY
        self.max_camera_fps = DEFAULT_CAMERA_FPS
        
        # Buffers de quadros e metadados
        self.binary_transport = False
        self.pending_cameras: Dict[str, str] = {}
        self.camera_info: Dict[str, Dict[str, Any]] = {}
        self.camera_stats: Dict[str, Dict[str, Any]] = {
            "cam0": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "cam1": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "gray": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0},
            "overlay": {"msg_count": 0, "last_msg_time": 0.0, "fps": 0.0}
        }
        self.has_connected_clients = True
        self.latest_cloud_points = None
        self.last_native_overlay_time = 0.0

    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if context:
            self.auto_start_driver = context.get("auto_start_driver", self.auto_start_driver)
            self.max_camera_fps = context.get("max_fps", self.max_camera_fps)
        
        # Inicia o servidor HTTP de gravação na porta 5050
        speech_cb = context.get("speech_callback") if context else None
        if (context or {}).get("recorder_enabled", True):
            self.http_server = start_recorder_server(self.video_recorder, speech_cb=speech_cb, host="127.0.0.1", port=HTTP_RECORDER_PORT)
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

    def set_camera_config(self, target_width: Optional[int] = None, jpeg_quality: Optional[int] = None):
        changed = False
        with self.lock:
            if isinstance(target_width, int) and target_width > 0 and target_width != self.target_image_width:
                self.target_image_width = target_width
                changed = True
            if isinstance(jpeg_quality, int) and 0 < jpeg_quality <= 100 and jpeg_quality != self.jpeg_quality:
                self.jpeg_quality = jpeg_quality
                changed = True
        if changed:
            self.log(f"Configuração atualizada: Width={self.target_image_width}, Quality={self.jpeg_quality}%")

    def set_active_view(self, active_tab: Optional[str] = None, active_cam: Optional[str] = None):
        changed = False
        with self.lock:
            if active_tab and active_tab != self.active_tab:
                self.active_tab = active_tab
                changed = True
            if active_cam and active_cam != self.active_cam:
                self.active_cam = active_cam
                changed = True
        if changed:
            self.log(f"Visualização ativa: Tab={self.active_tab}, Cam={self.active_cam}")

    def is_camera_active(self, key: str) -> bool:
        """Determina se uma câmera deve ser decodificada e enviada no ciclo atual."""
        if hasattr(self, "wanted_keys"):
            return key in self.wanted_keys
        if self.video_recorder.is_recording:
            return True
        if self.active_cam == "all":
            return True
        if key == self.active_cam:
            return True
        if self.active_cam == "stereo" and key in ["cam0", "cam1"]:
            return True
        # Aba de Mapeamento 3D / PointCloud: PiP suporta CAM0 e LiDAR Overlay simultaneamente
        if self.active_tab in ["pointcloud", "map3d", "map_3d"] and key in ["cam0", "overlay"]:
            return True
        # Abas de Visão e Cockpit: envia apenas a câmera selecionada.
        if self.active_tab in ["overview", "perception"] and key == self.active_cam:
            return True
        return False

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

            # Renderiza pontos com raio expandido para máxima visibilidade
            for du in (-1, 0, 1):
                for dv in (-1, 0, 1):
                    uu = np.clip(u + du, 0, w - 1)
                    vv = np.clip(v + dv, 0, h - 1)
                    overlay[vv, uu] = colors

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

            quality = self.jpeg_quality if self.compress_and_resize else 80
            success, encoded_img = cv2.imencode('.jpg', overlay, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if success:
                b64_str = base64.b64encode(encoded_img.tobytes()).decode('utf-8')
                data_url = f"data:image/jpeg;base64,{b64_str}"
                with self.lock:
                    self.pending_cameras['overlay'] = data_url
                    self.camera_stats['overlay']['msg_count'] += 1
                    self.camera_stats['overlay']['last_msg_time'] = time.time()
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

        stats = self.camera_stats[key]
        
        # Otimização: ignora conversão se a câmera não for a ativa no momento
        if not self.is_camera_active(key):
            return

        # Otimização: ignora se nenhum dashboard estiver conectado
        if not self.has_connected_clients:
            stats['last_msg_time'] = now
            stats['msg_count'] += 1
            return

        target_fps = 15.0 if self.active_cam == "stereo" else self.max_camera_fps
        if now - stats['last_msg_time'] < (0.9 / target_fps) and stats['msg_count'] > 0:
            return

        stats['last_msg_time'] = now
        stats['msg_count'] += 1

        try:
            img_bytes = bytes(msg.data)
            
            # Alimenta o gravador nativo de vídeo
            if self.video_recorder.is_recording:
                self.video_recorder.add_jpeg_bytes(img_bytes, key)

            fmt = getattr(msg, 'format', 'jpeg').lower()
            mime = 'image/png' if 'png' in fmt else 'image/jpeg'

            cv_img = None
            if self.compress_and_resize or (key == 'cam0' and self.is_camera_active('overlay')):
                try:
                    import cv2
                    import numpy as np
                    np_arr = np.frombuffer(img_bytes, dtype=np.uint8)
                    cv_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    if cv_img is not None and self.compress_and_resize:
                        h, w = cv_img.shape[:2]
                        if w > self.target_image_width:
                            new_h = int(h * (self.target_image_width / w))
                            cv_img = cv2.resize(cv_img, (self.target_image_width, new_h), interpolation=cv2.INTER_AREA)
                        success, encoded_img = cv2.imencode('.jpg', cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
                        if success:
                            img_bytes = encoded_img.tobytes()
                            mime = 'image/jpeg'
                except Exception:
                    pass

            if self.binary_transport:
                from platform_runtime.video import pack_frame
                data_url = pack_frame(key, mime, img_bytes)
            else:
                b64_str = base64.b64encode(img_bytes).decode('utf-8')
                data_url = f"data:{mime};base64,{b64_str}"

            with self.lock:
                self.pending_cameras[key] = data_url

            # Síntese autônoma de LiDAR Overlay quando não houver stream nativo ativo
            if key == 'cam0' and self.is_camera_active('overlay'):
                native_active = (now - self.last_native_overlay_time) < 3.0 if self.last_native_overlay_time > 0 else False
                if not native_active and self.latest_cloud_points is not None:
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

        stats = self.camera_stats[key]

        if not self.is_camera_active(key):
            return

        if not self.has_connected_clients:
            stats['last_msg_time'] = now
            stats['msg_count'] += 1
            return

        if now - stats['last_msg_time'] < (1.0 / self.max_camera_fps) and stats['msg_count'] > 0:
            return

        stats['last_msg_time'] = now
        stats['msg_count'] += 1

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
                    cv_img = cv2.resize(cv_img, (self.target_image_width, new_h), interpolation=cv2.INTER_AREA)

                quality = self.jpeg_quality if self.compress_and_resize else 80
                success, encoded_img = cv2.imencode('.jpg', cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if success:
                    b64_str = base64.b64encode(encoded_img.tobytes()).decode('utf-8')
                    data_url = f"data:image/jpeg;base64,{b64_str}"
                    with self.lock:
                        self.pending_cameras[key] = data_url
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

    def extract_pending_cameras(self) -> Optional[Dict[str, str]]:
        with self.lock:
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

        self.log("🚀 Iniciando driver odin_ros_driver_rev1...")
        try:
            if time.monotonic() - getattr(self, '_driver_attempt', -60) < 60:
                return
            self._driver_attempt = time.monotonic()
            from pathlib import Path
            log_dir = Path(os.environ.get('T800_STATE_DIR', '.state')) / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / 'odin.log').open('a') as log_file:
                self.driver_process = subprocess.Popen([
                    'ros2', 'run', 'odin_ros_driver_rev1', 'odin_ros_driver_node',
                    '--ros-args', '-p', 'operating_mode:=normal',
                    '-p', 'image_width:=1280', '-p', 'image_height:=1088',
                    '-p', 'image_fps:=30', '-p', 'image_format:=mjpeg'],
                    stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
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
