import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import numpy as np

class T800RTSPBridge(Node):
    def __init__(self):
        super().__init__('t800_rtsp_bridge')
        self.get_logger().info("A aguardar a imagem do T800 no tópico /camera0/compressed...")
        
        self.subscription = self.create_subscription(
            CompressedImage, '/camera0/compressed', self.image_callback, 10)
        
        # Pipeline H.264 de baixíssima latência enviando para localhost
        gst_pipeline = (
            "appsrc ! videoconvert ! "
            "x264enc tune=zerolatency bitrate=2048 speed-preset=ultrafast ! "
            "rtspclientsink location=rtsp://127.0.0.1:8554/cam_t800"
        )
        self.out = cv2.VideoWriter(gst_pipeline, cv2.CAP_GSTREAMER, 0, 30, (1280, 1088), True)
        self.first_frame = True

    def image_callback(self, msg):
        if self.first_frame:
            self.get_logger().info("✅ Primeiro frame recebido do robô! Transmitindo RTSP...")
            self.first_frame = False

        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is not None and self.out.isOpened():
            self.out.write(frame)

def main(args=None):
    rclpy.init(args=args)
    node = T800RTSPBridge()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
