import edge_tts as tts
import asyncio
from ollama import chat
from ollama import ChatResponse

voice = "pt-BR-FranciscaNeural"
voice_file="speech.mp3"

messages=[{
    'role': 'system',
    'content': """
    Você é Arka, assistente virtual da empresa IPQ.
    Responda sempre em português brasileiro.
    Seja objetiva e profissional.
    Se não souber uma informação, admita.
    Não responda de assuntos que tangenciem muito a empresa
    """
}]

answer = input("Você: ")

if answer.lower() == "sair":
        print("Arka: Até mais tarde...")
        
else:
    while answer.lower() != "sair":
        messages.append({'role':'user','content':answer})

        repsonse : ChatResponse chat(
            think=False,
            model='qwen3:1.7b',
            messages=messages,
            options={
                'temperature':0.2,
                'num_ctx':1024,
                },
        )

        arka = repsonse['message']['content']
        
        messages.append({'role':'assistant','content':arka})

        print("Arka: ",arka)
        

        async def voz() -> None:
            communicate=tts.Communicate(arka,voice)
            await communicate.save(voice_file)

        asyncio.run(voz())

        answer = input("Você: ")

        if answer.lower() == "sair":
            print("Arka: Até mais tarde...")
