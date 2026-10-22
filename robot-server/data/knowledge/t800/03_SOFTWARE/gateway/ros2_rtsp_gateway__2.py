import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import subprocess
import sys

class RosToRtspGateway(Node):
    def __init__(self):
        super().__init__('ros2_rtsp_gateway')
        
        rtsp_url = 'rtsp://localhost:8554/live'
        
        # FFmpeg otimizado com yuv420p (essencial para players descodificarem sem engasgar)
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', '640x480',
            '-pix_fmt', 'bgr24',
            '-r', '30',
            '-i', '-',
            '-vcodec', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p',
            '-f', 'rtsp',
            rtsp_url
        ]
        
        try:
            self.ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            self.get_logger().error(f"Erro ao iniciar FFmpeg: {e}")
            sys.exit(1)

        self.subscription = self.create_subscription(
            Image,
            '/t800/camera/raw',
            self.listener_callback,
            10
        )
        self.get_logger().info(f"Gateway ativo! Transmitindo para {rtsp_url}")

    def listener_callback(self, msg):
        try:
            if self.ffmpeg_proc.stdin:
                self.ffmpeg_proc.stdin.write(msg.data)
                self.ffmpeg_proc.stdin.flush()
        except Exception:
            pass

    def destroy_node(self):
        if hasattr(self, 'ffmpeg_proc') and self.ffmpeg_proc.stdin:
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
