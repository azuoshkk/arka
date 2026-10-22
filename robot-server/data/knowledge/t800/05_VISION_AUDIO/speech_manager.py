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

HTTP_SPEECH_PORT = 5000

class SpeechManager(BaseModule):
    """Gerencia a inicialização, watchdog e despacho de falas para o speech_server.py."""
    def __init__(self, ros_node=None, logger: Optional[Any] = None):
        super().__init__("speech", logger)
        self.ros_node = ros_node
        self.process = None
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
        """Inicia o subprocesso speech_server.py com checagem de saúde na porta 5000."""
        if self.is_server_alive():
            self.server_online = True
            return True

        possible_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "speech_server.py"),
            os.path.expanduser("~/scripts-ipq/beniFiles/speech_server.py"),
            "/home/ubuntu/scripts-ipq/beniFiles/speech_server.py"
        ]

        script_path = next((p for p in possible_paths if os.path.exists(p)), None)
        if not script_path:
            self.log("speech_server.py não encontrado!", level="WARNING")
            return False

        try:
            log_file = open('/tmp/speech_server.log', 'w')
            script_dir = os.path.dirname(script_path) or "."
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            env = os.environ.copy()
            env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"

            self.process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=script_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            self.log(f"Iniciando speech_server na porta {HTTP_SPEECH_PORT} (PID: {self.process.pid})...")

            # Aguarda inicialização ativa
            for _ in range(15):
                time.sleep(0.2)
                if self.process.poll() is not None:
                    break
                if self.is_server_alive():
                    self.server_online = True
                    self.log("✅ speech_server está ONLINE na porta 5000!")
                    return True

            self.server_online = False
            self.log("⚠️ speech_server não respondeu na porta 5000 dentro do tempo limite.", level="WARNING")
            return False
        except Exception as e:
            self.record_error(e, "launch_speech_server")
            return False

    def is_server_alive(self) -> bool:
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
                try:
                    urllib.request.urlopen(req, timeout=3.0)
                except Exception:
                    # Falha: relança servidor e tenta mais uma vez
                    self.launch_server()
                    time.sleep(0.3)
                    urllib.request.urlopen(req, timeout=3.0)
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
            "server_online": self.is_server_alive(),
            "speech_count": self.speech_count,
            "pid": self.process.pid if self.process and self.process.poll() is None else None
        })
        return st
