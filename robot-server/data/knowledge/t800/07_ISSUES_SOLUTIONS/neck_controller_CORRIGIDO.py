#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controlador Seguro do Pescoço (Motores Q25H - J23 Pitch e J24 Yaw).
Localização: modules_dashboard/neck/neck_controller.py
Módulo Exclusivo com Servidor de Controle REST na porta 5055 e Trajetória Suave 100 Hz.
"""

import os
import sys
import time
import math
import json
import threading
import http.server
import urllib.parse

# Configuração de Rede e Ambiente ROS 2 oficial do T800
os.environ["ROS_DOMAIN_ID"] = os.environ.get("ROS_DOMAIN_ID", "69")
os.environ["ROS_LOCALHOST_ONLY"] = os.environ.get("ROS_LOCALHOST_ONLY", "0")
os.environ["RMW_IMPLEMENTATION"] = os.environ.get("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")
if os.path.exists("/app/applications/install/bringup/cyclonedds.xml"):
    os.environ["CYCLONEDDS_URI"] = "file:///app/applications/install/bringup/cyclonedds.xml"
elif os.path.exists("/home/ubuntu/cyclonedds.xml"):
    os.environ["CYCLONEDDS_URI"] = "file:///home/ubuntu/cyclonedds.xml"

# Índices das juntas no robô humanóide T800
JOINT_HEAD_PITCH = 23
JOINT_HEAD_YAW = 24

# Limites físicos de segurança em radianos
PITCH_MIN = -0.523  # ~ -30°
PITCH_MAX = 0.523   # ~ +30°
YAW_MIN = -1.222    # ~ -70°
YAW_MAX = 1.222     # ~ +70°

KP_GAIN = 100.0     # Rigidez (Stiffness)
KD_GAIN = 3.0       # Amortecimento (Damping)
CONTROL_FREQ = 100.0  # 100 Hz
HTTP_PORT = 5055

# Face-follow por velocidade contínua.
# O app atualiza a intenção; este controlador integra localmente a 100 Hz.
VELOCITY_WATCHDOG_S = 0.35
MAX_PITCH_VELOCITY = 0.40   # rad/s
MAX_YAW_VELOCITY = 0.60     # rad/s
PITCH_ACCEL = 1.60          # rad/s²
YAW_ACCEL = 2.40            # rad/s²

# Tenta carregar ROS 2 e mensagens do protocolo T800
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
    from std_msgs.msg import Header
    from interface_protocol.msg import JointOverrideCommand, JointState, MotionStateRequest
    try:
        from interface_protocol.msg import MotionState, PowerInfo
    except ImportError:
        MotionState = None
        PowerInfo = None
    ROS2_AVAILABLE = True
    print("[NECK] ✅ Módulos ROS 2 e interface_protocol importados com sucesso!")
except ImportError as e:
    print(f"[NECK] ⚠️ ROS 2 ou interface_protocol não disponível ({e}). Operando em modo Mock/Simulação.")

def clamp(val, min_val, max_val):
    return max(min_val, min(max_val, float(val)))

def clamp_angles(pitch_rad: float, yaw_rad: float):
    """Aplica limites rígidos de software para proteger o pescoço e cabeamento."""
    c_pitch = clamp(pitch_rad, PITCH_MIN, PITCH_MAX)
    c_yaw = clamp(yaw_rad, YAW_MIN, YAW_MAX)
    return c_pitch, c_yaw

class NeckTrajectoryController:
    """Controlador de trajetória com interpolação contínua quíntica a 100 Hz."""
    def __init__(self, ros_node=None):
        self.ros_node = ros_node
        self.lock = threading.Lock()
        
        self.current_pitch = 0.0
        self.current_yaw = 0.0
        self.target_pitch = 0.0
        self.target_yaw = 0.0
        
        self.start_pitch = 0.0
        self.start_yaw = 0.0
        self.start_time = 0.0
        self.duration = 1.5
        self.is_moving = False
        
        self.actual_pitch = 0.0
        self.actual_yaw = 0.0
        self.has_received_state = False
        self.last_state_time = 0.0
        
        self.running = True
        self.cmd_pub = None
        self.state_pub = None
        self.balance_mode_active = False
        self.fsm_task = "idle"
        self.bms_relay_enabled = False

        # Estado do controle contínuo por velocidade.
        self.velocity_mode_active = False
        self.desired_pitch_velocity = 0.0
        self.desired_yaw_velocity = 0.0
        self.current_pitch_velocity = 0.0
        self.current_yaw_velocity = 0.0
        self.last_velocity_command = 0.0

        if self.ros_node and ROS2_AVAILABLE:
            self.cmd_pub = self.ros_node.create_publisher(
                JointOverrideCommand, "/motion/joint_override_command", 10
            )
            try:
                self.state_pub = self.ros_node.create_publisher(
                    MotionStateRequest, "/motion/set_motion_state", 10
                )
            except Exception as e:
                print(f"[NECK] Aviso MotionStateRequest: {e}")

            try:
                best_effort_qos = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.VOLATILE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10
                )
                if MotionState is not None:
                    self.ros_node.create_subscription(
                        MotionState, "/motion/motion_state", self.on_motion_state, best_effort_qos
                    )
                if PowerInfo is not None:
                    self.ros_node.create_subscription(
                        PowerInfo, "/hardware/power_info", self.on_power_info, best_effort_qos
                    )
            except Exception as e:
                print(f"[NECK] Aviso ao subscrever tópicos FSM/Power: {e}")

    def on_motion_state(self, msg):
        task = str(getattr(msg, 'current_motion_task', '')).strip().lower()
        with self.lock:
            self.fsm_task = task
            if not task or any(k in task for k in ['idle', 'passive', 'damp', 'standby']):
                if self.balance_mode_active:
                    print(f"[NECK] 🔒 Modo balance desativado: Robô em repouso ('{task.upper() or 'IDLE'}').")
                    self.balance_mode_active = False
                    self.is_moving = False
                    self.target_pitch = 0.0
                    self.target_yaw = 0.0
                    self.velocity_mode_active = False
                    self.desired_pitch_velocity = 0.0
                    self.desired_yaw_velocity = 0.0
                    self.current_pitch_velocity = 0.0
                    self.current_yaw_velocity = 0.0

    def on_power_info(self, msg):
        enabled = bool(getattr(msg, 'enable', False))
        with self.lock:
            self.bms_relay_enabled = enabled
            if not enabled and self.balance_mode_active:
                print("[NECK] 🔒 Modo balance desativado: Relé BMS foi DESLIGADO.")
                self.balance_mode_active = False
                self.is_moving = False
                self.target_pitch = 0.0
                self.target_yaw = 0.0
                self.velocity_mode_active = False
                self.desired_pitch_velocity = 0.0
                self.desired_yaw_velocity = 0.0
                self.current_pitch_velocity = 0.0
                self.current_yaw_velocity = 0.0

    def set_balance_mode(self, active: bool = True):
        if active:
            with self.lock:
                task = self.fsm_task
                bms_on = self.bms_relay_enabled
            
            is_idle = not task or any(k in task for k in ['idle', 'passive', 'damp', 'standby'])
            if ROS2_AVAILABLE:
                if not bms_on:
                    print("[NECK] ⛔ Bloqueio: Relé BMS DESLIGADO! Impossível ativar balance mode.")
                    return False
                if is_idle:
                    print(f"[NECK] ⛔ Bloqueio: Robô em '{task.upper() or 'IDLE'}'. Impossível ativar balance.")
                    return False
            
            # SEGURANÇA CRÍTICA: Sempre que o motor for iniciado, deve partir da posição REAL
            # física atual do hardware e centralizar suavemente no CENTRO (0.0, 0.0).
            # Evita qualquer movimento brusco ou salto para posições residuais anteriores.
            with self.lock:
                start_p = self.actual_pitch if self.has_received_state else self.current_pitch
                start_y = self.actual_yaw if self.has_received_state else self.current_yaw
                
                # Inicia rigorosamente na posição física atual para descontinuidade zero
                self.current_pitch = start_p
                self.current_yaw = start_y
                self.start_pitch = start_p
                self.start_yaw = start_y
                
                # Descarta qualquer comando contínuo antigo ao reativar o motor.
                self.velocity_mode_active = False
                self.desired_pitch_velocity = 0.0
                self.desired_yaw_velocity = 0.0
                self.current_pitch_velocity = 0.0
                self.current_yaw_velocity = 0.0
                self.last_velocity_command = 0.0

                # Alvo de inicialização de segurança: SEMPRE O CENTRO (0, 0)
                self.target_pitch = 0.0
                self.target_yaw = 0.0
                
                # Calcula duração suave (mínimo 1.8s) para transição segura sem jerk
                dist = math.hypot(start_p, start_y)
                self.duration = max(1.8, min(3.0, 1.8 + dist * 2.0))
                self.start_time = time.time()
                self.is_moving = True
                self.balance_mode_active = True
                
                deg_p = round(math.degrees(start_p), 1)
                deg_y = round(math.degrees(start_y), 1)
                print(f"[NECK] 🛡️ INICIALIZAÇÃO SEGURA: Motor acionado. Partindo de ({deg_p}°, {deg_y}°) ➔ Centralizando suave em {round(self.duration, 2)}s.")

            if self.state_pub and ROS2_AVAILABLE:
                try:
                    req = MotionStateRequest()
                    req.target_motion_name = "lower_body_balance"
                    self.state_pub.publish(req)
                    return True
                except Exception as e:
                    print(f"[NECK] ⚠️ Erro /motion/set_motion_state: {e}")
                    return False
            return True
        else:
            with self.lock:
                self.balance_mode_active = False
                self.is_moving = False
                self.target_pitch = 0.0
                self.target_yaw = 0.0
                self.velocity_mode_active = False
                self.desired_pitch_velocity = 0.0
                self.desired_yaw_velocity = 0.0
                self.current_pitch_velocity = 0.0
                self.current_yaw_velocity = 0.0
                print("[NECK] 🛑 Motor da cabeça desativado. Alvos redefinidos para o centro.")
            return True

    def on_hardware_joint_state(self, positions):
        with self.lock:
            if len(positions) > JOINT_HEAD_YAW:
                self.actual_pitch = float(positions[JOINT_HEAD_PITCH])
                self.actual_yaw = float(positions[JOINT_HEAD_YAW])
                if not self.has_received_state:
                    self.current_pitch = self.actual_pitch
                    self.current_yaw = self.actual_yaw
                    # Alvo de segurança inicial é sempre o centro
                    self.target_pitch = 0.0
                    self.target_yaw = 0.0
                    self.has_received_state = True
                self.last_state_time = time.time()

    def set_target(self, target_pitch: float, target_yaw: float, duration: float = 1.5):
        if not self.balance_mode_active:
            print("[NECK] ⚠️ Rejeitado: Modo balance está DESATIVADO.")
            return False

        safe_pitch, safe_yaw = clamp_angles(target_pitch, target_yaw)
        safe_duration = max(0.2, min(5.0, float(duration)))

        with self.lock:
            # /move, /step e /center assumem controle exclusivo.
            self.velocity_mode_active = False
            self.desired_pitch_velocity = 0.0
            self.desired_yaw_velocity = 0.0
            self.current_pitch_velocity = 0.0
            self.current_yaw_velocity = 0.0

            self.start_pitch = self.current_pitch
            self.start_yaw = self.current_yaw
            self.target_pitch = safe_pitch
            self.target_yaw = safe_yaw
            self.start_time = time.time()
            self.duration = safe_duration
            self.is_moving = True
        return True

    def step_target(self, delta_pitch: float, delta_yaw: float, duration: float = 0.4):
        with self.lock:
            new_pitch = self.target_pitch + float(delta_pitch)
            new_yaw = self.target_yaw + float(delta_yaw)
        return self.set_target(new_pitch, new_yaw, duration)

    def center(self, duration: float = 1.5):
        return self.set_target(0.0, 0.0, duration)

    def set_velocity(self, pitch_velocity: float = 0.0, yaw_velocity: float = 0.0):
        """Define a intenção de velocidade usada pelo face-follow.

        A posição é integrada localmente a 100 Hz. Se o app deixar de enviar
        atualizações, o watchdog manda a intenção para zero e o controlador
        desacelera de forma progressiva.
        """
        if not self.balance_mode_active:
            print("[NECK] ⚠️ /velocity rejeitado: Modo balance está DESATIVADO.")
            return False

        if ROS2_AVAILABLE and not self.has_received_state:
            print("[NECK] ⚠️ /velocity rejeitado: ainda sem feedback das juntas.")
            return False

        pitch_velocity = clamp(
            pitch_velocity, -MAX_PITCH_VELOCITY, MAX_PITCH_VELOCITY
        )
        yaw_velocity = clamp(
            yaw_velocity, -MAX_YAW_VELOCITY, MAX_YAW_VELOCITY
        )

        with self.lock:
            # Ao começar o modo contínuo, sincroniza com a posição física real.
            if not self.velocity_mode_active and self.has_received_state:
                self.current_pitch = clamp(self.actual_pitch, PITCH_MIN, PITCH_MAX)
                self.current_yaw = clamp(self.actual_yaw, YAW_MIN, YAW_MAX)

            self.is_moving = False
            self.desired_pitch_velocity = float(pitch_velocity)
            self.desired_yaw_velocity = float(yaw_velocity)
            self.last_velocity_command = time.monotonic()

            requested_motion = (
                abs(self.desired_pitch_velocity) > 1e-6
                or abs(self.desired_yaw_velocity) > 1e-6
            )
            still_braking = (
                abs(self.current_pitch_velocity) > 1e-5
                or abs(self.current_yaw_velocity) > 1e-5
            )
            self.velocity_mode_active = requested_motion or still_braking

        return True

    def stop_velocity(self):
        """Solicita parada suave do modo contínuo."""
        with self.lock:
            self.desired_pitch_velocity = 0.0
            self.desired_yaw_velocity = 0.0
            self.last_velocity_command = time.monotonic()

            if (
                abs(self.current_pitch_velocity) <= 1e-5
                and abs(self.current_yaw_velocity) <= 1e-5
            ):
                self.current_pitch_velocity = 0.0
                self.current_yaw_velocity = 0.0
                self.velocity_mode_active = False

        return True

    def get_status(self):
        with self.lock:
            return {
                "online": True,
                "is_moving": self.is_moving,
                "current_pitch": round(self.current_pitch, 4),
                "current_yaw": round(self.current_yaw, 4),
                "current_pitch_deg": round(math.degrees(self.current_pitch), 2),
                "current_yaw_deg": round(math.degrees(self.current_yaw), 2),
                "target_pitch": round(self.target_pitch, 4),
                "target_yaw": round(self.target_yaw, 4),
                "target_pitch_deg": round(math.degrees(self.target_pitch), 2),
                "target_yaw_deg": round(math.degrees(self.target_yaw), 2),
                "actual_pitch": round(self.actual_pitch, 4),
                "actual_yaw": round(self.actual_yaw, 4),
                "has_hardware_feedback": self.has_received_state,
                "limits": {
                    "pitch_min": PITCH_MIN,
                    "pitch_max": PITCH_MAX,
                    "pitch_min_deg": round(math.degrees(PITCH_MIN), 1),
                    "pitch_max_deg": round(math.degrees(PITCH_MAX), 1),
                    "yaw_min": YAW_MIN,
                    "yaw_max": YAW_MAX,
                    "yaw_min_deg": round(math.degrees(YAW_MIN), 1),
                    "yaw_max_deg": round(math.degrees(YAW_MAX), 1),
                },
                "gains": {"kp": KP_GAIN, "kd": KD_GAIN},
                "velocity_mode_active": self.velocity_mode_active,
                "pitch_velocity": round(self.current_pitch_velocity, 4),
                "yaw_velocity": round(self.current_yaw_velocity, 4),
                "desired_pitch_velocity": round(self.desired_pitch_velocity, 4),
                "desired_yaw_velocity": round(self.desired_yaw_velocity, 4),
                "velocity_watchdog_s": VELOCITY_WATCHDOG_S,
                "velocity_limits": {
                    "pitch": MAX_PITCH_VELOCITY,
                    "yaw": MAX_YAW_VELOCITY,
                    "pitch_accel": PITCH_ACCEL,
                    "yaw_accel": YAW_ACCEL,
                },
                "balance_mode_requested": self.balance_mode_active,
                "balance_mode_active": (
                    self.balance_mode_active
                    and self.bms_relay_enabled
                    and not (not self.fsm_task or any(k in self.fsm_task for k in ['idle', 'passive', 'damp', 'standby']))
                ),
                "fsm_task": self.fsm_task,
                "bms_relay_enabled": self.bms_relay_enabled,
                "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "69")),
                "simulation": not ROS2_AVAILABLE
            }

    def run_control_loop(self):
        nominal_dt = 1.0 / CONTROL_FREQ
        last_tick = time.monotonic()

        def approach(current, target, max_delta):
            if current < target:
                return min(target, current + max_delta)
            if current > target:
                return max(target, current - max_delta)
            return current

        while self.running:
            loop_started = time.monotonic()
            dt = max(0.001, min(0.05, loop_started - last_tick))
            last_tick = loop_started

            with self.lock:
                out_pitch_velocity = 0.0
                out_yaw_velocity = 0.0

                if self.velocity_mode_active:
                    # Watchdog: sem atualização do app, freia até zero.
                    if (
                        self.last_velocity_command <= 0.0
                        or loop_started - self.last_velocity_command > VELOCITY_WATCHDOG_S
                    ):
                        self.desired_pitch_velocity = 0.0
                        self.desired_yaw_velocity = 0.0

                    self.current_pitch_velocity = approach(
                        self.current_pitch_velocity,
                        self.desired_pitch_velocity,
                        PITCH_ACCEL * dt,
                    )
                    self.current_yaw_velocity = approach(
                        self.current_yaw_velocity,
                        self.desired_yaw_velocity,
                        YAW_ACCEL * dt,
                    )

                    next_pitch = (
                        self.current_pitch + self.current_pitch_velocity * dt
                    )
                    next_yaw = (
                        self.current_yaw + self.current_yaw_velocity * dt
                    )
                    safe_pitch, safe_yaw = clamp_angles(next_pitch, next_yaw)

                    # Não deixa a integração empurrar contra um fim de curso.
                    if abs(safe_pitch - next_pitch) > 1e-12:
                        self.current_pitch_velocity = 0.0
                        self.desired_pitch_velocity = 0.0
                    if abs(safe_yaw - next_yaw) > 1e-12:
                        self.current_yaw_velocity = 0.0
                        self.desired_yaw_velocity = 0.0

                    self.current_pitch = safe_pitch
                    self.current_yaw = safe_yaw
                    self.target_pitch = safe_pitch
                    self.target_yaw = safe_yaw

                    out_pitch_velocity = self.current_pitch_velocity
                    out_yaw_velocity = self.current_yaw_velocity

                    if (
                        abs(self.desired_pitch_velocity) <= 1e-6
                        and abs(self.desired_yaw_velocity) <= 1e-6
                        and abs(self.current_pitch_velocity) <= 1e-4
                        and abs(self.current_yaw_velocity) <= 1e-4
                    ):
                        self.current_pitch_velocity = 0.0
                        self.current_yaw_velocity = 0.0
                        self.velocity_mode_active = False
                        out_pitch_velocity = 0.0
                        out_yaw_velocity = 0.0

                elif self.is_moving:
                    now = time.time()
                    elapsed = now - self.start_time
                    t = min(1.0, elapsed / self.duration) if self.duration > 0 else 1.0
                    q = 10 * (t ** 3) - 15 * (t ** 4) + 6 * (t ** 5)
                    self.current_pitch = (
                        self.start_pitch
                        + q * (self.target_pitch - self.start_pitch)
                    )
                    self.current_yaw = (
                        self.start_yaw
                        + q * (self.target_yaw - self.start_yaw)
                    )

                    if t >= 1.0:
                        self.current_pitch = self.target_pitch
                        self.current_yaw = self.target_yaw
                        self.is_moving = False

                cur_p = self.current_pitch
                cur_y = self.current_yaw

            if self.balance_mode_active and self.cmd_pub and ROS2_AVAILABLE:
                try:
                    cmd = JointOverrideCommand()
                    cmd.header = Header()
                    cmd.header.stamp = self.ros_node.get_clock().now().to_msg()
                    cmd.weight = 1.0
                    cmd.joint_indices = [JOINT_HEAD_PITCH, JOINT_HEAD_YAW]
                    cmd.position = [cur_p, cur_y]
                    cmd.velocity = [out_pitch_velocity, out_yaw_velocity]
                    cmd.feed_forward_torque = [0.0, 0.0]
                    cmd.torque = [0.0, 0.0]
                    cmd.stiffness = [KP_GAIN, KP_GAIN]
                    cmd.damping = [KD_GAIN, KD_GAIN]
                    self.cmd_pub.publish(cmd)
                except Exception:
                    pass

            elif not ROS2_AVAILABLE:
                with self.lock:
                    self.actual_pitch = cur_p
                    self.actual_yaw = cur_y
                    self.has_received_state = True

            elapsed_loop = time.monotonic() - loop_started
            time.sleep(max(0.0, nominal_dt - elapsed_loop))

class NeckHttpHandler(http.server.BaseHTTPRequestHandler):
    controller = None

    def log_message(self, format, *args):
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "module": "modules_dashboard.neck"}')
        elif parsed.path == "/status":
            st = self.controller.get_status() if self.controller else {"online": False}
            data = json.dumps(st).encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        
        try:
            body = json.loads(post_body.decode("utf-8")) if post_body else {}
        except Exception:
            body = {}

        if parsed.path == "/move":
            pitch = float(body.get("pitch", 0.0))
            yaw = float(body.get("yaw", 0.0))
            duration = float(body.get("duration", 1.5))
            ok = self.controller.set_target(pitch, yaw, duration) if self.controller else False
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "action": "move"}).encode('utf-8'))

        elif parsed.path == "/step":
            d_pitch = float(body.get("d_pitch", 0.0))
            d_yaw = float(body.get("d_yaw", 0.0))
            duration = float(body.get("duration", 0.4))
            ok = self.controller.step_target(d_pitch, d_yaw, duration) if self.controller else False
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "action": "step"}).encode('utf-8'))

        elif parsed.path == "/center":
            duration = float(body.get("duration", 1.5))
            ok = self.controller.center(duration) if self.controller else False
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": ok, "action": "center"}).encode('utf-8'))

        elif parsed.path == "/velocity":
            pitch_velocity = float(body.get("pitch_velocity", 0.0))
            yaw_velocity = float(body.get("yaw_velocity", 0.0))
            ok = (
                self.controller.set_velocity(pitch_velocity, yaw_velocity)
                if self.controller else False
            )
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": ok,
                "action": "velocity",
                "pitch_velocity": pitch_velocity,
                "yaw_velocity": yaw_velocity
            }).encode("utf-8"))

        elif parsed.path == "/velocity_stop":
            ok = self.controller.stop_velocity() if self.controller else False
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": ok,
                "action": "velocity_stop"
            }).encode("utf-8"))

        elif parsed.path in ["/balance_mode", "/enable_balance"]:
            enable = body.get("enable", True) if isinstance(body, dict) else True
            ok = self.controller.set_balance_mode(enable) if self.controller else False
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({
                "success": ok,
                "balance_mode_active": self.controller.balance_mode_active if self.controller else False,
                "mode": "lower_body_balance" if enable else "disabled"
            }).encode("utf-8")
            self.wfile.write(resp)
        else:
            self.send_response(404)
            self.end_headers()

def start_http_server(controller, port=HTTP_PORT):
    NeckHttpHandler.controller = controller
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), NeckHttpHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd

def main():
    print("=" * 65)
    print("MÓDULO: modules_dashboard/neck/neck_controller.py")
    print(f"🚀 Porta: {HTTP_PORT} (Motores Q25H J23/J24 @ 100 Hz)")
    print("=" * 65)
    
    node = None
    if ROS2_AVAILABLE:
        try:
            rclpy.init(args=None)
            node = Node("safe_neck_controller")
        except Exception:
            node = None

    controller = NeckTrajectoryController(ros_node=node)

    if node and ROS2_AVAILABLE:
        def joint_state_cb(msg):
            if hasattr(msg, "position"):
                controller.on_hardware_joint_state(msg.position)

        hardware_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST
        )
        node.create_subscription(JointState, "/hardware/joint_state", joint_state_cb, hardware_qos)
        node.create_subscription(JointState, "/joint_states", joint_state_cb, hardware_qos)

    control_thread = threading.Thread(target=controller.run_control_loop, daemon=True)
    control_thread.start()

    httpd = start_http_server(controller, HTTP_PORT)

    try:
        if node and ROS2_AVAILABLE:
            rclpy.spin(node)
        else:
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        controller.running = False
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        if node and ROS2_AVAILABLE:
            try:
                node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
            except Exception:
                pass

if __name__ == "__main__":
    main()
