"""Small CPU-only visual model; leaves the chat GPU configuration untouched."""
import base64
import io
import threading
import warnings
import requests
from PIL import Image
from app.config import OLLAMA_URL

_lock = threading.Lock()
MODEL = 'moondream'

def normalize(data):
    if not data or len(data) > 3 * 1024 * 1024:
        raise ValueError('Envie uma imagem de até 3 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('JPEG', 'PNG') or image.width * image.height > 4000000:
                    raise ValueError('Imagem deve ser JPEG/PNG com até 4 megapixels.')
                image.load()
                image = image.convert('RGB')
                image.thumbnail((768, 768))
                out = io.BytesIO()
                image.save(out, format='JPEG', quality=80)
                return out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Imagem inválida.') from exc

def describe(data):
    image = normalize(data)
    if not _lock.acquire(blocking=False):
        raise RuntimeError('Visão ocupada.')
    try:
        result = requests.post(OLLAMA_URL + '/api/generate', json={
            'model': MODEL, 'prompt': 'Describe the visible objects and scene briefly. Do not identify people. If unclear, say so.',
            'images': [base64.b64encode(image).decode()], 'stream': False,
            'keep_alive': 0,
            'options': {'num_gpu': 0, 'num_ctx': 2048, 'num_predict': 160, 'temperature': 0},
        }, timeout=(5, 180))
        result.raise_for_status()
        text = result.json().get('response', '').strip()
        if not text:
            raise RuntimeError('Sem observação visual.')
        return text[:1400]
    finally:
        _lock.release()
