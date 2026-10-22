#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashgroup Arcanjo — Orquestrador Central ROS 2 WebSocket Bridge
Nó central para comunicação bidirecional de telemetria, visão e controle.
"""

import os
import sys
import time
import json
import socket
import asyncio
import threading
import subprocess
import argparse
import shlex
import base64
from datetime import datetime
from typing import Dict, Any, Optional, Callable

# ==============================================================================
# AUTO-BOOTSTRAP DO AMBIENTE ROS 2 E WORKSPACE (T800 / NVIDIA AGX ORIN)
# ==============================================================================
if os.environ.get("_ROS2_BOOTSTRAPPED") != "1":
    need_bootstrap = False
    try:
        import rclpy
        if "AMENT_PREFIX_PATH" not in os.environ:
            need_bootstrap = True
    except (ImportError, ModuleNotFoundError):
        need_bootstrap = True

    if need_bootstrap:
        setup_candidates = ["/opt/ros/humble/setup.bash", "/opt/ros/foxy/setup.bash"]
        ws_candidates = [
            os.path.expanduser("~/engineai_workspace-2"),
            "/home/ubuntu/engineai_workspace-2",
            "/app/applications",
            os.path.expanduser("~/engineai_workspace"),
            os.path.expanduser("~/Downloads/engineai_workspace-2"),
        ]
        source_cmds = [f"source {c}" for c in setup_candidates if os.path.exists(c)][:1]
        if source_cmds:
            for ws in ws_candidates:
                ws_setup = os.path.join(ws, "install/setup.bash")
                if os.path.exists(ws_setup):
                    source_cmds.append(f"source {ws_setup}")
                    env_sh = os.path.join(ws, "src/interface_example/scripts/env.sh")
                    if os.path.exists(env_sh):
                        source_cmds.append(f"source {env_sh}")
                    break
            print("[ORQUESTRADOR] ⚡ Auto-carregando ambiente ROS 2 e workspace do robô T800...")
            cmd = " && ".join(source_cmds) + f" && export _ROS2_BOOTSTRAPPED=1 && exec {sys.executable} " + " ".join(shlex.quote(a) for a in sys.argv)
            os.execlp("bash", "bash", "-c", cmd)

# ==============================================================================
# PARSE DE ARGUMENTOS CLI & CONFIGURAÇÕES DE REDE DDS
# ==============================================================================
parser = argparse.ArgumentParser(description="Dashgroup Arcanjo — Orquestrador Central ROS 2 WebSocket Bridge")
parser.add_argument("--domain", "-d", type=str, default=None, help="Força ROS_DOMAIN_ID (ex: 69 ou 0)")
parser.add_argument("--rmw", type=str, default=None, help="Força RMW_IMPLEMENTATION (ex: rmw_cyclonedds_cpp)")
parser.add_argument("--port", "-p", type=int, default=8090, help="Porta WebSocket (padrão: 8090)")
parser.add_argument("--no-clear", action="store_true", help="Não limpa terminal")
cli_args, _ = parser.parse_known_args()

os.environ["ROS_DOMAIN_ID"] = str(cli_args.domain or os.environ.get("ROS_DOMAIN_ID", "69"))
os.environ["RMW_IMPLEMENTATION"] = str(cli_args.rmw or os.environ.get("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp"))
os.environ["ROS_LOCALHOST_ONLY"] = os.environ.get("ROS_LOCALHOST_ONLY", "0")

if "CYCLONEDDS_URI" not in os.environ:
    for cpath in ["/app/applications/install/bringup/cyclonedds.xml", "/home/ubuntu/cyclonedds.xml", os.path.expanduser("~/cyclonedds.xml"), "/home/ubuntu/engineai_workspace-2/cyclonedds.xml"]:
        if os.path.exists(cpath):
            os.environ["CYCLONEDDS_URI"] = f"file://{cpath}"
            break

# Inclusão de caminhos no sys.path
DASHBOARD_ROOT = os.path.dirname(os.path.abspath(__file__))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

for p in [
    "/opt/ros/humble/local/lib/python3.10/dist-packages",
    "/opt/ros/humble/lib/python3.10/site-packages",
    "/home/ubuntu/engineai_workspace-2/install/interface_protocol/local/lib/python3.10/dist-packages",
    os.path.expanduser("~/engineai_workspace-2/install/interface_protocol/local/lib/python3.10/dist-packages"),
]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.append(p)

# ==============================================================================
# IMPORTAÇÃO DOS MÓDULOS DE 'modules_dashboard'
# ==============================================================================
from modules_dashboard.manager.process_manager import ProcessManager
from modules_dashboard.audio.audio_service import AudioCaptureService
from modules_dashboard.speech.speech_manager import SpeechManager
from modules_dashboard.neck.neck_manager import NeckManager
from modules_dashboard.camera.camera_service import CameraService, get_camera_key
from modules_dashboard.sensors.sensor_service import SensorService
from modules_dashboard.telemetry.telemetry_service import TelemetryService

try:
    from modules_dashboard.map3d import MapStream
except ImportError:
    MapStream = None

# ==============================================================================
# IMPORTAÇÃO CONDICIONAL DE ROS 2 E PROTOCOLO T800
# ==============================================================================
ROS2_AVAILABLE = False
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
    from rclpy.callback_groups import ReentrantCallbackGroup
    from sensor_msgs.msg import Imu, JointState, CompressedImage, Image, LaserScan, PointCloud2, CameraInfo, BatteryState, Joy
    from nav_msgs.msg import Odometry, OccupancyGrid
    from std_msgs.msg import String, Bool
    ROS2_AVAILABLE = True
except ImportError:
    OccupancyGrid = ReentrantCallbackGroup = None

PowerInfo = MotionState = JointMotionPlanState = MotorDebug = ImuInfo = GamepadKeys = Heartbeat = LedControl = InterfaceJointState = None
try:
    from interface_protocol.msg import PowerInfo, MotionState, JointMotionPlanState, MotorDebug, ImuInfo, GamepadKeys, Heartbeat, LedControl
    from interface_protocol.msg import JointState as InterfaceJointState
except ImportError:
    pass

try:
    import websockets
except ImportError:
    print("[ERRO] 'websockets' não instalado. Execute: pip3 install websockets")
    sys.exit(1)

PORT = cli_args.port
TELEMETRY_BROADCAST_RATE = 15.0  # Telemetria em 15 Hz (economiza CPU/JSON, vídeo corre desacoplado a 30+ FPS)
TOPIC_SCAN_INTERVAL = 3.0

PRIORITY_TOPICS: Dict[str, str] = {
    "/manifold/ODIN2/device0/camera0/compressed": "sensor_msgs/msg/CompressedImage",
    "/manifold/ODIN2/device0/camera1/compressed": "sensor_msgs/msg/CompressedImage",
    "/manifold/ODIN2/device0/reprojection/overlay": "sensor_msgs/msg/Image",
    "/manifold/ODIN2/device0/reprojection/overlay/compressed": "sensor_msgs/msg/CompressedImage",
    "/pessoas/imagem_anotada/compressed": "sensor_msgs/msg/CompressedImage",
    "/manifold/ODIN2/device0/camera0/camera_info": "sensor_msgs/msg/CameraInfo",
    "/manifold/ODIN2/device0/gray": "sensor_msgs/msg/Image",
    "/manifold/ODIN2/device0/imu": "sensor_msgs/msg/Imu",
    "/manifold/ODIN2/device0/odometry": "nav_msgs/msg/Odometry",
    "/manifold/ODIN2/device0/odometry_hf": "nav_msgs/msg/Odometry",
    "/hardware/power_info": "interface_protocol/msg/PowerInfo",
    "/motion/motion_state": "interface_protocol/msg/MotionState",
    "/motion/joint_motion_plan/state": "interface_protocol/msg/JointMotionPlanState",
    "/hardware/motor_debug": "interface_protocol/msg/MotorDebug",
    "/hardware/imu_info": "interface_protocol/msg/ImuInfo",
    "/hardware/gamepad_keys": "interface_protocol/msg/GamepadKeys",
    "/hardware/joint_state": "interface_protocol/msg/JointState",
    "/joint_states": "sensor_msgs/msg/JointState",
    "/heartbeat": "interface_protocol/msg/Heartbeat",
    "/data_recorder/bag_status": "std_msgs/msg/String",
    "/battery_state": "sensor_msgs/msg/BatteryState",
    "/joy": "sensor_msgs/msg/Joy"
}

def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "192.168.0.162"

# ==============================================================================
# NÓ CENTRAL ORQUESTRADOR ROS 2
# ==============================================================================
class RosBridgeOrchestrator(Node if ROS2_AVAILABLE else object):
    def __init__(self, port: int, local_ip: str, process_manager: ProcessManager):
        if ROS2_AVAILABLE:
            super().__init__('ros2_websocket_bridge')
            self.cb_group = ReentrantCallbackGroup() if ReentrantCallbackGroup is not None else None
        else:
            self.cb_group = None

        self.port = port
        self.local_ip = local_ip
        self.process_manager = process_manager
        self.start_time = time.time()
        self.lock = threading.RLock()

        self.ws_status = "RUNNING (NO CLIENTS)"
        self.total_topics_found = 0
        self.connected_clients = set()
        self.dashboard_logs = []
        self.frame_count = 0
        self.priority_topics = set(PRIORITY_TOPICS.keys())
        self.subscriptions_map: Dict[str, Dict[str, Any]] = {}

        # Módulos especializados
        self.audio_service: AudioCaptureService = process_manager.modules["audio"]
        self.speech_manager: SpeechManager = process_manager.modules["speech"]
        self.neck_manager: NeckManager = process_manager.modules["neck"]
        self.camera_service: CameraService = process_manager.modules["camera"]
        self.sensor_service: SensorService = process_manager.modules["sensors"]
        self.telemetry_service: TelemetryService = process_manager.modules["telemetry"]

        # Força protocolo binário Zero-Copy desde a inicialização
        self.camera_service.set_stream_mode("binary")

        self.map_stream = MapStream(ros_node=self if ROS2_AVAILABLE else None, logger=self.log) if MapStream else None
        if self.map_stream:
            try:
                from modules_dashboard.camera.video_recorder import RecorderHttpHandler
                RecorderHttpHandler.scan_manager = self.map_stream.scan_manager
            except Exception:
                pass

        self.log("Orquestrador central inicializado com sucesso.")

        if ROS2_AVAILABLE:
            for top_name, top_type in PRIORITY_TOPICS.items():
                if self.get_msg_class(top_type) is not None:
                    self.subscribe_to_topic(top_name, top_type)

            timer_kwargs = {'callback_group': self.cb_group} if self.cb_group else {}
            self.auto_discover_timer = self.create_timer(TOPIC_SCAN_INTERVAL, self.discover_and_subscribe, **timer_kwargs)
            self.discover_and_subscribe()

    def log(self, message: str, level: str = "INFO"):
        t_str = datetime.now().strftime("%H:%M:%S")
        entry = f"[{t_str}] [ORQUESTRADOR] {message}"
        self.dashboard_logs.append(entry)
        if len(self.dashboard_logs) > 10:
            self.dashboard_logs.pop(0)

    def get_msg_class(self, msg_type_str: str):
        if not ROS2_AVAILABLE:
            return None
        mapping = {
            'sensor_msgs/msg/Imu': Imu,
            'sensor_msgs/msg/JointState': JointState,
            'sensor_msgs/msg/CompressedImage': CompressedImage,
            'sensor_msgs/msg/Image': Image,
            'sensor_msgs/msg/LaserScan': LaserScan,
            'sensor_msgs/msg/PointCloud2': PointCloud2,
            'sensor_msgs/msg/CameraInfo': CameraInfo,
            'sensor_msgs/msg/BatteryState': BatteryState,
            'sensor_msgs/msg/Joy': Joy,
            'nav_msgs/msg/Odometry': Odometry,
            'nav_msgs/msg/OccupancyGrid': OccupancyGrid,
            'std_msgs/msg/String': String,
            'std_msgs/msg/Bool': Bool,
        }
        for name, cls in [
            ('interface_protocol/msg/PowerInfo', PowerInfo),
            ('interface_protocol/msg/MotionState', MotionState),
            ('interface_protocol/msg/JointMotionPlanState', JointMotionPlanState),
            ('interface_protocol/msg/MotorDebug', MotorDebug),
            ('interface_protocol/msg/ImuInfo', ImuInfo),
            ('interface_protocol/msg/GamepadKeys', GamepadKeys),
            ('interface_protocol/msg/Heartbeat', Heartbeat),
            ('interface_protocol/msg/JointState', InterfaceJointState),
            ('interface_protocol/msg/LedControl', LedControl),
        ]:
            if cls is not None:
                mapping[name] = cls
        return mapping.get(msg_type_str, None)

    def discover_and_subscribe(self):
        if not ROS2_AVAILABLE:
            return
        try:
            names_and_types = self.get_topic_names_and_types()
            self.total_topics_found = len(names_and_types)

            # Watchdogs
            has_cam = any(self.count_publishers(t) > 0 for t in ['/manifold/ODIN2/device0/camera0/compressed', '/manifold/ODIN2/device0/camera1/compressed'])
            self.camera_service.check_and_start_driver(has_publishers=has_cam)
            self.speech_manager.check_watchdog()
            self.neck_manager.check_watchdog()

            active_topics = {t[0]: t[1][0] for t in names_and_types if t[1]}
            for t_name, t_type in active_topics.items():
                if t_name in self.priority_topics:
                    self.subscribe_to_topic(t_name, t_type)
                else:
                    nl, tl = t_name.lower(), t_type.lower()
                    if any(k in nl for k in ['imu', 'odom', 'scan', 'cloud', 'joint', 'battery', 'joy', 'gamepad']):
                        self.subscribe_to_topic(t_name, t_type)

            for t_name in list(self.subscriptions_map.keys()):
                if t_name not in active_topics and t_name not in self.priority_topics:
                    self.unsubscribe_from_topic(t_name)
        except Exception as e:
            self.log(f"Erro auto-descoberta: {e}")

    def _resolve_raw_callback(self, msg_class, topic_name: str):
        if msg_class == CompressedImage:
            return lambda msg, t=topic_name: self.camera_service.process_compressed_image(msg, t)
        elif msg_class == Image:
            return lambda msg, t=topic_name: self.camera_service.process_raw_image(msg, t)
        elif msg_class == CameraInfo:
            return lambda msg, t=topic_name: self.camera_service.process_camera_info(msg, t)
        elif msg_class == Imu:
            return lambda msg, t=topic_name: self.sensor_service.process_imu_standard(msg, t)
        elif ImuInfo is not None and msg_class == ImuInfo:
            return lambda msg, t=topic_name: self.sensor_service.process_imu_info(msg, t)
        elif msg_class == Odometry:
            if 'lidar2cam' in topic_name or 'lidar2imu' in topic_name:
                return lambda msg, t=topic_name: self.sensor_service.process_calibration(msg, t)
            def _odom_cb(msg, t=topic_name):
                self.sensor_service.process_odometry(msg, t)
                if self.map_stream and self.map_stream.odom_sub:
                    self.map_stream.odom_sub._handle_odometry(msg)
            return _odom_cb
        elif LaserScan is not None and msg_class == LaserScan:
            return lambda msg: self.sensor_service.process_laser_scan(msg)
        elif PointCloud2 is not None and msg_class == PointCloud2:
            def _cloud_cb(msg, t=topic_name):
                self.sensor_service.process_point_cloud(msg, t)
                if self.camera_service.is_camera_active('overlay'):
                    self.camera_service.update_point_cloud(msg)
            return _cloud_cb
        elif msg_class == BatteryState:
            return lambda msg: self.telemetry_service.process_battery_state(msg)
        elif PowerInfo is not None and msg_class == PowerInfo:
            return lambda msg: self.telemetry_service.process_power_info(msg)
        elif MotionState is not None and msg_class == MotionState:
            return lambda msg: self.telemetry_service.process_motion_state(msg)
        elif JointMotionPlanState is not None and msg_class == JointMotionPlanState:
            return lambda msg: self.telemetry_service.process_motion_plan_state(msg)
        elif MotorDebug is not None and msg_class == MotorDebug:
            return lambda msg: self.telemetry_service.process_motor_debug(msg)
        elif GamepadKeys is not None and msg_class == GamepadKeys:
            return lambda msg: self.telemetry_service.process_gamepad_keys(msg)
        elif Heartbeat is not None and msg_class == Heartbeat:
            return lambda msg: self.telemetry_service.process_heartbeat(msg)
        elif msg_class == Joy:
            return lambda msg: self.telemetry_service.process_joy(msg)
        elif msg_class == JointState or (InterfaceJointState is not None and msg_class == InterfaceJointState):
            return lambda msg: self.telemetry_service.process_joint_states(msg)
        elif msg_class == String:
            if 'bag_status' in topic_name:
                return lambda msg: self.telemetry_service.process_bag_status(str(msg.data))
            return lambda msg, t=topic_name: self.telemetry_service.process_system_driver_string(t, str(msg.data))
        elif msg_class == Bool:
            return lambda msg, t=topic_name: self.telemetry_service.process_system_driver_bool(t, bool(msg.data))
        return None

    def subscribe_to_topic(self, topic_name: str, msg_type_str: str):
        if topic_name in self.subscriptions_map:
            if self.subscriptions_map[topic_name].get('type') == msg_type_str:
                return
            self.unsubscribe_from_topic(topic_name)

        msg_class = self.get_msg_class(msg_type_str)
        if not msg_class:
            return

        raw_cb = self._resolve_raw_callback(msg_class, topic_name)

        def callback(msg, t=topic_name, target=raw_cb):
            info = self.subscriptions_map.get(t)
            if info:
                info['msg_count'] += 1
                info['last_msg_time'] = time.time()
            if target:
                try:
                    target(msg)
                except Exception as ex:
                    self.log(f"Erro callback {t}: {ex}")

        try:
            depth = 10 if any(k in topic_name.lower() for k in ['hardware', 'motion', 'joint']) else (1 if msg_class in [String, Bool, CameraInfo, Joy] else 5)
            qos = QoSProfile(
                reliability=ReliabilityPolicy.RELIABLE if msg_class in [String, Bool, CameraInfo, Joy] else ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
                history=HistoryPolicy.KEEP_LAST,
                depth=depth
            )
            sub_kwargs = {'callback_group': self.cb_group} if self.cb_group else {}
            sub = self.create_subscription(msg_class, topic_name, callback, qos, **sub_kwargs)
            self.subscriptions_map[topic_name] = {
                'sub': sub,
                'msg_count': 0,
                'type': msg_type_str,
                'last_msg_time': 0.0,
                'rate_hz': 0.0
            }
        except Exception as e:
            self.log(f"Falha ao assinar {topic_name}: {e}")

    def unsubscribe_from_topic(self, topic_name: str):
        if topic_name in self.subscriptions_map:
            try:
                self.destroy_subscription(self.subscriptions_map[topic_name]['sub'])
            except Exception:
                pass
            del self.subscriptions_map[topic_name]

    def get_telemetry_payload(self) -> Dict[str, Any]:
        self.frame_count += 1
        is_slow_frame = (self.frame_count % 15 == 0)

        cameras_payload = self.camera_service.extract_pending_cameras()
        camera_info_payload = self.camera_service.get_camera_info_payload()
        camera_stats_payload = self.camera_service.get_camera_stats_payload()

        audio_bytes, mic_vol = self.audio_service.get_and_clear_audio()
        audio_payload = {
            "pcm": base64.b64encode(audio_bytes).decode('utf-8') if audio_bytes else None,
            "sample_rate": self.audio_service.sample_rate,
            "channels": self.audio_service.channels,
            "volume_level": mic_vol
        }

        sensor_snap = self.sensor_service.get_telemetry_snapshot()
        telem_snap = self.telemetry_service.get_telemetry_snapshot(is_slow_frame=is_slow_frame)

        p_info = telem_snap.get("power") or telem_snap.get("battery") or {}
        bms_on = bool(p_info.get("enable", False)) if isinstance(p_info, dict) else False
        m_state = telem_snap.get("motion_state") or {}
        curr_task = str(m_state.get("current_motion_task", "")) if isinstance(m_state, dict) else ""

        neck_payload = self.neck_manager.get_telemetry_snapshot(
            bms_enabled=bms_on,
            current_task=curr_task,
            joints_data=telem_snap.get("joints")
        )

        now = time.time()
        status_map = {}
        for topic, info in self.subscriptions_map.items():
            last_time = info.get('last_msg_time', 0.0)
            cnt = info.get('msg_count', 0)
            elapsed = round(now - last_time, 1) if last_time > 0 else None
            is_conn = (elapsed is not None and elapsed < 3.0)
            status_map[topic] = {
                "connected": is_conn,
                "msgs": cnt,
                "rate_hz": info.get('rate_hz', 0.0) if is_conn else 0.0,
                "last_msg_time": last_time,
                "elapsed_sec": elapsed,
                "state": "ONLINE" if is_conn else ("TIMEOUT" if cnt > 0 else "INACTIVE")
            }

        payload = {
            "timestamp": now,
            "connection_status": "CONNECTED",
            "cameras": cameras_payload,
            "camera_info": camera_info_payload,
            "camera_stats": camera_stats_payload,
            "audio": audio_payload,
            "battery": telem_snap.get("battery"),
            "power": telem_snap.get("power"),
            "imu": sensor_snap.get("imu"),
            "imu_torso": sensor_snap.get("imu_torso"),
            "imu_head": sensor_snap.get("imu_head"),
            "cloud_mode": sensor_snap.get("cloud_mode", "raw"),
            "quaternion": sensor_snap.get("quaternion"),
            "odometry": sensor_snap.get("odometry"),
            "cloud_points": None,
            "gamepad": telem_snap.get("gamepad"),
            "bag_recorder": telem_snap.get("bag_recorder"),
            "status": status_map,
            "neck": neck_payload,
            "motion_state": telem_snap.get("motion_state"),
            "motion_plan": telem_snap.get("motion_plan"),
            "motors_debug": telem_snap.get("motors_debug"),
            "heartbeats": telem_snap.get("heartbeats"),
            "modules_status": self.process_manager.get_all_status()
        }

        if is_slow_frame:
            payload["joints"] = telem_snap.get("joints")
            payload["system"] = telem_snap.get("system")
            payload["node_status"] = {
                "active_topics_count": len(self.subscriptions_map),
                "connected_ws_clients": len(self.connected_clients),
                "uptime_seconds": time.time() - self.start_time
            }

        return payload

# ==============================================================================
# DESPACHADOR CENTRAL DE AÇÕES WEBSOCKET
# ==============================================================================
async def handle_client_action(orchestrator: RosBridgeOrchestrator, websocket, action: str, data: Dict[str, Any], send_func: Optional[Callable] = None):
    async def _send_resp(msg_data: str):
        if send_func:
            await send_func(msg_data)
        else:
            await websocket.send(msg_data)

    if action == "speak":
        orchestrator.speech_manager.speak_text(data.get("text", "").strip(), voice=data.get("voice", "pt-BR-AntonioNeural"), speed=str(data.get("speed", "+20%")))
    elif action == "start_recording":
        orchestrator.camera_service.video_recorder.start(camera=data.get("camera", orchestrator.camera_service.active_cam), fps=data.get("fps", 30.0))
    elif action == "stop_recording":
        orchestrator.camera_service.video_recorder.stop()
    elif action in ["set_camera_config", "set_camera_quality"]:
        w = data.get("target_width") or data.get("target_image_width")
        q = data.get("jpeg_quality")
        fps = data.get("max_fps") or data.get("fps")
        orchestrator.camera_service.set_camera_config(w, q, max_fps=fps)
    elif action in ["set_camera_stream_mode", "set_stream_mode"]:
        orchestrator.camera_service.set_stream_mode(str(data.get("mode", "binary")).lower())
    elif action == "set_active_view":
        tab = data.get("active_tab")
        orchestrator.camera_service.set_active_view(tab, data.get("active_cam"))
        if orchestrator.map_stream:
            orchestrator.map_stream.set_active_tab(tab)
    elif action in ["neck_move", "neck_control"]:
        orchestrator.neck_manager.send_command("move", {"pitch": float(data.get("pitch", 0.0)), "yaw": float(data.get("yaw", 0.0)), "duration": float(data.get("duration", 1.5))})
    elif action == "neck_step":
        orchestrator.neck_manager.send_command("step", {"d_pitch": float(data.get("d_pitch", 0.0)), "d_yaw": float(data.get("d_yaw", 0.0)), "duration": float(data.get("duration", 0.4))})
    elif action == "neck_center":
        orchestrator.neck_manager.send_command("center", {"duration": float(data.get("duration", 1.5))})
    elif action in ["neck_balance", "neck_balance_mode", "enable_balance"]:
        enable = bool(data.get("enable", True))
        p_info = orchestrator.telemetry_service.power_data or {}
        bms_on = bool(p_info.get("enable", False)) if isinstance(p_info, dict) else False
        m_state = orchestrator.telemetry_service.motion_state or {}
        curr_task = str(m_state.get("current_motion_task", "")) if isinstance(m_state, dict) else ""
        is_safe, reason = orchestrator.neck_manager.validate_safety_interlock(enable, bms_on, curr_task)
        if is_safe:
            orchestrator.neck_manager.send_command("balance_mode", {"enable": enable})
        else:
            orchestrator.log(f"⛔ Intertravamento rejeitou balance: {reason}")
    elif action in ["set_led", "led_control"]:
        orchestrator.telemetry_service.set_led_control(int(data.get("color", 5)))
    elif action in ["start_bag_recording", "bag_record"]:
        orchestrator.telemetry_service.start_bag_recording(str(data.get("filename", "")).strip())
    elif action in ["stop_bag_recording", "bag_stop"]:
        orchestrator.telemetry_service.stop_bag_recording()
    elif action == "ping":
        client_ts = data.get("timestamp", time.time() * 1000)
        await _send_resp(json.dumps({"type": "pong", "client_timestamp": client_ts, "server_timestamp": time.time() * 1000}))
    elif action == "query_ros_topics":
        topics = orchestrator.get_topic_names_and_types() if ROS2_AVAILABLE else []
        await _send_resp(json.dumps({"type": "ros_topics_list", "topics": topics}))
    elif action == "query_topic_info":
        target = data.get("topic", "")
        pubs = [{"node_name": p.node_name, "node_namespace": p.node_namespace, "topic_type": p.topic_type} for p in orchestrator.get_publishers_info_by_topic(target)] if (ROS2_AVAILABLE and target) else []
        await _send_resp(json.dumps({"type": "topic_info_res", "topic": target, "publishers": pubs}))
    elif action == "query_system_cmd":
        cmd = data.get("cmd", "")
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            out = res.stdout if res.stdout else res.stderr
        except Exception as e:
            out = str(e)
        await _send_resp(json.dumps({"type": "system_cmd_res", "cmd": cmd, "output": out}))
    elif action and action.startswith("map_3d/") and orchestrator.map_stream:
        resp = orchestrator.map_stream.handle_action(action, data)
        if resp:
            await _send_resp(json.dumps(resp))

# ==============================================================================
# LOOP PRINCIPAL WEBSOCKET
# ==============================================================================
async def main_ws_loop(orchestrator: RosBridgeOrchestrator, port: int):
    loop = asyncio.get_running_loop()
    # Fila atômica latest-wins: tamanho 1 garante 0 ms de delay acumulado de buffer
    camera_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    client_locks: Dict[Any, asyncio.Lock] = {}

    def on_camera_frame_ready(bframe: bytes):
        if not orchestrator.connected_clients:
            return
        def _enqueue():
            while not camera_queue.empty():
                try:
                    camera_queue.get_nowait()
                except Exception:
                    break
            try:
                camera_queue.put_nowait(bframe)
            except Exception:
                pass
        try:
            loop.call_soon_threadsafe(_enqueue)
        except Exception:
            pass

    orchestrator.camera_service.set_frame_callback(on_camera_frame_ready)

    async def safe_send_direct(client, data: Any, timeout: float = 1.0):
        """Envio direto de alta performance para WebSockets sem cancelamentos prematuros."""
        if not getattr(client, 'open', True):
            return
        try:
            await asyncio.wait_for(client.send(data), timeout=timeout)
        except Exception:
            pass

    async def camera_stream_loop():
        """Despacho binário de vídeo 30+ FPS em tempo real em alta performance e qualidade nativa (1280px)."""
        while True:
            try:
                bframe = await camera_queue.get()
                if orchestrator.connected_clients:
                    clients = [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
                    if clients:
                        await asyncio.gather(*[safe_send_direct(c, bframe, timeout=1.0) for c in clients], return_exceptions=True)
            except Exception as e:
                orchestrator.log(f"Erro camera_stream_loop: {e}")

    async def broadcast_loop():
        """Broadcast de telemetria a 15 Hz e 3D Pointcloud sob demanda."""
        interval = 1.0 / TELEMETRY_BROADCAST_RATE
        while True:
            await asyncio.sleep(interval)
            if not orchestrator.connected_clients:
                continue

            orchestrator.camera_service.pop_pending_binary_frames()

            # 1. Telemetria Geral (JSON)
            try:
                payload = orchestrator.get_telemetry_payload()
                msg = json.dumps(payload)
                clients = [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
                if clients:
                    await asyncio.gather(*[safe_send_direct(c, msg, timeout=1.0) for c in clients], return_exceptions=True)
            except Exception as e:
                orchestrator.log(f"Erro broadcast: {e}")

            # 2. Frames 3D Pointcloud sob demanda
            if orchestrator.map_stream:
                try:
                    bin_frames = orchestrator.map_stream.pop_pending_binary_frames()
                    if bin_frames:
                        clients = [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
                        if clients:
                            for bframe in bin_frames:
                                await asyncio.gather(*[safe_send_direct(c, bframe, timeout=1.0) for c in clients], return_exceptions=True)

                    for evt in orchestrator.map_stream.pop_pending_events():
                        evt_msg = json.dumps(evt)
                        clients = [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
                        if clients:
                            await asyncio.gather(*[safe_send_direct(c, evt_msg, timeout=1.0) for c in clients], return_exceptions=True)
                except Exception:
                    pass

    async def heartbeat_log_loop():
        """Log periódico leve no terminal a cada 5s sem travar CPU ou forkar subshell."""
        while True:
            await asyncio.sleep(5.0)
            c_count = len(orchestrator.connected_clients)
            top_count = len(orchestrator.subscriptions_map)
            uptime = int(time.time() - orchestrator.start_time)
            print(f"[STATUS] Uptime: {uptime}s | Clientes WS: {c_count} | Tópicos DDS: {top_count} | Tx: {TELEMETRY_BROADCAST_RATE}Hz")

    async def handler(websocket, path=None):
        try:
            sock = websocket.transport.get_extra_info('socket')
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

        client_locks[websocket] = asyncio.Lock()
        orchestrator.connected_clients.add(websocket)
        orchestrator.camera_service.set_has_clients(True)
        orchestrator.ws_status = "RUNNING (CLIENT CONNECTED)"
        client_ip = websocket.remote_address[0] if websocket.remote_address else "painel"
        orchestrator.log(f"🟢 Dashboard conectado: {client_ip}")
        orchestrator.speech_manager.play_sound("connect")

        if orchestrator.map_stream:
            try:
                for evt in orchestrator.map_stream.get_initial_snapshot():
                    await safe_send_direct(websocket, json.dumps(evt), timeout=1.0)
            except Exception:
                pass

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    action = data.get("action") or data.get("type")
                    if action:
                        await handle_client_action(
                            orchestrator,
                            websocket,
                            action,
                            data,
                            send_func=lambda d: safe_send_direct(websocket, d, timeout=1.0)
                        )
                except Exception as ex:
                    orchestrator.log(f"Erro processar comando: {ex}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            client_locks.pop(websocket, None)
            if websocket in orchestrator.connected_clients:
                orchestrator.connected_clients.remove(websocket)
            orchestrator.log("🔴 Dashboard desconectado.")
            if not orchestrator.connected_clients:
                orchestrator.ws_status = "RUNNING (NO CLIENTS)"
                orchestrator.camera_service.set_has_clients(False)
                orchestrator.speech_manager.play_sound("disconnect")

    server = await websockets.serve(
        handler,
        "0.0.0.0",
        port,
        ping_interval=20,
        ping_timeout=20,
        max_size=None,
        compression=None  # Desativa permessage-deflate para máxima performance em frames binários
    )
    orchestrator.log(f"Servidor WebSocket ativo na porta {port}.")
    await asyncio.gather(broadcast_loop(), camera_stream_loop(), heartbeat_log_loop(), return_exceptions=True)

# ==============================================================================
# PONTO DE ENTRADA PRINCIPAL
# ==============================================================================
def main():
    print("=" * 60)
    print("  DASHGROUP ARCANJO — ORQUESTRADOR CENTRAL T800  ")
    print("=" * 60)

    ProcessManager.free_ports([PORT, 5050, 5000, 5055])

    if ROS2_AVAILABLE:
        try:
            rclpy.init(args=None)
        except Exception as e:
            print(f"[ORQUESTRADOR] Aviso rclpy.init: {e}")

    pm = ProcessManager()
    audio_svc = AudioCaptureService()
    pm.register_module(audio_svc)
    speech_mgr = SpeechManager(ros_node=None)
    pm.register_module(speech_mgr)
    neck_mgr = NeckManager()
    pm.register_module(neck_mgr)
    cam_svc = CameraService()
    pm.register_module(cam_svc)
    sensor_svc = SensorService()
    pm.register_module(sensor_svc)
    telemetry_svc = TelemetryService()
    pm.register_module(telemetry_svc)

    pm.initialize_all({"camera": {"speech_callback": speech_mgr.speak_text}})
    pm.start_all()

    local_ip = get_local_ip()
    orchestrator = RosBridgeOrchestrator(PORT, local_ip, pm)

    if ROS2_AVAILABLE:
        if LedControl is not None:
            try:
                telemetry_svc.led_publisher = orchestrator.create_publisher(LedControl, '/hardware/led_control', 10)
                telemetry_svc.led_msg_class = LedControl
            except Exception:
                pass
        try:
            telemetry_svc.bag_record_publisher = orchestrator.create_publisher(String, '/data_recorder/bag_record', 10)
            telemetry_svc.bag_stop_publisher = orchestrator.create_publisher(Bool, '/data_recorder/bag_stop', 10)
            telemetry_svc.string_msg_class = String
            telemetry_svc.bool_msg_class = Bool
        except Exception:
            pass

        speech_mgr.ros_node = orchestrator
        speech_mgr.initialize()
        if orchestrator.map_stream:
            orchestrator.map_stream.notify_node_ready(orchestrator)

    ros_executor = None
    if ROS2_AVAILABLE:
        try:
            from rclpy.executors import MultiThreadedExecutor
            ros_executor = MultiThreadedExecutor(num_threads=4)
            ros_executor.add_node(orchestrator)
            ros_thread = threading.Thread(target=ros_executor.spin, daemon=True)
            orchestrator.log("ROS 2 MultiThreadedExecutor ativo (4 threads de I/O).")
        except Exception as e:
            ros_thread = threading.Thread(target=lambda: rclpy.spin(orchestrator), daemon=True)
        ros_thread.start()

    try:
        asyncio.run(main_ws_loop(orchestrator, PORT))
    except KeyboardInterrupt:
        print("\n[ORQUESTRADOR] Encerrando...")
    finally:
        if orchestrator.map_stream:
            try:
                orchestrator.map_stream.stop()
            except Exception:
                pass
        pm.stop_all()
        if ROS2_AVAILABLE:
            if ros_executor is not None:
                try:
                    ros_executor.shutdown()
                except Exception:
                    pass
            try:
                orchestrator.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
            except Exception:
                pass
        print("[ORQUESTRADOR] Encerrado com sucesso.")

if __name__ == '__main__':
    main()
