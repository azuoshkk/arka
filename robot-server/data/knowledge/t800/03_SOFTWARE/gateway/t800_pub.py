import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import cv2

class T800CameraPublisher(Node):
    def __init__(self):
        super().__init__('t800_camera_publisher')
        self.publisher_ = self.create_publisher(Image, '/t800/camera/raw', 10)
        
        # Força o uso do backend V4L2 (essencial para Linux/Docker)
        self.get_logger().info("A abrir a câmara com o backend V4L2...")
        self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        
        if not self.cap.isOpened():
            self.get_logger().error("ERRO CRÍTICO: Não foi possível abrir a câmara /dev/video0!")
        else:
            self.get_logger().info("Câmara aberta com sucesso!")
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        self.timer = self.create_timer(1.0 / 30.0, self.timer_callback)
        self.frame_count = 0

    def timer_callback(self):
        ret, frame = self.cap.read()
        if not ret or frame is None:
            if self.frame_count == 0:
                self.get_logger().warn("Aviso: A câmara abriu, mas o primeiro frame veio vazio (preto). A tentar ler...")
            return

        self.frame_count += 1
        if self.frame_count % 30 == 0:
            self.get_logger().info(f"Frame {self.frame_count} lido e publicado com sucesso (Shape: {frame.shape})")

        # Converte o frame cru para mensagem ROS2 Image
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera_frame'
        msg.height = frame.shape[0]
        msg.width = frame.shape[1]
        msg.encoding = 'bgr8'
        msg.step = frame.shape[1] * 3
        msg.data = frame.tobytes()

        self.publisher_.publish(msg)

    def destroy_node(self):
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = T800CameraPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
