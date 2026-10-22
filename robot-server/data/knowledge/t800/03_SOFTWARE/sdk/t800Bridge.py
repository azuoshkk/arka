# Bibliotecas que devem ser baixadas antes
# sudo apt-get install -y libasound2-dev portaudio19-dev
# pip3 install Flask requests sounddevice soundfile numpy

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import requests
import threading
import sounddevice as sd
import soundfile as sf
import io
from flask import Flask, request

# ==========================================
# CONFIGURAÇÕES DE REDE
# ==========================================
# URL do seu Servidor Backend Externo que fará o Reconhecimento Facial
BACKEND_URL = "http://IP_DO_SEU_SERVIDOR:5000/api/reconhecimento"

# Porta onde o Orin escutará o áudio enviado pelo Servidor Backend
ORIN_AUDIO_PORT = 8080

# Inicializa o app Flask para escuta de áudio
app = Flask(__name__)

# ==========================================
# 1. SERVIDOR DE ÁUDIO (Servidor -> T800)
# ==========================================
@app.route('/play_audio', methods=['POST'])
def play_audio():
    """
    Endpoint que o Servidor Backend vai chamar enviando o arquivo de áudio (bytes)
    para o robô reproduzir.
    """
    try:
        audio_bytes = request.data
        
        # Lê os bytes do áudio (suporta WAV, FLAC, OGG via soundfile)
        data, fs = sf.read(io.BytesIO(audio_bytes))
        
        # Reproduz o áudio nos alto-falantes de alta fidelidade do T800
        sd.play(data, fs)
        sd.wait() # Aguarda a reprodução terminar
        
        return "Áudio reproduzido com sucesso", 200
    except Exception as e:
        return f"Erro ao reproduzir áudio: {str(e)}", 500

def start_audio_server():
    # Roda o servidor Flask em uma thread separada para não bloquear o ROS2
    app.run(host='0.0.0.0', port=ORIN_AUDIO_PORT, threaded=True)


# ==========================================
# 2. NÓ ROS2 DE VISÃO (T800 -> Servidor)
# ==========================================
class CameraBridgeNode(Node):
    def __init__(self):
        super().__init__('camera_bridge_node')
        
        # Assina o tópico de imagens JPEGs já comprimidas pelo hardware do robô
        self.subscription = self.create_subscription(
            CompressedImage,
            'camera0/compressed',
            self.image_callback,
            10 # Tamanho da fila (QoS básico)
        )
        self.get_logger().info(f"Ponte iniciada. Enviando frames para: {BACKEND_URL}")
        self.get_logger().info(f"Escutando áudios na porta local: {ORIN_AUDIO_PORT}")

    def image_callback(self, msg):
        # msg.data contém um array de bytes com a imagem JPEG
        jpeg_bytes = bytes(msg.data)
        
        try:
            # Envia o frame comprimido para o servidor backend via HTTP POST
            # Dica: Timeout curto (0.2s) para não travar a fila de callbacks se a rede oscilar
            response = requests.post(
                BACKEND_URL, 
                data=jpeg_bytes, 
                headers={'Content-Type': 'image/jpeg'},
                timeout=0.2 
            )
            
            if response.status_code != 200:
                self.get_logger().warning(f"Aviso do backend: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            # Erros de rede (timeout, servidor fora do ar, etc)
            self.get_logger().error(f"Falha de conexão com backend: {e}")


# ==========================================
# FUNÇÃO PRINCIPAL
# ==========================================
def main(args=None):
    # 1. Inicia o servidor de escuta de áudio em background
    audio_thread = threading.Thread(target=start_audio_server, daemon=True)
    audio_thread.start()

    # 2. Inicia o nó ROS2 para capturar as imagens
    rclpy.init(args=args)
    camera_bridge = CameraBridgeNode()
    
    try:
        # Mantém o nó rodando e processando os callbacks da câmera
        rclpy.spin(camera_bridge)
    except KeyboardInterrupt:
        print("\nDesligando a ponte de I/O do T800...")
    finally:
        camera_bridge.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
