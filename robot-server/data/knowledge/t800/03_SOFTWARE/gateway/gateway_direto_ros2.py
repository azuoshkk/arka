import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import subprocess
import sys

# URL do servidor RTSP (MediaMTX) rodando na sua máquina
RTSP_URL = "rtsp://localhost:8554/live"


class RTSPDirectGateway(Node):
    def __init__(self):
        super().__init__('rtsp_direct_gateway')

        # Configuração nativa do FFmpeg para receber stream MJPEG cru da rede
        # e retransmitir em RTSP com latência zero.
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'image2pipe',  # Recebe fluxo de imagens contínuas
            '-vcodec', 'mjpeg',  # O formato que chega do ROS2 (CompressedImage)
            '-i', '-',  # Lê direto da memória (stdin)
            '-c:v', 'libx264',  # Codifica para H.264 exigido pelo RTSP
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-f', 'rtsp',
            RTSP_URL
        ]

        self.get_logger().info(f"Iniciando pipe FFmpeg para: {RTSP_URL}")

        # Inicia o processo do FFmpeg direcionando os erros para o terminal se houver falha
        try:
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stderr=sys.stdout
            )
        except Exception as e:
            self.get_logger().error(f"Erro ao iniciar o FFmpeg: {e}")
            self.ffmpeg_process = None

        # Subscreve ao tópico ROS2 exato com QoS padrão (10)
        self.subscription = self.create_subscription(
            CompressedImage,
            '/manifold/odin/device0/camera0/compressed',
            self.image_callback,
            10)

        self.frame_count = 0
        self.get_logger().info("Gateway Direto Ativo! Pronto para retransmitir ROS2 -> RTSP.")

    def image_callback(self, msg):
        self.frame_count += 1

        if self.frame_count % 30 == 0:
            self.get_logger().info(f"[{self.frame_count} frames] Repassando bytes comprimidos para o FFmpeg...")

        # Injeta os bytes puros do JPEG direto no FFmpeg, sem decodificar ou mexer em pixels
        if self.ffmpeg_process and self.ffmpeg_process.stdin:
            try:
                self.ffmpeg_process.stdin.write(bytes(msg.data))
                self.ffmpeg_process.stdin.flush()
            except Exception as e:
                # Caso o pipe feche ou dê erro
                pass

    def destroy_node(self):
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RTSPDirectGateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nEncerrando gateway...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()