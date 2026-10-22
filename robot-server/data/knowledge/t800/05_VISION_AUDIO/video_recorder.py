#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gravador de Vídeo Nativo em Disco (Zero Loss Recording) e Servidor REST na porta 5050.
Localização: modules_dashboard/camera/video_recorder.py
Permite gravação contínua no robô em alta taxa de quadros (30 FPS) e download dos arquivos MP4.
"""

import os
import time
import json
import threading
import urllib.parse
from datetime import datetime
from typing import Optional, Any, Dict
import http.server
from socketserver import ThreadingMixIn

HTTP_RECORDER_PORT = 5050

import queue

class RobotVideoRecorder:
    """Grava fluxos de vídeo em alta definição direto no armazenamento local do robô sem bloquear threads de captura."""
    def __init__(self, output_dir: Optional[str] = None, logger: Optional[Any] = None):
        if output_dir is None:
            output_dir = os.path.expanduser("~/recordings")
        self.output_dir = output_dir
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception:
            self.output_dir = "/tmp/recordings"
            os.makedirs(self.output_dir, exist_ok=True)
            
        self.logger = logger
        self.is_recording = False
        self.writer = None
        self.current_filename = None
        self.current_filepath = None
        self.start_time = 0.0
        self.recorded_frames = 0
        self.lock = threading.Lock()
        self.target_fps = 30.0
        self.active_camera = "cam0"
        self.last_download_url = None
        
        # Fila assíncrona dedicada e thread trabalhadora (Zero Camera Jitter)
        self.frame_queue: queue.Queue = queue.Queue(maxsize=180)
        self.worker_thread: Optional[threading.Thread] = None
        self.worker_stop_event = threading.Event()

    def log(self, msg: str):
        if self.logger:
            self.logger(f"[RECORDER] {msg}")
        else:
            print(f"[RECORDER] {msg}")

    def _init_writer(self, width: int, height: int):
        import cv2
        codecs_to_try = [
            ('avc1', 'H.264 / AVC1 (Web Native)'),
            ('mp4v', 'MPEG-4 Part 2 (mp4v)')
        ]
        for fourcc_str, desc in codecs_to_try:
            try:
                fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
                writer = cv2.VideoWriter(self.current_filepath, fourcc, self.target_fps, (width, height))
                if writer is not None and writer.isOpened():
                    self.log(f"Codec de gravação: {desc} ({width}x{height} @ {self.target_fps} FPS)")
                    return writer
            except Exception:
                continue
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        return cv2.VideoWriter(self.current_filepath, fourcc, self.target_fps, (width, height))

    def _worker_loop(self):
        """Worker thread assíncrona que processa e grava os frames no disco sem afetar o streaming."""
        import cv2
        import numpy as np

        while not self.worker_stop_event.is_set() or not self.frame_queue.empty():
            try:
                item = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                kind, data = item
                frame = None
                if kind == "frame":
                    frame = data
                elif kind == "jpeg":
                    np_arr = np.frombuffer(data, dtype=np.uint8)
                    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None and frame.size > 0:
                    if self.writer is None:
                        h, w = frame.shape[:2]
                        self.writer = self._init_writer(w, h)

                    if self.writer is not None and self.writer.isOpened():
                        self.writer.write(frame)
                        self.recorded_frames += 1
            except Exception as e:
                self.log(f"Erro no worker de gravação: {e}")
            finally:
                self.frame_queue.task_done()

    def start(self, camera: str = "cam0", fps: float = 30.0) -> Dict[str, Any]:
        with self.lock:
            if self.is_recording:
                self._stop_internal()

            self.active_camera = camera or "cam0"
            self.target_fps = float(fps) if fps else 30.0
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_filename = f"rec_{self.active_camera}_{ts}.mp4"
            self.current_filepath = os.path.join(self.output_dir, self.current_filename)
            self.writer = None
            self.recorded_frames = 0
            self.start_time = time.time()
            self.is_recording = True

            # Limpa fila residual e inicia worker thread
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                    self.frame_queue.task_done()
                except Exception:
                    break

            self.worker_stop_event.clear()
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="VideoRecorderWorker")
            self.worker_thread.start()

            self.log(f"Gravação iniciada: {self.current_filename} ({self.active_camera} @ {self.target_fps} FPS)")
            return {
                "status": "recording",
                "camera": self.active_camera,
                "filename": self.current_filename
            }

    def add_frame(self, cv_frame, key: str):
        """Enfileira frame OpenCV de forma instantânea e sem bloquear I/O."""
        if not self.is_recording or cv_frame is None:
            return
        if key != self.active_camera and self.active_camera != "all":
            return
        try:
            self.frame_queue.put_nowait(("frame", cv_frame))
        except queue.Full:
            pass

    def add_jpeg_bytes(self, img_bytes: bytes, key: str):
        """Enfileira bytes brutos de JPEG sem decodificação imediata para máximo rendimento."""
        if not self.is_recording or not img_bytes:
            return
        if key != self.active_camera and self.active_camera != "all":
            return
        try:
            self.frame_queue.put_nowait(("jpeg", img_bytes))
        except queue.Full:
            pass

    def _stop_internal(self) -> Optional[Dict[str, Any]]:
        if not self.is_recording:
            return None
        self.is_recording = False
        
        # Sinaliza parada e aguarda esvaziar os frames pendentes para zero perda
        self.worker_stop_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=3.0)
            self.worker_thread = None

        if self.writer is not None:
            try:
                self.writer.release()
            except Exception:
                pass
            self.writer = None

        duration = time.time() - self.start_time
        self.last_download_url = f"/api/record/download/{self.current_filename}"
        self.log(f"Gravação finalizada: {self.current_filename} ({self.recorded_frames} frames gravados, {duration:.1f}s)")
        return {
            "status": "stopped",
            "filename": self.current_filename,
            "filepath": self.current_filepath,
            "duration": round(duration, 2),
            "frames": self.recorded_frames,
            "download_url": self.last_download_url
        }

    def stop(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self._stop_internal()

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            duration = round(time.time() - self.start_time, 1) if self.is_recording else 0.0
            return {
                "is_recording": self.is_recording,
                "camera": self.active_camera,
                "filename": self.current_filename,
                "duration": duration,
                "frames": self.recorded_frames,
                "download_url": self.last_download_url
            }


class ThreadingServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class RecorderHttpHandler(http.server.BaseHTTPRequestHandler):
    recorder: Optional[RobotVideoRecorder] = None
    scan_manager = None
    speech_callback = None

    def log_message(self, format, *args):
        pass

    def _send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors()
        self.end_headers()

    def do_POST(self):
        rec = RecorderHttpHandler.recorder
        if self.path.startswith('/api/record/start'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8', errors='ignore') if content_length > 0 else "{}"
            cam = "cam0"
            fps = 30.0
            try:
                data = json.loads(body)
                cam = data.get('camera', "cam0")
                fps = float(data.get('fps', 30.0))
            except Exception:
                pass
            res = rec.start(camera=cam, fps=fps) if rec else {"status": "error"}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._send_cors()
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return
        elif self.path.startswith('/api/record/stop'):
            res = rec.stop() if rec else {"status": "error"}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._send_cors()
            self.end_headers()
            self.wfile.write(json.dumps(res or {"status": "inactive"}).encode('utf-8'))
            return
        elif self.path.startswith('/speak'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8', errors='ignore')
            text = None
            try:
                data = json.loads(body)
                text = data.get('text')
            except Exception:
                pass
            if not text:
                try:
                    parsed = urllib.parse.parse_qs(body)
                    text = parsed.get('text', [None])[0]
                except Exception:
                    pass
            if text and RecorderHttpHandler.speech_callback:
                RecorderHttpHandler.speech_callback(text)
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self._send_cors()
                self.end_headers()
                self.wfile.write(b"Success")
                return
            self.send_response(400)
            self._send_cors()
            self.end_headers()
            self.wfile.write(b"No text provided")
        elif self.path.startswith('/api/scans/'):
            mgr = RecorderHttpHandler.scan_manager
            if not mgr:
                self.send_response(503)
                self._send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Scan manager unavailable"}')
                return
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8', errors='ignore') if content_length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            if '/delete' in self.path:
                parts = self.path.split('?')[0].split('/')
                scan_id = parts[3] if len(parts) >= 5 else data.get('scan_id', '')
                res = mgr.delete_scan(scan_id)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(json.dumps(res).encode('utf-8'))
                return
            self.send_response(400)
            self._send_cors()
            self.end_headers()
            self.wfile.write(b'{"error": "Unknown scan action"}')
            return
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        rec = RecorderHttpHandler.recorder
        mgr = RecorderHttpHandler.scan_manager
        if self.path.startswith('/api/record/status'):
            status = rec.get_status() if rec else {"is_recording": False}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._send_cors()
            self.end_headers()
            self.wfile.write(json.dumps(status).encode('utf-8'))
            return
        elif self.path.startswith('/api/record/download/'):
            filename = os.path.basename(urllib.parse.unquote(self.path[len('/api/record/download/'):]))
            if rec:
                filepath = os.path.join(rec.output_dir, filename)
                if os.path.exists(filepath) and os.path.isfile(filepath):
                    filesize = os.path.getsize(filepath)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(filesize))
                    self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                    self._send_cors()
                    self.end_headers()
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
            self.send_response(404)
            self._send_cors()
            self.end_headers()
            self.wfile.write(b"Arquivo de video nao encontrado")
            return
        elif self.path.startswith('/api/scans/'):
            if not mgr:
                self.send_response(503)
                self._send_cors()
                self.end_headers()
                self.wfile.write(b'{"error": "Scan manager unavailable"}')
                return

            if '/download' in self.path:
                parts = self.path.split('?')[0].split('/')
                # parts: ['', 'api', 'scans', '<scan_id>', 'download']
                scan_id = parts[3] if len(parts) >= 5 else ""
                parsed_url = urllib.parse.urlparse(self.path)
                q_params = urllib.parse.parse_qs(parsed_url.query)
                fmt = q_params.get('format', ['ply'])[0].lower()

                filepath = mgr.get_scan_file_path(scan_id, fmt)
                if filepath and os.path.exists(filepath):
                    filesize = os.path.getsize(filepath)
                    mime_type = "application/octet-stream"
                    filename = f"{scan_id}.{fmt}"
                    self.send_response(200)
                    self.send_header('Content-Type', mime_type)
                    self.send_header('Content-Length', str(filesize))
                    self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                    self._send_cors()
                    self.end_headers()
                    with open(filepath, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    return
                else:
                    self.send_response(404)
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(b'{"error": "Scan file not found"}')
                    return
            elif self.path.startswith('/api/scans/list'):
                scans = mgr.list_scans()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"scans": scans}).encode('utf-8'))
                return
            elif self.path.startswith('/api/scans/storage'):
                storage = mgr.get_storage_info()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({"storage": storage}).encode('utf-8'))
                return
        elif self.path.startswith('/health'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._send_cors()
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "video_recorder", "port": 5050}')
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self._send_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"service": "video_recorder", "endpoints": ["/api/record/start", "/api/record/stop", "/api/record/status", "/api/record/download/<file>"]}).encode('utf-8'))

def start_recorder_server(recorder: RobotVideoRecorder, speech_cb=None, host="0.0.0.0", port=HTTP_RECORDER_PORT):
    RecorderHttpHandler.recorder = recorder
    RecorderHttpHandler.speech_callback = speech_cb
    try:
        httpd = ThreadingServer((host, port), RecorderHttpHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd
    except Exception as e:
        print(f"[RECORDER] Falha ao iniciar servidor HTTP na porta {port}: {e}")
        return None
