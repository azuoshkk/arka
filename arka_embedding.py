import ollama
import numpy as np
import sounddevice as sd
import queue
import threading
import subprocess
import wave
import cv2

from collections import deque
from faster_whisper import WhisperModel
from piper import PiperVoice

# listas
vetores=[]
cosSim=[]
ipq=[]
gerais=[]
messages = [{
    'role':'system',
    'content':"""
    Você é Arka, assistente virtual da empresa IPQ.
    Responda sempre em português brasileiro.
    Seja objetiva e profissional.
    Se não souber uma informação, admita.
    Não responda de assuntos que tangenciem muito a empresa
    """
}]

def call_ollama(messages,temperature,contexto):
    resposta = ollama.chat(
        think=False,
        model='qwen3:1.7b',
        messages=messages,
        options={
            'temperature':temperature,
            'num_ctx':contexto,
        }
    )
    return resposta['message']['content']

def data_clear(rawData, formato): # função para limpara o banco de dados em uma array. O banco de dados já deve estar formatado do jeito esperado
    clean_data=[]

    # Separa o tipo de dado entre Lista e faq e limpa com base formato
    if formato == "faq":
        with open(rawData) as file:
            data = file.read()
            data = data.split("\n\n")
        for bloco in data:
            if bloco.startswith("PERGUNTA:"):
                clean_data.append(bloco)
                
    elif formato == "lista":
        with open(rawData) as file:
            data = file.read()
            data = data.split("\n")
        for bloco in data:
            clean_data.append(bloco)
    else:
        return "formato indisponivel"

    return clean_data

def embed_generator(data): # função para gerar os embeddings dos dados  
    r=ollama.embed(model="bge-m3",input=data)
    return np.array(r['embeddings'])

def find_similar(frase, embed, clean_data): # função para achar frase similar com base no input do user e nos dados
    embedGerado=embed_generator(frase)[0]

    scores = embed @ embedGerado
    indices=np.argsort(scores)
    melhor = indices[-1]
    k3 = []

    for i in indices[-3:][::-1]:
        k3.append({
            clean_data[i]:scores[i]*100
        })

    return scores[melhor]*100, k3

def extrude_contexAnswer(resposta):
    bloco = resposta.split("RESPOSTA:",1)[1]
    bloco = bloco.split("FONTES:",1)[0]
    return bloco.strip()

def detect_routeType(frase):
    palavras = frase.lower().replace(",", "").split()
    if "nao" in palavras or "não" in palavras:
        return None 
    comandos = ["arka, liberar acesso","arca, liberar acesso"]
    comandos_embed = embed_generator(comandos)

    similaridade,_ = find_similar(frase, comandos_embed, comandos)

    if similaridade > 80:
        return "COMANDO"

def choose_route(frase, ipq_listaData, ipq_embed, gerais_listaData, gerais_embed): # função para decidir a rota entre o sistema rag e o ollama normal 
    ipq_melhor,_ = find_similar(frase, ipq_embed, ipq_listaData)
    gerais_melhor,_ = find_similar(frase, gerais_embed, gerais_listaData)

    # print(f"IPQ: {ipq_melhor:.4f}")
    # print(f"GERAL: {gerais_melhor:.4f}")

    if ipq_melhor > gerais_melhor:
        return "IPQ"
    else:
        return "GERAL"

