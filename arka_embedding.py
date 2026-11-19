"""Arka: STT local, roteamento por embeddings, RAG, Piper e webcam.

Dependências externas: ollama, numpy, sounddevice, faster-whisper,
piper-tts, opencv-python. Requer ffplay instalado no Linux.
"""

import hashlib
import queue
import re
import subprocess
import threading
import unicodedata
import wave
from collections import deque
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import ollama
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

EMBED_MODEL = "bge-m3"
CHAT_MODEL = "qwen3:1.7b"
VOICE_FILE = "modelos/dii/dii_pt-BR.onnx"
CACHE_DIR = Path(".cache/arka")
DEBUG_TEMPO = False

SYSTEM_PROMPT = (
    "Você é Arka, assistente virtual da IPQ Tecnologia. "
    "Responda em português brasileiro de forma objetiva e profissional. "
    "Use as informações do contexto quando forem fornecidas. "
    "Se houver uma resposta explícita, dê-a diretamente; não a descarte "
    "por ressalvas genéricas. Diferencie cargos como CEO e presidente. "
    "Se realmente faltar informação, diga que não sabe. Não invente dados."
)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", texto))


def retirar_chamado(frase):
    return re.sub(
        r"^\s*(?:arka|arca|arcan)\b[\s,.:!?-]*",
        "", frase, flags=re.IGNORECASE
    ).strip()


def ler_dados(caminho, formato):
    texto = Path(caminho).read_text(encoding="utf-8")
    if formato == "faq":
        blocos = re.split(r"\n\s*\n", texto)
        dados = [b.strip() for b in blocos if b.strip().startswith("PERGUNTA:")
                 and "RESPOSTA:" in b]
    elif formato == "lista":
        dados = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    else:
        raise ValueError(f"Formato inválido: {formato}")
    if not dados:
        raise ValueError(f"Nenhum dado válido em {caminho}")
    return dados


def normalizar_vetores(vetores):
    vetores = np.asarray(vetores, dtype=np.float32)
    normas = np.linalg.norm(vetores, axis=-1, keepdims=True)
    return vetores / np.maximum(normas, 1e-12)


def vetor_pergunta(frase):
    vetor = ollama.embed(model=EMBED_MODEL, input=frase)["embeddings"][0]
    return normalizar_vetores(vetor)


def indice_embedding(dados, nome):
    # Reaproveita os embeddings de inicializações anteriores; invalida
    # automaticamente o cache quando o texto da base é alterado.
    identificador = hashlib.sha256(
        (EMBED_MODEL + "\0" + "\0".join(dados)).encode("utf-8")
    ).hexdigest()[:16]
    arquivo = CACHE_DIR / f"{nome}-{identificador}.npy"
    if arquivo.is_file():
        return np.load(arquivo, allow_pickle=False)

    vetores = ollama.embed(model=EMBED_MODEL, input=dados)["embeddings"]
    indice = normalizar_vetores(vetores)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(arquivo, indice)
    return indice


def buscar_similares(vetor, indice, dados, quantidade=3):
    scores = indice @ vetor
    k = min(quantidade, len(scores))
    posicoes = np.argpartition(scores, -k)[-k:]
    posicoes = posicoes[np.argsort(scores[posicoes])[::-1]]
    return [(dados[i], float(scores[i])) for i in posicoes]


def detectar_comando(frase):
    """Para tirar foto, exige uma ordem clara; similaridade sozinha é insegura."""
    texto = normalizar(frase)
    palavras = set(texto.split())
    if not re.match(r"^(?:arka|arca|arcan)\b", texto):
        return None
    if "acesso" in palavras and palavras & {"nao", "nunca", "jamais"}:
        return "CANCELADO"
    if re.fullmatch(
        r"(?:arka|arca|arcan) (?:liberar|libera|libere) (?:o )?acesso",
        texto,
    ):
        return "FOTO"
    return None


