#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Fala e Síntese Vocal (TTS) do Robô T800.
Localização: modules_dashboard/speech/speech_server.py
Servidor HTTP Flask na porta 5000 com Edge-TTS neural, cache em RAM (/dev/shm) e ALSA.
"""

import os
import sys
import time
import hashlib
import asyncio
import wave
import struct
import math
import subprocess
import threading
import logging
try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    Flask = None
    request = None
    jsonify = lambda data, status=200: (data, status)
    class _MockApp:
        def route(self, *args, **kwargs):
            return lambda fn: fn
        def after_request(self, fn):
            return fn
        def run(self, *args, **kwargs):
            pass

# ==========================================================
# Configuração de Logs
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [T800-SPEECH] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("T800_Speech")

app = Flask(__name__) if FLASK_AVAILABLE else _MockApp()

# Configurações de Voz
VOICE = "pt-BR-AntonioNeural"
RATE = "+20%"

# Diretório de Cache de Alta Velocidade Exclusivo Voz Masculina Antonio (em RAM /dev/shm ou /tmp)
CACHE_DIR = "/dev/shm/t800_tts_cache_antonio" if os.path.exists("/dev/shm") else "/tmp/t800_tts_cache_antonio"
os.makedirs(CACHE_DIR, exist_ok=True)

# Diretório de Sinais Sonoros (WAV) de Conexão e Desconexão
SOUND_DIR = "/dev/shm/t800_sound_cues" if os.path.exists("/dev/shm") else "/tmp/t800_sound_cues"
os.makedirs(SOUND_DIR, exist_ok=True)

SOUND_CONNECT_PATH = os.path.join(SOUND_DIR, "connect.wav")
SOUND_DISCONNECT_PATH = os.path.join(SOUND_DIR, "disconnect.wav")

def generate_tone_wav(filepath: str, tones: list, sample_rate: int = 44100, master_volume: float = 0.35):
    """
    tones: lista de tuplas (frequência_hz, duração_seg, amplitude_relativa)
    Gera arquivo WAV senoidal com envelopes suaves de ataque e decaimento.
    """
    samples = []
    for freq, duration, amp in tones:
        num_samples = int(sample_rate * duration)
        if num_samples <= 0:
            continue
        attack_samples = min(int(sample_rate * 0.008), num_samples // 4)
        release_samples = min(int(sample_rate * 0.015), num_samples // 4)
        for i in range(num_samples):
            gain = 1.0
            if i < attack_samples:
                gain = i / float(attack_samples)
            elif i > num_samples - release_samples:
                gain = (num_samples - i) / float(release_samples)
            t = float(i) / sample_rate
            val = math.sin(2.0 * math.pi * freq * t) * amp * gain * master_volume
            samples.append(int(max(-32767, min(32767, val * 32767))))

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with wave.open(filepath, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack(f'<{len(samples)}h', *samples))

def ensure_sound_cues():
    """Garante a existência dos arquivos WAV dos sinais sonoros pré-sintetizados."""
    try:
        if not os.path.exists(SOUND_CONNECT_PATH) or os.path.getsize(SOUND_CONNECT_PATH) < 100:
            # Tom ascendente de conexão: D5 (587.33 Hz, 70ms) -> A5 (880.00 Hz, 120ms)
            generate_tone_wav(SOUND_CONNECT_PATH, [(587.33, 0.07, 0.8), (880.00, 0.12, 1.0)])
        
        if not os.path.exists(SOUND_DISCONNECT_PATH) or os.path.getsize(SOUND_DISCONNECT_PATH) < 100:
            # Tom descendente de desconexão: A5 (880.00 Hz, 70ms) -> C5 (523.25 Hz, 140ms)
            generate_tone_wav(SOUND_DISCONNECT_PATH, [(880.00, 0.07, 1.0), (523.25, 0.14, 0.8)])
    except Exception as e:
        logger.warning(f"Erro ao gerar sinais sonoros WAV: {e}")

# Pré-gera os arquivos de sinal sonoro no boot
ensure_sound_cues()

# Limpa resquícios de caches legados para garantir integridade
for _legacy in ["/dev/shm/t800_tts_cache", "/tmp/t800_tts_cache"]:
    if os.path.exists(_legacy) and _legacy != CACHE_DIR:
        try:
            import shutil
            shutil.rmtree(_legacy, ignore_errors=True)
        except Exception:
            pass

# Controle de Concorrência
current_player_process = None
player_lock = threading.Lock()

# Event Loop Assíncrono Persistente em Thread Dedicada
async_loop = asyncio.new_event_loop()

def _run_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop_thread = threading.Thread(target=_run_event_loop, args=(async_loop,), daemon=True)
loop_thread.start()

# ==========================================================
# CORS Middleware
# ==========================================================
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

# ==========================================================
# Desmutar Canais ALSA e PulseAudio
# ==========================================================
def unmute_alsa_async():
    def _unmute():
        commands = [
            ["amixer", "-c", "1", "sset", "Speaker", "100%", "unmute"],
            ["amixer", "-c", "1", "sset", "Master", "100%", "unmute"],
            ["amixer", "-c", "0", "sset", "Master", "100%", "unmute"],
            ["amixer", "-c", "0", "sset", "Speaker", "100%", "unmute"],
            ["amixer", "sset", "Master", "100%", "unmute"],
            ["amixer", "sset", "Speaker", "100%", "unmute"],
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"]
        ]
        for cmd in commands:
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.3)
            except Exception:
                pass
    threading.Thread(target=_unmute, daemon=True).start()

# Executa desmutador inicial no boot
unmute_alsa_async()

# ==========================================================
# Helper de Interrupção
# ==========================================================
def stop_current_playback():
    global current_player_process
    with player_lock:
        if current_player_process and current_player_process.poll() is None:
            try:
                current_player_process.terminate()
                current_player_process.kill()
            except Exception:
                pass
            current_player_process = None

# ==========================================================
# Detecção e Seleção do Melhor Player de Áudio
# ==========================================================
_WORKING_PLAYER_CMD = None

def detect_best_player():
    """Detecta o método de reprodução funcional uma única vez no boot."""
    global _WORKING_PLAYER_CMD
    candidates = [
        ["mpg123", "-a", "default"],
        ["mpg123", "-a", "pulse"],
        ["mpg123"],
        ["paplay"],
        ["play"],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
        ["mpg123", "-a", "plughw:1,0"],
        ["mpg123", "-a", "hw:1,0"]
    ]
    
    for cmd in candidates:
        bin_name = cmd[0]
        if subprocess.call(["which", bin_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            _WORKING_PLAYER_CMD = cmd
            logger.info(f"🎯 Dispositivo de áudio configurado: {' '.join(cmd)}")
            return cmd
    
    _WORKING_PLAYER_CMD = ["mpg123"]
    return _WORKING_PLAYER_CMD

detect_best_player()

# ==========================================================
# Motor de Reprodução Instantânea (Cache 0ms)
# ==========================================================
def play_cached_file(file_path: str):
    """Toca arquivo de áudio instantaneamente com o motor verificado."""
    global current_player_process, _WORKING_PLAYER_CMD
    stop_current_playback()
    
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 50:
        logger.error(f"❌ Arquivo de áudio inválido: {file_path}")
        return

    # Se for arquivo WAV (ex: sinais sonoros do robô), prioriza aplay/paplay/afplay
    if file_path.lower().endswith(".wav"):
        wav_cmds = [
            ["aplay", "-q", file_path],
            ["paplay", file_path],
            ["play", "-q", file_path],
            ["afplay", file_path],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", file_path]
        ]
        for cmd in wav_cmds:
            if subprocess.call(["which", cmd[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                try:
                    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with player_lock:
                        current_player_process = proc
                    logger.info(f"🔔 [SOUND CUE] Reproduzindo sinal sonoro: {os.path.basename(file_path)}")
                    return
                except Exception:
                    continue
        logger.warning(f"Nenhum player compatível encontrado para reproduzir WAV: {file_path}")
        return

    primary_cmd = list(_WORKING_PLAYER_CMD) + [file_path] if _WORKING_PLAYER_CMD else ["mpg123", "-a", "default", file_path]
    
    try:
        proc = subprocess.Popen(primary_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with player_lock:
            current_player_process = proc
        logger.info(f"▶️ [CACHE HIT] Reproduzindo: {os.path.basename(file_path)}")
        return
    except Exception as e:
        logger.warning(f"Erro no player primário: {e}")

    fallback_cmds = [
        ["mpg123", "-a", "default", file_path],
        ["mpg123", "-a", "pulse", file_path],
        ["mpg123", "-a", "plughw:1,0", file_path],
        ["mpg123", "-a", "hw:1,0", file_path],
        ["mpg123", file_path],
        ["aplay", file_path],
        ["paplay", file_path]
    ]
    
    for cmd in fallback_cmds:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with player_lock:
                current_player_process = proc
            _WORKING_PLAYER_CMD = cmd[:-1]
            return
        except Exception:
            continue

def play_sound_cue(name: str) -> bool:
    """Toca sinal sonoro ('connect' ou 'disconnect')."""
    ensure_sound_cues()
    clean_name = str(name).strip().lower()
    if clean_name in ["connect", "connected", "online", "join"]:
        target = SOUND_CONNECT_PATH
    elif clean_name in ["disconnect", "disconnected", "offline", "leave"]:
        target = SOUND_DISCONNECT_PATH
    else:
        logger.warning(f"Sinal sonoro não reconhecido: '{name}'")
        return False

    play_cached_file(target)
    return True

def normalize_rate(rate_val) -> str:
    """Normaliza o valor de velocidade para o formato aceito pelo Edge-TTS (+20%, +0%, etc.)"""
    if not rate_val:
        return RATE
    rate_str = str(rate_val).strip()
    if rate_str.endswith("%"):
        return rate_str if rate_str.startswith(("+", "-")) else f"+{rate_str}"
    try:
        val = float(rate_str)
        pct = int(round((val - 1.0) * 100))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return RATE

def get_cache_filename(text: str, voice: str = VOICE, rate: str = RATE) -> str:
    clean = text.strip()
    norm_rate = normalize_rate(rate)
    key = f"{clean}_{VOICE}_{norm_rate}".encode('utf-8')
    cache_hash = hashlib.md5(key).hexdigest()
    return os.path.join(CACHE_DIR, f"{cache_hash}.mp3")

async def stream_and_cache(text: str, voice: str, rate: str, cache_file: str):
    """Transmite áudio via pipe mpg123 e armazena em cache RAM."""
    global current_player_process
    try:
        import edge_tts
    except ImportError:
        logger.error("Biblioteca 'edge_tts' não instalada.")
        return

    stop_current_playback()

    target_cmd = list(_WORKING_PLAYER_CMD) if _WORKING_PLAYER_CMD else ["mpg123", "-a", "default"]
    if target_cmd[0] == "mpg123":
        stream_cmd = ["mpg123", "-q"] + target_cmd[1:] + ["-"]
    else:
        stream_cmd = target_cmd + ["-"]

    proc = None
    try:
        proc = subprocess.Popen(stream_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            proc = subprocess.Popen(["mpg123", "-q", "-"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    with player_lock:
        current_player_process = proc

    audio_chunks = []
    communicate = edge_tts.Communicate(text=text, voice=VOICE, rate=rate)

    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                data = chunk["data"]
                audio_chunks.append(data)
                if proc and proc.stdin and proc.poll() is None:
                    try:
                        proc.stdin.write(data)
                        proc.stdin.flush()
                    except (BrokenPipeError, IOError):
                        break
    except Exception as e:
        logger.error(f"Erro no streaming Edge-TTS: {e}")
        try:
            esc = text.replace('"', '\\"').replace("'", "\\'")
            os.system(f'espeak -v pt-br+m3 -s 150 "{esc}" 2>/dev/null || espeak-ng -v pt-br+m3 -s 150 "{esc}" 2>/dev/null')
        except Exception:
            pass
    finally:
        if proc and proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass

    if audio_chunks:
        try:
            with open(cache_file, "wb") as f:
                for chunk in audio_chunks:
                    f.write(chunk)
        except Exception:
            pass

_last_requests = {}
_requests_lock = threading.Lock()

def process_speech_request(text: str, voice: str = VOICE, rate: str = RATE):
    clean_text = text.strip()
    if not clean_text:
        return

    now = time.time()
    with _requests_lock:
        if clean_text in _last_requests and (now - _last_requests[clean_text]) < 1.2:
            logger.info(f"⏭️ [DEDUP] Ignorado: '{clean_text[:40]}'")
            return
        _last_requests[clean_text] = now

    target_voice = VOICE
    target_rate = normalize_rate(rate)
    cache_file = get_cache_filename(clean_text, target_voice, target_rate)

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 100:
        logger.info(f"⚡ [CACHE HIT] '{clean_text[:50]}...'")
        play_cached_file(cache_file)
        return

    logger.info(f"🔊 [LIVE] '{clean_text[:50]}...'")
    asyncio.run_coroutine_threadsafe(
        stream_and_cache(clean_text, target_voice, target_rate, cache_file),
        async_loop
    )

def prewarm_cache():
    """Pré-aquecimento das frases comuns no startup."""
    quick_phrases = [
        "Sistema de voz online.",
        "Olá, eu sou o Arcanjo!",
        "Atenção: Robô em movimento.",
        "Por favor, libere a passagem.",
        "Inspeção concluída com sucesso.",
        "Retornando à base de recarga.",
        "Sim.",
        "Não.",
        "Comando recebido.",
        "Parando movimento.",
        "Movimento iniciado.",
        "Modo autônomo ativado.",
        "Modo manual ativado.",
        "Bateria baixa.",
        "Câmera ativada.",
        "Gravação iniciada.",
        "Gravação finalizada."
    ]
    
    async def _generate_all():
        try:
            import edge_tts
            for phrase in quick_phrases:
                fpath = get_cache_filename(phrase, VOICE, RATE)
                if not os.path.exists(fpath) or os.path.getsize(fpath) < 100:
                    try:
                        comm = edge_tts.Communicate(text=phrase, voice=VOICE, rate=RATE)
                        await comm.save(fpath)
                    except Exception:
                        pass
            logger.info("⚡ Pré-aquecimento de frases frequentes concluído!")
        except Exception:
            pass

    asyncio.run_coroutine_threadsafe(_generate_all(), async_loop)

threading.Thread(target=prewarm_cache, daemon=True).start()

# ==========================================================
# Rotas HTTP Flask
# ==========================================================
@app.route('/speak', methods=['POST', 'GET', 'OPTIONS'])
def speak():
    if request.method == 'OPTIONS':
        return '', 200

    text = None
    voice = VOICE
    rate = RATE

    if request.is_json:
        data = request.get_json(silent=True) or {}
        text = data.get('text')
        voice = data.get('voice', VOICE)
        rate = data.get('rate', RATE)
    elif request.form:
        text = request.form.get('text')
        voice = request.form.get('voice', VOICE)
        rate = request.form.get('rate', RATE)
    elif request.args:
        text = request.args.get('text')
        voice = request.args.get('voice', VOICE)
        rate = request.args.get('rate', RATE)

    if not text or not str(text).strip():
        return jsonify({"success": False, "error": "No text provided"}), 400

    text = str(text).strip()
    process_speech_request(text=text, voice=voice, rate=rate)

    return jsonify({
        "success": True,
        "status": "playing",
        "text": text
    }), 200

@app.route('/sound/<name>', methods=['POST', 'GET', 'OPTIONS'])
def sound_by_path(name):
    if request.method == 'OPTIONS':
        return '', 200
    ok = play_sound_cue(name)
    return jsonify({
        "success": ok,
        "sound": name,
        "status": "playing" if ok else "not_found"
    }), 200 if ok else 404

@app.route('/sound', methods=['POST', 'GET', 'OPTIONS'])
def sound():
    if request.method == 'OPTIONS':
        return '', 200
    name = "connect"
    if request.is_json:
        data = request.get_json(silent=True) or {}
        name = data.get('sound') or data.get('name') or "connect"
    elif request.args:
        name = request.args.get('sound') or request.args.get('name') or "connect"

    ok = play_sound_cue(name)
    return jsonify({
        "success": ok,
        "sound": name,
        "status": "playing" if ok else "not_found"
    }), 200 if ok else 404

@app.route('/stop', methods=['POST', 'GET'])
def stop():
    stop_current_playback()
    return jsonify({"success": True, "message": "Áudio interrompido"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "online",
        "service": "Fast TTS Server",
        "module": "modules_dashboard.speech",
        "cache_dir": CACHE_DIR,
        "sound_dir": SOUND_DIR,
        "voice": VOICE,
        "rate": RATE
    }), 200

def run_server(host='0.0.0.0', port=5000):
    app.run(host=host, port=port, debug=False, threaded=True)

if __name__ == '__main__':
    print("=" * 65)
    print("MÓDULO: modules_dashboard/speech/speech_server.py")
    print("🚀 Porta: 5000 (TTS Neural Edge-TTS + ALSA)")
    print("=" * 65)
    run_server()
