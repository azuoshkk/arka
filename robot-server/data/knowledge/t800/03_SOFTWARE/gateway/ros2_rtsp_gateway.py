import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import subprocess
import sys

class RosToRtspGateway(Node):
    def __init__(self):
        super().__init__('ros2_rtsp_gateway')
        self.ffmpeg_proc = None
        self.frames = 0
        
        self.subscription = self.create_subscription(
            Image,
            '/t800/camera/raw',
            self.listener_callback,
            10
        )
        self.get_logger().info("Gateway ativo! A aguardar o primeiro frame...")

    def listener_callback(self, msg):
        try:
            if self.ffmpeg_proc is None:
                width = msg.width
                height = msg.height
                self.get_logger().info(f"Resolução: {width}x{height}. A iniciar FFmpeg...")
                
                rtsp_url = 'rtsp://admin:s3d31pqB%40%21@localhost:554/Streaming/Channels/101'
                
                ffmpeg_cmd = [
                    'ffmpeg', '-y',
                    '-f', 'rawvideo',
                    '-vcodec', 'rawvideo',
                    '-s', f'{width}x{height}',
                    '-pix_fmt', 'bgr24',
                    '-r', '30',
                    '-i', '-',
                    
                    # Compressão Turbo para IA
                    '-c:v', 'libx264',
                    '-preset', 'ultrafast',
                    '-tune', 'zerolatency',
                    '-profile:v', 'baseline',
                    '-level', '3.1',           # Garante que o Firefox não dê tela preta
                    '-pix_fmt', 'yuv420p',
                    
                    # Publica localmente via TCP (para não engasgar o MediaMTX)
                    '-rtsp_transport', 'tcp',
                    '-f', 'rtsp',
                    rtsp_url
                ]
                
                self.ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd, 
                    stdin=subprocess.PIPE, 
                    stdout=subprocess.DEVNULL, 
                    stderr=sys.stderr
                )
                self.get_logger().info("Transmissão iniciada!")

            if self.ffmpeg_proc and self.ffmpeg_proc.stdin:
                self.ffmpeg_proc.stdin.write(bytes(msg.data))
                self.ffmpeg_proc.stdin.flush()
                self.frames += 1
                if self.frames % 30 == 0:
                    self.get_logger().info(f"Gateway já injetou {self.frames} frames...")
                    
        except Exception as e:
            self.get_logger().error(f"Erro no pipeline: {e}")

    def destroy_node(self):
        if self.ffmpeg_proc and self.ffmpeg_proc.stdin:
            self.ffmpeg_proc.stdin.close()
            self.ffmpeg_proc.wait()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = RosToRtspGateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
