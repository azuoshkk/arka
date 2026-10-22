import sys
import time
import numpy as np

print("DEBUG: A importar bibliotecas ROS2...", flush=True)
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2

print("DEBUG: Bibliotecas importadas com sucesso!", flush=True)


class SimuladorDebug(Node):
    def __init__(self):
        super().__init__('simulador_debug')
        print("DEBUG: Nó ROS2 'simulador_debug' criado.", flush=True)

        self.publisher_ = self.create_publisher(
            CompressedImage,
            '/manifold/odin/device0/camera0/compressed',
            10
        )
        print("DEBUG: Publisher criado no tópico /manifold/odin/device0/camera0/compressed", flush=True)

        self.timer = self.create_timer(1.0 / 30.0, self.timer_callback)
        self.counter = 0
        print("DEBUG: Timer de 30 FPS iniciado com sucesso.", flush=True)

    def timer_callback(self):
        try:
            # Cria um frame sintético direto (sem tocar na webcam física por agora para evitar travamentos)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, f"T800 TEST FRAME: {self.counter}", (30, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

            success, encoded_image = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not success:
                print("DEBUG: Falha ao codificar imagem JPEG.", flush=True)
                return

            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = "jpeg"
            msg.data = np.array(encoded_image).tobytes()

            self.publisher_.publish(msg)
            self.counter += 1

            if self.counter % 30 == 0:
                print(f"DEBUG: Já foram publicados {self.counter} frames com sucesso!", flush=True)
        except Exception as e:
            print(f"DEBUG ERRO no callback: {e}", flush=True)


def main(args=None):
    print("DEBUG: A iniciar rclpy...", flush=True)
    rclpy.init(args=args)
    node = SimuladorDebug()
    print("DEBUG: A entrar no loop rclpy.spin()...", flush=True)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("DEBUG: Interrompido pelo utilizador.", flush=True)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()