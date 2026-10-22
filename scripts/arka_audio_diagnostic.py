#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "robot-server"))


import argparse, json, math, os, re, time, unicodedata
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad

RATE = 16000
VAD_CHUNK = 512
REFERENCE = (
    "Qual a senha do Wi-Fi do T800? "
    "Como habilitar os tópicos ROS2 do T800?"
)

def normalize_text(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def levenshtein_words(ref, hyp):
    r = normalize_text(ref).split()
    h = normalize_text(hyp).split()
    dp = [[0]*(len(h)+1) for _ in range(len(r)+1)]
    for i in range(len(r)+1): dp[i][0] = i
    for j in range(len(h)+1): dp[0][j] = j
    for i in range(1, len(r)+1):
        for j in range(1, len(h)+1):
            cost = 0 if r[i-1] == h[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    dist = dp[-1][-1]
    return dist, (dist / len(r) if r else 0.0)

def dbfs(rms):
    return 20 * math.log10(max(rms, 1e-12))

def metrics(audio):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if len(audio) else 0.0
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    clipping = float(np.mean(np.abs(audio) >= 0.99) * 100.0) if len(audio) else 0.0
    return {
        "rms": rms,
        "dbfs": dbfs(rms),
        "peak": peak,
        "peak_dbfs": 20 * math.log10(max(peak, 1e-12)),
        "clipping_percent": clipping,
        "dc_offset": float(np.mean(audio)) if len(audio) else 0.0,
    }

def load_whisper(name):
    try:
        import ctranslate2
        gpus = ctranslate2.get_cuda_device_count()
    except Exception:
        gpus = 0
    if gpus > 0:
        try:
            return WhisperModel(name, device="cuda", compute_type="float16"), "GPU NVIDIA"
        except Exception as exc:
            print("⚠️ GPU Whisper falhou:", exc)
    return WhisperModel(name, device="cpu", compute_type="int8"), "CPU"

def transcribe(model, audio, beam):
    t0 = time.perf_counter()
    segments, _ = model.transcribe(
        audio.astype(np.float32),
        language="pt",
        beam_size=beam,
        best_of=beam,
        temperature=0,
        condition_on_previous_text=False,
        without_timestamps=True,
        vad_filter=False,
        initial_prompt=(
            "Português brasileiro. Termos possíveis: "
            "Arka, T800, EngineAI, Wi-Fi, ROS2, ros2_bridge, RC02, SDK."
        ),
    )
    text = "".join(s.text for s in segments).strip()
    return text, time.perf_counter() - t0

def apply_vad(audio, model, threshold=0.55, silence_time=0.65, prebuffer_frames=12):
    if hasattr(model, "reset_states"):
        model.reset_states()
    pre = deque(maxlen=prebuffer_frames)
    captured = []
    speaking = False
    silence_frames = 0
    start_frame = last_voice = end_frame = None
    silence_limit = max(1, int(silence_time * RATE / VAD_CHUNK))
    total = int(math.ceil(len(audio) / VAD_CHUNK))

    for idx in range(total):
        a = idx * VAD_CHUNK
        b = min(len(audio), a + VAD_CHUNK)
        chunk = audio[a:b]
        if len(chunk) < VAD_CHUNK:
            chunk = np.pad(chunk, (0, VAD_CHUNK-len(chunk)))
        prob = float(model(torch.from_numpy(chunk.astype(np.float32)), RATE).item())

        if not speaking:
            pre.append(chunk.copy())
            if prob >= threshold:
                speaking = True
                start_frame = idx
                last_voice = idx
                captured.extend(list(pre))
                pre.clear()
        else:
            captured.append(chunk.copy())
            if prob >= threshold:
                silence_frames = 0
                last_voice = idx
            else:
                silence_frames += 1
            if silence_frames >= silence_limit:
                end_frame = idx
                break

    if not captured:
        return np.array([], dtype=np.float32), {
            "detected": False, "start_seconds": None,
            "last_voice_seconds": None, "end_seconds": None,
            "captured_seconds": 0.0
        }

    vad_audio = np.concatenate(captured).astype(np.float32)
    return vad_audio, {
        "detected": True,
        "start_seconds": start_frame * VAD_CHUNK / RATE if start_frame is not None else None,
        "last_voice_seconds": last_voice * VAD_CHUNK / RATE if last_voice is not None else None,
        "end_seconds": end_frame * VAD_CHUNK / RATE if end_frame is not None else len(audio)/RATE,
        "captured_seconds": len(vad_audio)/RATE,
    }

def classify(report):
    f = []
    noise = report["noise"]["dbfs"]
    speech = report["speech"]["dbfs"]
    snr = report["snr_db"]
    clipping = report["full"]["clipping_percent"]
    raw_wer = report["whisper"]["raw"]["wer_percent"]
    vad_wer = report["whisper"]["vad"]["wer_percent"]

    if speech < -35: f.append("MIC_INPUT_LOW: fala muito baixa; ganho/dispositivo de entrada é suspeito.")
    elif speech > -8: f.append("MIC_INPUT_HOT: fala muito alta; risco de saturação.")
    if noise > -35: f.append("HIGH_NOISE_FLOOR: ruído de fundo elevado.")
    if snr < 10: f.append("LOW_SNR: relação sinal/ruído ruim; captura/microfone/ambiente é o principal suspeito.")
    elif snr < 18: f.append("MEDIUM_SNR: áudio utilizável, mas há espaço para melhorar ruído/ganho.")
    if clipping > 0.1: f.append("CLIPPING: há amostras saturadas; reduza o ganho.")
    if not report["vad"]["detected"]:
        f.append("VAD_FAIL: Silero não detectou fala.")
    elif vad_wer >= raw_wer + 20:
        f.append("VAD_DAMAGE: pós-VAD ficou muito pior que o áudio bruto.")
    if raw_wer >= 40 and snr >= 18 and speech >= -35:
        f.append("WHISPER_SUSPECT: áudio parece razoável, mas Whisper errou muito.")
    if raw_wer <= 20 and vad_wer <= 20:
        f.append("PIPELINE_GOOD: captura e STT estão funcionando bem neste teste.")
    if not f:
        f.append("MIXED: nenhum gargalo ficou dominante.")
    return f

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", default=None)
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", "small"))
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "logs" / "audio_diagnostics"))
    args = p.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    device = args.device
    if device is not None:
        try: device = int(device)
        except ValueError: pass

    out = Path(args.output) / time.strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True, exist_ok=True)

    silence_s = 2
    speech_s = 8
    total_s = silence_s + speech_s + silence_s

    print("\n" + "="*72)
    print("ARKA AUDIO DIAGNOSTIC")
    print("="*72)
    print("\nEntrada:")
    try: print(sd.query_devices(device, "input"))
    except Exception: print(sd.query_devices(kind="input"))

    print("\nPROTOCOLO")
    print("1. Fique em silêncio por 2s.")
    print("2. Leia EXATAMENTE:")
    print(f'\n   "{REFERENCE}"\n')
    print("3. Fique em silêncio por mais 2s.\n")

    for n in (3,2,1):
        print(f"Começando em {n}...")
        time.sleep(1)

    print("🔴 GRAVANDO...")
    audio = sd.rec(int(total_s*RATE), samplerate=RATE, channels=1,
                   dtype="float32", device=device)
    sd.wait()
    audio = audio[:,0].astype(np.float32)
    print("✅ Gravação concluída.")

    raw_path = out/"01_raw_full.wav"
    sf.write(raw_path, audio, RATE, subtype="PCM_16")

    s0 = silence_s*RATE
    s1 = s0 + speech_s*RATE
    speech_region = audio[s0:s1]
    noise = np.concatenate([audio[:s0], audio[s1:]])

    speech_path = out/"02_known_speech_window.wav"
    sf.write(speech_path, speech_region, RATE, subtype="PCM_16")

    full_m = metrics(audio)
    noise_m = metrics(noise)
    speech_m = metrics(speech_region)
    snr = speech_m["dbfs"] - noise_m["dbfs"]

    print("\n👂 Silero VAD...")
    vad_model = load_silero_vad()
    vad_audio, vad_m = apply_vad(audio, vad_model)
    vad_path = out/"03_vad_to_whisper.wav"
    if len(vad_audio):
        sf.write(vad_path, vad_audio, RATE, subtype="PCM_16")

    print(f"🧠 Whisper {args.whisper_model}...")
    whisper, whisper_device = load_whisper(args.whisper_model)

    raw_text, raw_t = transcribe(whisper, speech_region, args.beam)
    raw_dist, raw_wer = levenshtein_words(REFERENCE, raw_text)

    if len(vad_audio):
        vad_text, vad_t = transcribe(whisper, vad_audio, args.beam)
        vad_dist, vad_wer = levenshtein_words(REFERENCE, vad_text)
    else:
        vad_text, vad_t = "", 0.0
        vad_dist = len(normalize_text(REFERENCE).split())
        vad_wer = 1.0

    report = {
        "reference": REFERENCE,
        "full": full_m,
        "noise": noise_m,
        "speech": speech_m,
        "snr_db": snr,
        "vad": vad_m,
        "whisper": {
            "model": args.whisper_model,
            "device": whisper_device,
            "beam": args.beam,
            "raw": {
                "text": raw_text, "seconds": raw_t,
                "word_distance": raw_dist, "wer_percent": raw_wer*100
            },
            "vad": {
                "text": vad_text, "seconds": vad_t,
                "word_distance": vad_dist, "wer_percent": vad_wer*100
            },
        },
    }
    report["findings"] = classify(report)

    (out/"report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "="*72,
        "ARKA AUDIO DIAGNOSTIC REPORT",
        "="*72,
        "",
        f"Whisper: {args.whisper_model} | {whisper_device} | beam={args.beam}",
        "",
        "ÁUDIO",
        f"Noise floor: {noise_m['dbfs']:.1f} dBFS",
        f"Speech RMS:  {speech_m['dbfs']:.1f} dBFS",
        f"Peak:        {full_m['peak_dbfs']:.1f} dBFS",
        f"SNR aprox.:  {snr:.1f} dB",
        f"Clipping:    {full_m['clipping_percent']:.3f}%",
        f"DC offset:   {full_m['dc_offset']:.6f}",
        "",
        "VAD",
        f"Detectou:         {vad_m['detected']}",
        f"Início detectado: {vad_m['start_seconds']}",
        f"Última voz:       {vad_m['last_voice_seconds']}",
        f"Fim segmento:     {vad_m['end_seconds']}",
        f"Áudio entregue:   {vad_m['captured_seconds']:.3f}s",
        "",
        "WHISPER — JANELA BRUTA",
        f'Texto: "{raw_text}"',
        f"Tempo: {raw_t:.3f}s",
        f"WER:   {raw_wer*100:.1f}%",
        "",
        "WHISPER — PÓS-VAD",
        f'Texto: "{vad_text}"',
        f"Tempo: {vad_t:.3f}s",
        f"WER:   {vad_wer*100:.1f}%",
        "",
        "DIAGNÓSTICO AUTOMÁTICO",
    ]
    lines.extend(f"- {x}" for x in report["findings"])
    lines += ["", "ARQUIVOS", str(raw_path), str(speech_path), str(vad_path)]

    txt = "\n".join(lines)
    (out/"report.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print("\n✅ Pasta:", out)

if __name__ == "__main__":
    main()
