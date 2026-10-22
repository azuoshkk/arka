#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Captura e Streaming de Áudio do Microfone Físico (AIUI-USB-MC / ALSA).
Localização: modules_dashboard/audio/audio_service.py
Responsável por capturar PCM 16kHz Mono em tempo real e calcular nível de volume RMS.
"""

import os
import time
import math
import struct
import threading
import subprocess
from typing import Optional, Dict, Any, Tuple
from modules_dashboard.common.base_module import BaseModule

# Configurações padrão do hardware de áudio do T800
DEFAULT_AUDIO_DEVICE = "plughw:1,0"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_CHUNK_SIZE = 1600  # ~50ms de áudio em 16kHz S16_LE

class AudioCaptureService(BaseModule):
    """Serviço de captura de áudio do microfone do robô usando ALSA/arecord."""
    def __init__(
        self,
        device: str = DEFAULT_AUDIO_DEVICE,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        logger: Optional[Any] = None
    ):
        super().__init__("audio", logger)
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        
        self.process = None
        self.thread = None
        self.lock = threading.Lock()
        self.latest_chunk = b""
        self.volume_level = 0
        self.device_used = None

    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        self.is_initialized = True
        self.status = "INITIALIZED"
        self.log(f"Inicializado com dispositivo alvo: {self.device}")
        return True

    def start(self) -> bool:
        if self.is_running:
            return True
        self.is_running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        self.status = "RUNNING"
        self.log("Thread de captura de microfone iniciada.")
        return True

    def _capture_loop(self):
        candidate_configs = [
            {"device": self.device, "rate": 16000, "rec_channels": 1},
            {"device": self.device, "rate": 16000, "rec_channels": 2},
            {"device": self.device, "rate": 48000, "rec_channels": 2},
            {"device": "plughw:1,0", "rate": 16000, "rec_channels": 1},
            {"device": "hw:1,0", "rate": 16000, "rec_channels": 1},
            {"device": "plughw:AIUIUSBMC", "rate": 16000, "rec_channels": 2},
            {"device": "default", "rate": 16000, "rec_channels": 1},
            {"device": "default", "rate": 16000, "rec_channels": 2},
        ]

        for config in candidate_configs:
            if not self.is_running:
                break

            dev = config["device"]
            rate = config["rate"]
            rec_ch = config["rec_channels"]
            read_size = self.chunk_size * rec_ch * (rate // 16000)

            cmd = [
                "arecord",
                "-D", dev,
                "-f", "S16_LE",
                "-r", str(rate),
                "-c", str(rec_ch),
                "-t", "raw",
                "-q"
            ]

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=read_size
                )
                time.sleep(0.15)
                if self.process.poll() is not None:
                    continue

                self.device_used = f"{dev} ({rate}Hz, {rec_ch}ch)"
                self.log(f"Microfone conectado: {self.device_used}")

                while self.is_running and self.process.poll() is None:
                    raw_data = self.process.stdout.read(read_size)
                    if not raw_data:
                        break

                    num_shorts = len(raw_data) // 2
                    if num_shorts == 0:
                        continue

                    shorts = struct.unpack(f"<{num_shorts}h", raw_data[:num_shorts * 2])
                    rate_step = max(1, rate // 16000)
                    step = rec_ch * rate_step
                    mono_shorts = shorts[0::step]

                    # Cálculo do nível de volume RMS (0-100)
                    sum_sq = sum(s * s for s in mono_shorts)
                    rms = math.sqrt(sum_sq / (len(mono_shorts) or 1))
                    vol = min(100, int((rms / 32768.0) * 400))
                    mono_pcm = struct.pack(f"<{len(mono_shorts)}h", *mono_shorts)

                    with self.lock:
                        self.latest_chunk += mono_pcm
                        if len(self.latest_chunk) > self.chunk_size * 50:
                            self.latest_chunk = self.latest_chunk[-self.chunk_size * 50:]
                        self.volume_level = vol

                if not self.is_running:
                    break
            except Exception as e:
                self.record_error(e, f"arecord com {dev}")

        self.stop()

    def get_and_clear_audio(self) -> Tuple[bytes, int]:
        """Retorna os bytes PCM capturados e zera o buffer."""
        with self.lock:
            data = self.latest_chunk
            self.latest_chunk = b""
            vol = self.volume_level
            return data, vol

    def stop(self) -> bool:
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=0.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.status = "STOPPED"
        return True

    def get_status(self) -> Dict[str, Any]:
        st = super().get_status()
        st.update({
            "device_configured": self.device,
            "device_used": self.device_used,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "volume_level": self.volume_level
        })
# Alias de conveniência
AudioService = AudioCaptureService

if __name__ == "__main__":
    svc = AudioCaptureService()
    svc.initialize()
    svc.start()
    print("Capturando áudio por 3 segundos...")
    for _ in range(6):
        time.sleep(0.5)
        pcm, vol = svc.get_and_clear_audio()
        print(f"Bytes: {len(pcm)} | Volume: {vol}%")
    svc.stop()
