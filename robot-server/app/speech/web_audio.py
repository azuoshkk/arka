"""Client audio only: never open the server microphone or speakers."""
import io
import os
from pathlib import Path
import requests
import re
import threading
import numpy as np
import soundfile as sf
from app.speech.tts_fast import clean_for_speech, trim_silence, KOKORO_SAMPLE_RATE
from app.core.voice_sanity import analyze_transcription

class WebAudio:
    def __init__(self):
        self.whisper = None
        self.pipeline = None
        self.stt_lock = threading.Lock()
        self.tts_lock = threading.Lock()
        self.upstream_url = os.getenv("ARKA_STT_UPSTREAM", "")
        self.upstream_token = None
        self.upstream_ready = False
        self.stt_error = None
        self.tts_error = None

    def upstream_session(self):
        from urllib.parse import urlsplit
        parsed=urlsplit(self.upstream_url)
        if parsed.hostname not in ('127.0.0.1','localhost') or parsed.scheme!='https':
            raise RuntimeError('STT upstream deve usar HTTPS de loopback.')
        root=Path(__file__).resolve().parents[3]
        self.upstream_ca=str(root/'.local/tls/arcanjo-local-ca.crt')
        response=requests.post(self.upstream_url+'/api/sessions',verify=self.upstream_ca,timeout=10)
        if response.status_code==401:
            credentials=(root/'.local/demo-login.txt').read_text().splitlines()
            response=requests.post(self.upstream_url+'/api/login',json={'username':credentials[0].split(': ',1)[1],'password':credentials[1].split(': ',1)[1]},verify=self.upstream_ca,timeout=10)
        response.raise_for_status();self.upstream_token=response.json()['token']
        state=requests.get(self.upstream_url+'/api/state',headers={'Authorization':'Bearer '+self.upstream_token},verify=self.upstream_ca,timeout=10)
        state.raise_for_status()
        if state.json().get('stt')!='ready':raise RuntimeError('Whisper upstream não está pronto.')
        self.upstream_ready=True

    def load_stt(self):
        if self.upstream_url:
            if not self.upstream_ready:self.upstream_session()
            return
        if self.whisper is None:
            from faster_whisper import WhisperModel
            # Intentionally no silent CPU fallback or GPU model reconfiguration.
            self.whisper = WhisperModel('small', device='cuda', compute_type='float16', local_files_only=True)

    def load_tts(self):
        if self.pipeline is None:
            from kokoro import KPipeline
            self.pipeline = KPipeline(lang_code='p', repo_id='hexgrad/Kokoro-82M', device='cpu')

    def warmup(self):
        for kind, lock, load in [('stt',self.stt_lock,self.load_stt), ('tts',self.tts_lock,self.load_tts)]:
            try:
                with lock:
                    load()
                    if kind == 'stt' and not self.upstream_url:
                        segments, _ = self.whisper.transcribe(np.zeros(16000,dtype=np.float32), language='pt')
                        list(segments)
                setattr(self,kind+'_error',None)
            except Exception:
                setattr(self,kind+'_error', 'Whisper CUDA indisponível' if kind=='stt' else 'Kokoro indisponível')

    def transcribe(self, data):
        if self.upstream_url:
            with self.stt_lock:
                self.load_stt()
                for attempt in range(2):
                    response=requests.post(self.upstream_url+'/api/transcribe',headers={'Authorization':'Bearer '+self.upstream_token,'Content-Type':'application/octet-stream'},data=data,verify=self.upstream_ca,timeout=(5,180))
                    if response.status_code!=401:break
                    self.upstream_session()
                if response.status_code==422:raise ValueError(response.json().get('detail','Áudio inválido.'))
                response.raise_for_status()
                return response.json()['text']
        import av
        # Decode with a strict duration bound before handing audio to Whisper.
        frames, count = [], 0
        try:
            with av.open(io.BytesIO(data)) as container:
                resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
                for frame in container.decode(audio=0):
                    for converted in resampler.resample(frame):
                        block = converted.to_ndarray().reshape(-1)
                        count += len(block)
                        if count > 16000*60: raise ValueError('Áudio deve ter no máximo 60 segundos.')
                        frames.append(block)
                for converted in resampler.resample(None):
                    block=converted.to_ndarray().reshape(-1); count += len(block)
                    if count > 16000*60: raise ValueError('Áudio deve ter no máximo 60 segundos.')
                    frames.append(block)
        except ValueError: raise
        except Exception as exc: raise ValueError('Formato de áudio inválido.') from exc
        if not frames or count < 1600: raise ValueError('Áudio muito curto.')
        samples = np.concatenate(frames).astype(np.float32)/32768
        if np.max(np.abs(samples)) < 0.005: raise ValueError('Não detectei fala. Tente novamente.')
        with self.stt_lock:
            try:
                self.load_stt()
                segments, _ = self.whisper.transcribe(samples, language='pt', beam_size=5, best_of=5,
                    temperature=0, condition_on_previous_text=False, without_timestamps=True,
                    initial_prompt='Conversa em português brasileiro. Arcanjo, T800, EngineAI, ROS2, SDK, Wi-Fi.',
                    vad_filter=True)
                text=' '.join(s.text.strip() for s in segments).strip()
                self.stt_error=None
            except Exception as exc:
                self.stt_error='Whisper CUDA indisponível'
                raise RuntimeError(self.stt_error) from exc
        if not text or analyze_transcription(text, {'tempo_fala_ativa': count/16000})['suspicious']:
            raise ValueError('Não entendi a fala. Tente novamente.')
        return text

    def synthesize(self, text):
        text=re.split(r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?fontes(?: consultadas| utilizadas| do RAG)?(?:\*\*)?\s*:", text, maxsplit=1)[0]
        cleaned=clean_for_speech(text)
        if not cleaned: raise ValueError('Não há texto para falar.')
        with self.tts_lock:
            try:
                self.load_tts()
                blocks=[trim_silence(item[-1]) for item in self.pipeline(cleaned, voice='pf_dora', speed=1.25, split_pattern=r'\n+')]
                blocks=[block for block in blocks if len(block)]
                if not blocks: raise RuntimeError('Áudio vazio')
                out=io.BytesIO()
                sf.write(out, np.concatenate(blocks), KOKORO_SAMPLE_RATE, format='WAV', subtype='PCM_16')
                self.tts_error=None
                return out.getvalue()
            except Exception as exc:
                self.tts_error='Kokoro indisponível'
                raise RuntimeError(self.tts_error) from exc
