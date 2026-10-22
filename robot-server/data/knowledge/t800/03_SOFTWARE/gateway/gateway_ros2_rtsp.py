import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import subprocess
import sys

class GatewayRosRtsp(Node):
    def __init__(self):
        super().__init__('rtsp_gateway_node')
        
        # Inicia o processo do FFmpeg direcionando o stream para o MediaMTX local
        rtsp_url = 'rtsp://localhost:8554/live'
        self.get_logger().info(f"Conectando ao RTSP em: {rtsp_url}")
        
        ffmpeg_command = [
            'ffmpeg',
            '-y',
            '-f', 'image2pipe',
            '-vcodec', 'mjpeg',
            '-r', '30',
            '-i', '-',
            '-vcodec', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-f', 'rtsp',
            rtsp_url
        ]
        
        try:
            self.ffmpeg_proc = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.get_logger().error(f"Erro ao iniciar FFmpeg: {e}")
            sys.exit(1)

        # Subscreve ao tópico oficial do T800 com QoS configurado para confiabilidade (10)
        self.subscription = self.create_subscription(
            CompressedImage,
            '/manifold/odin/device0/camera0/compressed',
            self.listener_callback,
            10
        )
        self.get_logger().info("Gateway ROS2 -> RTSP Ativo! Aguardando imagens da simulação...")

    def listener_callback(self, msg):
        try:
            if self.ffmpeg_proc.stdin:
                self.ffmpeg_proc.stdin.write(msg.data)
                self.ffmpeg_proc.stdin.flush()
        except Exception as e:
            self.get_logger().error(f"Erro ao injetar frames no FFmpeg: {e}")

def main(args=None):
    rclpy.init(args=args)
    node = GatewayRosRtsp()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'ffmpeg_proc') and node.ffmpeg_proc.stdin:
            node.ffmpeg_proc.stdin.close()
            node.ffmpeg_proc.wait()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
