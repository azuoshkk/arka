import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2
import sys

class T800Simulator(Node):
    def __init__(self):
        super().__init__('t800_simulator_node')
        
        # Cria o publicador idêntico ao do T800
        self.publisher_ = self.create_publisher(CompressedImage, '/camera0/compressed', 10)
        
        # Abre a webcam do computador (0 é normalmente a câmara padrão)
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            self.get_logger().error("Não foi possível abrir a webcam!")
            sys.exit(1)
            
        # Define a resolução e os frames por segundo (30 FPS)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        timer_period = 1.0 / 30.0  
        
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.get_logger().info("🤖 T800 Simulado Online! A publicar a webcam no tópico /camera0/compressed...")

    def timer_callback(self):
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warning("Falha ao capturar a imagem da webcam.")
            return

        # Comprime a imagem para JPEG (O padrão do T800)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        success, encoded_image = cv2.imencode('.jpg', frame, encode_param)
        
        if success:
            # Cria a mensagem ROS2
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera_link"
            msg.format = "jpeg"
            msg.data = encoded_image.tobytes()
            
            # Publica na rede
            self.publisher_.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = T800Simulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cap.release()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
