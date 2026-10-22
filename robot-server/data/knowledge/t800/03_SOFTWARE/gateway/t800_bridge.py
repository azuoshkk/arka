import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import numpy as np

class T800RTSPBridge(Node):
    def __init__(self):
        super().__init__('t800_rtsp_bridge')
        
        self.get_logger().info("A procurar pelo tópico /camera0/compressed na rede...")
        
        self.subscription = self.create_subscription(
            CompressedImage,
            '/camera0/compressed',
            self.image_callback,
            10)
        
        gst_pipeline = (
            "appsrc ! videoconvert ! "
            "x264enc tune=zerolatency bitrate=2048 speed-preset=ultrafast ! "
            "rtspclientsink location=rtsp://127.0.0.1:8554/cam_t800"
        )
        
        self.out = cv2.VideoWriter(gst_pipeline, cv2.CAP_GSTREAMER, 0, 30, (1280, 1088), True)
        self.first_frame = True

    def image_callback(self, msg):
        if self.first_frame:
            self.get_logger().info("SUCESSO! Primeiro frame da câmera do T800 recebido e injetado no RTSP!")
            self.first_frame = False

        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is not None and self.out.isOpened():
            self.out.write(frame)
        else:
            self.get_logger().warn("Recebeu dados, mas o frame decodificado veio vazio ou GStreamer fechado.")

def main(args=None):
    rclpy.init(args=args)
    node = T800RTSPBridge()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
