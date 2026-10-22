#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciador e Supervisor do Módulo de Fala (Speech Manager).
Localização: modules_dashboard/speech/speech_manager.py
Responsável pelo ciclo de vida do subprocesso speech_server.py, tópicos ROS 2 e chamadas HTTP.
"""

import os
import sys
import time
import json
import threading
import subprocess
import urllib.request
from typing import Optional, Any, Dict
from modules_dashboard.common.base_module import BaseModule

HTTP_SPEECH_PORT = int(os.environ.get("ARCANJO_SPEECH_PORT", "5100"))

class SpeechManager(BaseModule):
    """Gerencia a inicialização, watchdog e despacho de falas para o speech_server.py."""
    def __init__(self, ros_node=None, logger: Optional[Any] = None):
        super().__init__("speech", logger)
        self.ros_node = ros_node
        self.process = None
        self.launch_lock = threading.Lock()
        self.speech_publisher = None
        self.speech_subscriber = None
        self.server_online = False
        self.speech_count = 0

    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if self.ros_node:
            try:
                from std_msgs.msg import String
                self.speech_publisher = self.ros_node.create_publisher(String, '/robot/speech', 10)
                self.speech_subscriber = self.ros_node.create_subscription(
                    String, '/robot/speak', self._on_robot_speak_msg, 10
                )
                self.log("Tópicos ROS 2 /robot/speech e /robot/speak registrados.")
            except Exception as e:
                self.record_error(e, "init_ros_speech_topics")
                
        self.is_initialized = True
        self.status = "INITIALIZED"
        return True

    def _on_robot_speak_msg(self, msg):
        if msg and getattr(msg, 'data', None):
            self.speak_text(msg.data.strip())

    def start(self) -> bool:
        self.is_running = True
        self.start_time = time.time()
        self.launch_server()
        self.status = "RUNNING" if self.server_online else "DEGRADED"
        return True

    def launch_server(self) -> bool:
        """Inicia o subprocesso speech_server.py com checagem de saúde na porta {HTTP_SPEECH_PORT}."""
        with self.launch_lock:
            if self.process is not None and self.process.poll() is None:
                return self.is_server_alive()
            if not self.is_running:
                return False
            import socket
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", 5100))
                except OSError:
                    self.log("Porta 5100 ocupada; serviço externo preservado", level="WARNING")
                    return False
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "speech_server.py")
            try:
                from pathlib import Path
                log_dir = Path(os.environ.get("T800_STATE_DIR", ".state")) / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                with (log_dir / "speech.log").open("a") as log_file:
                    self.process = subprocess.Popen(
                        [sys.executable, script_path], cwd=str(Path(__file__).resolve().parents[2]),
                        stdout=log_file, stderr=subprocess.STDOUT)
            except Exception as exc:
                self.record_error(exc, "launch")
                return False
        try:
            self.log(f"Iniciando speech_server na porta {HTTP_SPEECH_PORT} (PID: {self.process.pid})...")

            # Aguarda inicialização ativa
            for _ in range(15):
                time.sleep(0.2)
                if self.process.poll() is not None:
                    break
                if self.is_server_alive():
                    self.server_online = True
                    self.log(f"✅ speech_server está ONLINE na porta {HTTP_SPEECH_PORT}!")
                    return True

            self.server_online = False
            self.log(f"⚠️ speech_server não respondeu na porta {HTTP_SPEECH_PORT} dentro do tempo limite.", level="WARNING")
            return False
        except Exception as e:
            self.record_error(e, "launch_speech_server")
            return False

    def is_server_alive(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            return False
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{HTTP_SPEECH_PORT}/health")
            with urllib.request.urlopen(req, timeout=0.4) as resp:
                return resp.status == 200
        except Exception:
            return False

    def check_watchdog(self):
        """Watchdog periódico não-bloqueante chamado pelo orquestrador."""
        if not self.is_running:
            return
        now = time.time()
        last_attempt = getattr(self, '_last_launch_attempt', 0.0)
        if now - last_attempt < 15.0:
            return

        should_relaunch = False
        if self.process is not None and self.process.poll() is not None:
            self.log("⚠️ Processo speech_server parou inesperadamente. Relançando em background...", level="WARNING")
            should_relaunch = True
        elif not self.is_server_alive():
            should_relaunch = True

        if should_relaunch:
            self._last_launch_attempt = now
            threading.Thread(target=self.launch_server, daemon=True).start()

    def speak_text(self, text: str, voice: str = "pt-BR-AntonioNeural", speed: str = "+20%"):
        clean_text = text.strip() if text else ""
        if not clean_text:
            return

        self.speech_count += 1
        self.log(f"Falando ({self.speech_count}): '{clean_text}'")

        # 1. Publica no ROS 2 se disponível
        if self.speech_publisher:
            try:
                from std_msgs.msg import String
                msg = String()
                msg.data = clean_text
                self.speech_publisher.publish(msg)
            except Exception as e:
                self.record_error(e, "publish_robot_speech")

        # 2. Despacha requisição HTTP assíncrona para o speech_server.py
        def _send_http():
            try:
                payload = json.dumps({"text": clean_text, "voice": voice, "rate": speed}).encode('utf-8')
                req = urllib.request.Request(
                    f"http://127.0.0.1:{HTTP_SPEECH_PORT}/speak",
                    data=payload,
                    headers={'Content-Type': 'application/json'}
                )
                if self.process is None or self.process.poll() is not None:
                    raise RuntimeError("Serviço Arcanjo indisponível")
                with urllib.request.urlopen(req, timeout=2.0) as response:
                    response.read()
            except Exception as e:
                self.record_error(e, "http_speak_request")

        threading.Thread(target=_send_http, daemon=True).start()

    def play_sound(self, name: str = "connect"):
        """Toca sinal sonoro (ex: 'connect', 'disconnect') sem síntese vocal."""
        clean_name = str(name).strip().lower()
        self.log(f"🔔 Sinal sonoro: '{clean_name}'")

        def _send_sound():
            try:
                payload = json.dumps({"sound": clean_name}).encode('utf-8')
                req = urllib.request.Request(
                    f"http://127.0.0.1:{HTTP_SPEECH_PORT}/sound/{clean_name}",
                    data=payload,
                    headers={'Content-Type': 'application/json'}
                )
                try:
                    urllib.request.urlopen(req, timeout=2.0)
                except Exception:
                    # Se speech_server ainda não respondeu, tenta fallback local
                    try:
                        from modules_dashboard.speech.speech_server import play_sound_cue
                        play_sound_cue(clean_name)
                    except Exception:
                        pass
            except Exception as e:
                self.record_error(e, "play_sound")

        threading.Thread(target=_send_sound, daemon=True).start()

    def stop(self) -> bool:
        self.is_running = False
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.status = "STOPPED"
        self.log("SpeechManager encerrado.")
        return True

    def get_status(self) -> Dict[str, Any]:
        st = super().get_status()
        st.update({
            "server_online": self.server_online,
            "speech_count": self.speech_count,
            "pid": self.process.pid if self.process and self.process.poll() is None else None
        })
        return st
