"""Adaptador para o protocolo realmente encontrado no Orin, sem troca de modo corporal."""
import time
import secrets


class RosBackend:
    TOPIC = '/motion/joint_override_command'

    def __init__(self, controller, lock):
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from interface_protocol.msg import JointOverrideCommand, JointState, MotionState
        self.rclpy, self.Message = rclpy, JointOverrideCommand
        self.controller, self.lock = controller, lock
        rclpy.init()
        self.node = rclpy.create_node('headfollow_' + secrets.token_hex(4))
        self.pub = None  # Leitura não cria publicador, nem envia weight=0.
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.node.create_subscription(JointState, '/hardware/joint_state', self.feedback, qos)
        self.node.create_subscription(MotionState, '/motion/motion_state', self.motion, qos)
        self.last_graph = -10.

    def feedback(self, msg):
        with self.lock:
            try:
                self.controller.feedback(msg.position)
            except ValueError:
                self.controller.actual = None

    def motion(self, msg):
        with self.lock:
            self.controller.motion_feedback(msg.current_motion_task)

    def step(self):
        self.rclpy.spin_once(self.node, timeout_sec=0.)
        now = time.monotonic()
        if now-self.last_graph > .2:
            conflicts = [p.node_name for p in self.node.get_publishers_info_by_topic(self.TOPIC)
                         if p.node_name != self.node.get_name()]
            with self.lock:
                self.controller.conflicts = conflicts
                self.controller.subscribers = self.node.count_subscribers(self.TOPIC)
            self.last_graph = now
        with self.lock:
            packet = self.controller.tick()
        if packet is not None:
            if self.pub is None:
                from rclpy.qos import QoSProfile, ReliabilityPolicy
                self.pub = self.node.create_publisher(self.Message, self.TOPIC,
                    QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE))
            msg = self.Message()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            for key, value in packet.items():
                setattr(msg, key, value)
            self.pub.publish(msg)

    def close(self):
        with self.lock:
            self.controller.disarm('Servidor encerrado.')
        # Liberação é tentativa de devolução de controle, não parada física garantida.
        try:
            for _ in range(5):
                self.step()
                time.sleep(.02)
        finally:
            self.node.destroy_node()
            if self.rclpy.ok():
                self.rclpy.shutdown()
