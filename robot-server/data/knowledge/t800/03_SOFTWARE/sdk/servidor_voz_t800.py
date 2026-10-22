from flask import Flask, request, jsonify
import os
import threading
import asyncio
import edge_tts
import uuid

app = Flask(__name__)

# ================= CONFIGURAÇÕES DA VOZ =================
# Você pode alterar essas variáveis como fizemos no teste
MODELO_VOZ = "pt-BR-AntonioNeural"
VELOCIDADE = "+25%"


# ========================================================

async def gerar_e_tocar_async(texto):
    """
    Função assíncrona que chama a IA da Microsoft (edge-tts),
    salva num arquivo temporário e toca no alto-falante.
    """
    # Cria um nome de arquivo temporário único para evitar conflitos
    arquivo_audio = f"/tmp/voz_t800_{uuid.uuid4()}.mp3"

    # Gera o áudio com a voz neural
    comunicacao = edge_tts.Communicate(texto, MODELO_VOZ, rate=VELOCIDADE)
    await comunicacao.save(arquivo_audio)

    # Toca o áudio no Linux (tenta mpg123 primeiro, se falhar tenta ffplay)
    comando_tocar = f"mpg123 -q {arquivo_audio} || ffplay -nodisp -autoexit -loglevel quiet {arquivo_audio}"
    os.system(comando_tocar)

    # Apaga o arquivo logo depois de tocar para não encher o disco do robô
    if os.path.exists(arquivo_audio):
        os.remove(arquivo_audio)


def tocar_audio(texto):
    """
    Função síncrona (wrapper) que roda dentro da thread e
    inicia o processo assíncrono do edge-tts.
    """
    asyncio.run(gerar_e_tocar_async(texto))


@app.route('/falar', methods=['POST'])
def receber_texto():
    dados = request.get_json()

    # Verifica se enviaram a chave 'texto'
    if not dados or 'texto' not in dados:
        return jsonify({"erro": "Nenhum texto enviado no JSON."}), 400

    texto = dados['texto']
    print(f"🔊 Recebido do Servidor Facial: {texto}")

    # Roda a fala numa thread separada para não travar a resposta HTTP
    threading.Thread(target=tocar_audio, args=(texto,)).start()

    return jsonify({"status": "sucesso", "mensagem": "Áudio neural em reprodução!"}), 200


if __name__ == '__main__':
    print("🤖 Módulo de Voz Neural do T800 Iniciado na porta 5000...")
    print(f"🎙️ Configuração ativa -> Voz: {MODELO_VOZ} | Velocidade: {VELOCIDADE}")

    # Roda em 0.0.0.0 para aceitar conexões de qualquer computador da rede
    app.run(host='0.0.0.0', port=5000)