def hear():
    SAMPLE_RATE = 16000
    BLOCK_DURATION = 0.2
    SILENCE_THRESHOLD = 0.015

    pausado = threading.Event()
    fila = queue.Queue()
    pre_buffer = deque(maxlen=2)
    audio_buffer = []
    silence_blocks = 0

    print("Carregando STT...")
    model = WhisperModel("small", device="cpu", compute_type="int8")

    # Localiza o microfone USB
    device = next(
        (i for i, d in enumerate(sd.query_devices())
         if "Solid_State_System" in d["name"]
         and d["max_input_channels"] > 0),
        None
    )

    if device is None:
        raise RuntimeError("Microfone USB não encontrado.")

    def callback(indata, frames, time, status):
        if not pausado.is_set():
            fila.put(indata.copy())

    with sd.InputStream(
        device=device,
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
        callback=callback
    ):
        print("Pode falar!")

        while True:
            block = fila.get()
            volume = np.sqrt(np.mean(block ** 2))

            if volume > SILENCE_THRESHOLD:
                if not audio_buffer:
                    audio_buffer.extend(pre_buffer)
                    pre_buffer.clear()

                audio_buffer.append(block)
                silence_blocks = 0

            elif audio_buffer:
                audio_buffer.append(block)
                silence_blocks += 1

                if silence_blocks >= 5:
                    audio = np.concatenate(audio_buffer).flatten()
                    audio_buffer.clear()
                    silence_blocks = 0

                    pausado.set()

                    try:
                        segments, _ = model.transcribe(
                            audio,
                            initial_prompt=(
                                "Esta conversa é sobre a IPQ Tecnologia. "
                                "Termos frequentes: IPQ, Arka, Arcanjo e Tático."
                            ),
                            beam_size=5,
                            task="transcribe",
                            language="pt",
                            vad_filter=True
                        )

                        texto = " ".join(
                            s.text.strip()
                            for s in segments
                            if s.text.strip()
                        )

                        if texto:
                            yield texto

                    finally:
                        # Limpa áudios antigos antes de voltar a escutar
                        while True:
                            try:
                                fila.get_nowait()
                            except queue.Empty:
                                break

                        pre_buffer.clear()
                        pausado.clear()

            else:
                pre_buffer.append(block)

def carregar_dii():
    return PiperVoice.load("modelos/dii/dii_pt-BR.onnx")

def speak(texto, voz):
    with wave.open("speech.wav", "wb") as audio:
        voz.synthesize_wav(texto, audio)

    subprocess.run([
        "ffplay", "-nodisp", "-autoexit",
        "-loglevel", "error",
        "speech.wav"
    ], check=True)

def take_photo(): # melhorar função
    camera = cv2.VideoCapture(0)

    if camera.isOpened():
        print("camera aberta")
        sucesso, frame = camera.read()
        if sucesso:
            cv2.imwrite("foto.jpg",frame)
            camera.release()
        else:
            print("n foi possivel abrir a camera")
    else: 
        print("camera n foi aberta")

def main():
    clean_data = data_clear("conhecimentos.txt", "faq")
    embed = embed_generator(clean_data)

    ipq_listaData = data_clear("perguntas_IPQ.txt", "lista")
    gerais_listaData = data_clear("Perguntas_gerais.txt", "lista")

    ipq_embed = embed_generator(ipq_listaData)
    gerais_embed = embed_generator(gerais_listaData)

    voice = carregar_dii()

    for frase in hear():
        frase = frase.strip()
        if not frase:
            continue

        print(f"\nVocê: {frase}")

        if detect_routeType(frase) == "COMANDO":
            take_photo()
        else: 
            rota = choose_route(
                frase,
                ipq_listaData, ipq_embed,
                gerais_listaData, gerais_embed
            )

            if rota == "IPQ":
                _, top3 = find_similar(frase, embed, clean_data)
                print("TOP-3 RECUPERADO:")

                for item in top3:
                    for bloco, score in item.items():
                        print(f"{bloco.splitlines()[0]} | {score:.2f}")

                respostas = [
                    extrude_contexAnswer(bloco)
                    for item in top3
                    for bloco in item
                ]

                contexto = "\n\n".join(respostas)

                mensagem_atual = (
                    "Responda usando apenas as informações fornecidas. "
                    "Se não souber, admita.\n\n"
                    f"Contexto:\n{contexto}\n\n"
                    f"Pergunta:\n{frase}"
                )
            else:
                mensagem_atual = frase

            messages_call = messages + [{
                "role": "user",
                "content": mensagem_atual
            }]

            resposta = call_ollama(messages_call, 0.2, 2048)

            print(f"Arka: {resposta}")

            speak(resposta, voice)

            messages.append({"role": "user", "content": frase})
            messages.append({"role": "assistant", "content": resposta})

if __name__ == "__main__":
    main()