def hear():
    taxa = 16000
    duracao_bloco = 0.2
    limite_voz = 0.015
    blocos_silencio = int(1.0 / duracao_bloco)

    fila = queue.Queue()
    pausado = threading.Event()
    pre_buffer = deque(maxlen=2)
    buffer = []
    silencio = 0

    print("Carregando STT...")
    whisper = WhisperModel("small", device="cpu", compute_type="int8")
    dispositivo = next(
        (i for i, d in enumerate(sd.query_devices())
         if "Solid_State_System" in d["name"] and d["max_input_channels"] > 0),
        None,
    )
    if dispositivo is None:
        raise RuntimeError("Microfone USB não encontrado")

    def callback(indata, frames, time_info, status):
        if not pausado.is_set():
            fila.put(indata.copy())

    with sd.InputStream(
        device=dispositivo,
        samplerate=taxa,
        channels=1,
        dtype="float32",
        blocksize=int(taxa * duracao_bloco),
        callback=callback,
    ):
        print("Pode falar!")
        while True:
            bloco = fila.get()
            volume = float(np.sqrt(np.mean(bloco ** 2)))

            if volume > limite_voz:
                if not buffer:
                    buffer.extend(pre_buffer)
                    pre_buffer.clear()
                buffer.append(bloco)
                silencio = 0
            elif buffer:
                buffer.append(bloco)
                silencio += 1
                if silencio >= blocos_silencio:
                    audio = np.concatenate(buffer).ravel()
                    buffer.clear()
                    silencio = 0
                    pausado.set()
                    try:
                        trechos, _ = whisper.transcribe(
                            audio,
                            initial_prompt=(
                                "Esta conversa é sobre a IPQ Tecnologia. "
                                "Termos frequentes: IPQ, Arka, Arcanjo e Tático."
                            ),
                            beam_size=5,
                            task="transcribe",
                            language="pt",
                            vad_filter=True,
                        )
                        frase = " ".join(t.text.strip() for t in trechos if t.text.strip())
                        if frase:
                            yield frase
                    finally:
                        # Não processa o som da própria Arka nem da geração do LLM.
                        while True:
                            try:
                                fila.get_nowait()
                            except queue.Empty:
                                break
                        pre_buffer.clear()
                        pausado.clear()
            else:
                pre_buffer.append(bloco)


def speak(texto, voz):
    texto = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texto)
    texto = re.sub(r"[*_`#]", "", texto).strip()
    if not texto:
        return
    with wave.open("speech.wav", "wb") as saida:
        voz.synthesize_wav(texto, saida)
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "speech.wav"],
        check=True,
    )


def take_photo(caminho="foto.jpg"):
    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            raise RuntimeError("Câmera não encontrada")
        ok, frame = camera.read()
        if not ok or frame is None or not cv2.imwrite(caminho, frame):
            raise RuntimeError("Falha ao capturar ou salvar a foto")
        return caminho
    finally:
        camera.release()


def main():
    base = ler_dados("conhecimentos.txt", "faq")
    perguntas_ipq = ler_dados("perguntas_IPQ.txt", "lista")
    perguntas_gerais = ler_dados("Perguntas_gerais.txt", "lista")

    indice_base = indice_embedding(base, "faq")
    indice_ipq = indice_embedding(perguntas_ipq, "ipq")
    indice_geral = indice_embedding(perguntas_gerais, "geral")
    voz = PiperVoice.load(VOICE_FILE)
    historico = []

    for frase in hear():
        frase = frase.strip()
        if not frase:
            continue
        print(f"\nVocê: {frase}")
        inicio = perf_counter()

        comando = detectar_comando(frase)
        if comando == "CANCELADO":
            print("Arka: Comando não executado.")
            continue
        if comando == "FOTO":
            try:
                print(f"Foto salva: {take_photo()}")
            except Exception as erro:
                print(f"Erro na câmera: {erro}")
            continue

        busca = retirar_chamado(frase)
        if not busca:
            continue
        vetor = vetor_pergunta(busca)  # Só UMA chamada ao bge-m3 por fala.

        score_ipq = float((indice_ipq @ vetor).max())
        score_geral = float((indice_geral @ vetor).max())
        if score_ipq > score_geral:
            resultados = buscar_similares(vetor, indice_base, base)

            # Para pergunta igual à de uma FAQ, exclui distratores do Top-3.
            pergunta_top1 = resultados[0][0].split("RESPOSTA:", 1)[0]
            pergunta_top1 = pergunta_top1.removeprefix("PERGUNTA:").strip()
            if normalizar(busca) == normalizar(pergunta_top1):
                resultados = resultados[:1]

            contexto = "\n\n".join(bloco for bloco, _ in resultados)
            if DEBUG_TEMPO:
                print("TOP recuperado:")
                for bloco, score in resultados:
                    print(f"{bloco.splitlines()[0]} | {score * 100:.2f}")

            mensagem = (
                "Responda diretamente à pergunta com base no contexto abaixo. "
                "Se a resposta estiver explícita, não diga que não há dados. "
                "Se não estiver disponível, admita que não sabe.\n\n"
                f"Contexto:\n{contexto}\n\nPergunta:\n{busca}"
            )
        else:
            mensagem = busca

        mensagens = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + historico[-4:]
            + [{"role": "user", "content": mensagem}]
        )
        resposta = ollama.chat(
            model=CHAT_MODEL,
            messages=mensagens,
            think=False,
            options={"temperature": 0.2, "num_ctx": 2048},
        )["message"]["content"].strip()
        print(f"Arka: {resposta}")
        if DEBUG_TEMPO:
            print(f"Até a resposta: {perf_counter() - inicio:.2f}s")

        speak(resposta, voz)
        if DEBUG_TEMPO:
            print(f"Total com TTS: {perf_counter() - inicio:.2f}s")

        historico.extend([
            {"role": "user", "content": busca},
            {"role": "assistant", "content": resposta},
        ])
        historico = historico[-4:]


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArka encerrada.")