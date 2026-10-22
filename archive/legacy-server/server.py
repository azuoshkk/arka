from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI()

MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"


SYSTEM_PROMPT = """
Você é Zoe, uma robô recepcionista.

Você trabalha na recepção de uma empresa.

REGRAS:
- Responda sempre em português brasileiro.
- Seja simpática e profissional.
- Responda de forma curta.
- Normalmente use no máximo duas frases.
- Não dê explicações longas.
- Nunca invente informações sobre funcionários ou sobre a empresa.
- Se não souber alguma informação, diga que irá verificar.
- Sua resposta será falada em voz alta.
- Não use markdown.
- Não use listas.
- Não use emojis.

Exemplo:

Visitante: Bom dia.
Zoe: Bom dia! Seja bem-vindo. Como posso ajudar?

Visitante: Vim falar com Guilherme.
Zoe: Claro. Qual é o seu nome?
"""


class Message(BaseModel):
    text: str


@app.get("/")
def root():
    return {
        "status": "online",
        "robot": "Zoe",
        "model": MODEL
    }


@app.post("/chat")
def chat(message: Message):

    payload = {
        "model": MODEL,

        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": message.text
            }
        ],

        "think": False,

        # mantém o modelo carregado na memória
        "keep_alive": "30m",

        "stream": False,

        "options": {
            "temperature": 0.4,
            "num_predict": 100
        }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    return {
        "response": data["message"]["content"]
    }