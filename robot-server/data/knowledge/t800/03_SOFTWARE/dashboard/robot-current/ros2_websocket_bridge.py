#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
Dashgroup Arcanjo — Orquestrador Central ROS 2 WebSocket Bridge
T800 Humanoid Robot Central Communication & Lifecycle Orchestrator
==============================================================================

Responsabilidade do Orquestrador Central:
1. Inicializar e supervisionar todos os módulos em 'modules_dashboard/'.
2. Conectar e gerenciar o servidor WebSocket na porta 8090 com o Dashboard web.
3. Rotear comandos recebidos do operador para seus respectivos módulos especializados.
4. Compilar os dados dos módulos e transmitir o fluxo de telemetria a 30 Hz.
5. Monitorar o status de integridade de cada componente e realizar encerramento seguro.
"""

import os
import sys
import time
import json
import socket
import asyncio
import threading
import argparse
import shlex
import logging
from datetime import datetime
from typing import Dict, Any, Optional

# ==============================================================================
# AUTO-BOOTSTRAP DO AMBIENTE ROS 2 E WORKSPACE (T800 / NVIDIA AGX ORIN)
# ==============================================================================
# Permite rodar 'python3 ros2_websocket_bridge.py' diretamente mesmo sem 'source'
# manual no terminal. Se rclpy ou o workspace do robô não estiverem carregados,
# o script localiza o setup.bash do ROS 2 Humble e do robô, carrega as variáveis
# e se auto-reexecuta sob bash de forma transparente e imediata.
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
        setup_candidates = [
            "/opt/ros/humble/setup.bash",
            "/opt/ros/foxy/setup.bash",
        ]
        ws_candidates = [
            os.path.expanduser("~/engineai_workspace-2"),
            "/home/ubuntu/engineai_workspace-2",
            "/home/ubuntu/source/engineai_workspace",
            "/app/applications",
            os.path.expanduser("~/engineai_workspace"),
            os.path.expanduser("~/Downloads/engineai_workspace-2"),
            os.path.expanduser("~/Downloads/engineai_workspace"),
        ]
        source_cmds = []
        ros_base_found = False
        for c in setup_candidates:
            if os.path.exists(c):
                source_cmds.append(f"source {c}")
                ros_base_found = True
                break
        
        if ros_base_found:
            for ws in ws_candidates:
                ws_setup = os.path.join(ws, "install/setup.bash")
                if os.path.exists(ws_setup):
                    source_cmds.append(f"source {ws_setup}")
                    env_sh = os.path.join(ws, "src/interface_example/scripts/env.sh")
                    if os.path.exists(env_sh):
                        source_cmds.append(f"source {env_sh}")
                    break

            if source_cmds:
                print("[ORQUESTRADOR] ⚡ Auto-carregando ambiente ROS 2 e workspace do robô T800...")
                cmd = " && ".join(source_cmds) + f" && export _ROS2_BOOTSTRAPPED=1 && exec {sys.executable} " + " ".join(shlex.quote(arg) for arg in sys.argv)
                os.execlp("bash", "bash", "-c", cmd)

# ==============================================================================
# PARSE DE ARGUMENTOS CLI
# ==============================================================================
parser = argparse.ArgumentParser(description="Dashgroup Arcanjo — Orquestrador Central ROS 2 WebSocket Bridge")
parser.add_argument("--domain", "-d", type=str, default=None, help="Força ROS_DOMAIN_ID (ex: 69 ou 0)")
parser.add_argument("--rmw", type=str, default=None, help="Força RMW_IMPLEMENTATION (ex: rmw_cyclonedds_cpp ou rmw_fastrtps_cpp)")
parser.add_argument("--port", "-p", type=int, default=8090, help="Porta WebSocket (padrão: 8090)")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--observer", action="store_true", default=True, help="Somente leitura; controle físico aguarda arbitragem")
parser.add_argument("--enable-control", action="store_true", help="Habilita comandos via lease temporario no modo TEST")
parser.add_argument("--headless", action="store_true")
parser.add_argument("--mock", action="store_true", help="Não conectar ao ROS")
parser.add_argument("--no-clear", action="store_true", help="Não limpa a tela no terminal para manter histórico visível")
cli_args, _ = parser.parse_known_args()

# ==============================================================================
# CONFIGURAÇÕES DE REDE E AMBIENTE ROS 2 (T800 / CYCLONEDDS)
# ==============================================================================
if cli_args.domain:
    os.environ["ROS_DOMAIN_ID"] = str(cli_args.domain)
else:
    os.environ["ROS_DOMAIN_ID"] = os.environ.get("ROS_DOMAIN_ID", "69")

if cli_args.rmw:
    os.environ["RMW_IMPLEMENTATION"] = str(cli_args.rmw)
else:
    os.environ["RMW_IMPLEMENTATION"] = os.environ.get("RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp")

os.environ["ROS_LOCALHOST_ONLY"] = os.environ.get("ROS_LOCALHOST_ONLY", "0")

# Auto-localiza cyclonedds.xml
if "CYCLONEDDS_URI" not in os.environ:
    cyclone_candidates = [
        "/app/applications/install/bringup/cyclonedds.xml",
        "/home/ubuntu/cyclonedds.xml",
        os.path.expanduser("~/cyclonedds.xml"),
        os.path.expanduser("~/engineai_workspace-2/cyclonedds.xml"),
        "/home/ubuntu/engineai_workspace-2/cyclonedds.xml"
    ]
    for cpath in cyclone_candidates:
        if os.path.exists(cpath):
            os.environ["CYCLONEDDS_URI"] = f"file://{cpath}"
            break

# Adiciona diretórios do ROS 2 Humble e do workspace do T800 ao sys.path
for extra_p in [
    "/opt/ros/humble/local/lib/python3.10/dist-packages",
    "/opt/ros/humble/lib/python3.10/site-packages",
    "/opt/ros/foxy/local/lib/python3.8/dist-packages",
    os.path.expanduser("~/engineai_workspace-2/install/interface_protocol/local/lib/python3.10/dist-packages"),
    "/home/ubuntu/engineai_workspace-2/install/interface_protocol/local/lib/python3.10/dist-packages",
    "/app/applications/install/interface_protocol/local/lib/python3.10/dist-packages",
    os.path.expanduser("~/Downloads/engineai_workspace/install/interface_protocol/local/lib/python3.10/dist-packages"),
    os.path.expanduser("~/Downloads/engineai_workspace-2/install/interface_protocol/local/lib/python3.10/dist-packages")
]:
    if os.path.exists(extra_p) and extra_p not in sys.path:
        sys.path.append(extra_p)

# Garante que a pasta raiz do dashboard e modules_dashboard estejam no sys.path
DASHBOARD_ROOT = os.path.dirname(os.path.abspath(__file__))
if DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, DASHBOARD_ROOT)

# ==============================================================================
# IMPORTAÇÃO DOS MÓDULOS DE 'modules_dashboard' E 'backend'
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
except ImportError as e:
    MapStream = None
    print(f"\n[ORQUESTRADOR] ⚠️ Aviso: Módulo 3D 'modules_dashboard.map3d' não encontrado ({e}).\n")

# ==============================================================================
# CONFIGURAÇÕES DO ORQUESTRADOR
# ==============================================================================
PORT = cli_args.port
NO_CLEAR = cli_args.no_clear
HOST = cli_args.host
OBSERVER = bool(cli_args.observer and not cli_args.enable_control)
CONTROL_ENABLED = bool(cli_args.enable_control)
from platform_runtime.policy import validate_observer_message
from platform_runtime.logging_config import configure_logging
BROADCAST_RATE = 30.0       # Loop interno; telemetria/video sao limitados abaixo.
TELEMETRY_RATE = 8.0
VIDEO_RATE = 12.0
MAP_RATE = 5.0
CONTROL_LEASE_SECONDS = 15.0
CONTROL_ACTIONS = {
    "body_velocity", "body_stop", "set_motion_state",
    "speak", "neck_move", "neck_control", "neck_step", "neck_center",
    "neck_balance", "neck_balance_mode", "enable_balance",
    "set_led", "led_control", "start_bag_recording", "bag_record",
    "stop_bag_recording", "bag_stop",
}
TOPIC_SCAN_INTERVAL = 3.0   # Frequência para re-escanear tópicos no ROS 2 (segundos)
ENABLE_AUDIO = True

PRIORITY_TOPICS: Dict[str, str] = {
    "/manifold/ODIN2/device0/camera0/compressed": "sensor_msgs/msg/CompressedImage",
    "/manifold/ODIN2/device0/camera1/compressed": "sensor_msgs/msg/CompressedImage",
    "/manifold/ODIN2/device0/reprojection/overlay": "sensor_msgs/msg/Image",
    "/manifold/ODIN2/device0/reprojection/overlay/compressed": "sensor_msgs/msg/CompressedImage",
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

# ==============================================================================
# SUPORTE A ROS 2 E MENSAGENS OFICIAIS (interface_protocol)
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
except ImportError as e:
    OccupancyGrid = None
    ReentrantCallbackGroup = None
    print(f"[ORQUESTRADOR] ℹ️ ROS 2 não disponível ({e}). Operando com simulação/mocks.")

PowerInfo = None
MotionState = None
JointMotionPlanState = None
MotorDebug = None
ImuInfo = None
GamepadKeys = None
Heartbeat = None
LedControl = None
InterfaceJointState = None

try:
    from interface_protocol.msg import (
        PowerInfo, MotionState, JointMotionPlanState,
        MotorDebug, ImuInfo, GamepadKeys, Heartbeat,
        LedControl
    )
    from interface_protocol.msg import JointState as InterfaceJointState
except ImportError:
    pass

try:
    import websockets
except ImportError:
    print("\n[ERRO] Biblioteca 'websockets' não encontrada. Instale com: pip3 install websockets")
    sys.exit(1)

if cli_args.mock:
    ROS2_AVAILABLE = False

def get_local_ip():
    """Descobre o IP de rede local ativa do robô."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "192.168.0.162"


# ==============================================================================
# NÓ CENTRAL ORQUESTRADOR ROS 2
# ==============================================================================
class RosBridgeOrchestrator(Node if ROS2_AVAILABLE else object):
    """
    Nó central de orquestração.
    Coordena as assinaturas ROS 2, encaminha as mensagens para os serviços de
    modules_dashboard/ e monta o payload de telemetria unificado.
    """
    def __init__(self, port: int, local_ip: str, process_manager: ProcessManager):
        if ROS2_AVAILABLE:
            super().__init__('arcanjo_ros2_websocket_bridge')
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
        self.control_owner = None
        self.control_owner_id = None
        self.control_owner_name = None
        self.control_lease_expires = 0.0
        self.control_deadline = 0.0
        self.physical = None
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
        if MapStream is not None and os.environ.get("ARCANJO_MAP_ENABLED") == "1":
            self.map_stream = MapStream(ros_node=self if ROS2_AVAILABLE else None, logger=self.log)
            try:
                from modules_dashboard.camera.video_recorder import RecorderHttpHandler
                RecorderHttpHandler.scan_manager = self.map_stream.scan_manager
            except Exception:
                pass
        else:
            self.map_stream = None
        
        self.log("Orquestrador central inicializado com sucesso.")
        
        # Inscrição prévia imediata nos tópicos prioritários conhecidos
        if ROS2_AVAILABLE:
            for top_name, top_type in PRIORITY_TOPICS.items():
                if self.get_msg_class(top_type) is not None:
                    self.subscribe_to_topic(top_name, top_type)

        # Timer de auto-descoberta dinâmica de tópicos no ROS 2 (usando callback_group reentrante)
        if ROS2_AVAILABLE:
            timer_kwargs = {}
            if self.cb_group is not None:
                timer_kwargs['callback_group'] = self.cb_group
            self.auto_discover_timer = self.create_timer(TOPIC_SCAN_INTERVAL, self.discover_and_subscribe, **timer_kwargs)
            self.discover_and_subscribe()

    def log(self, message: str):
        logging.getLogger("bridge").info(message)
        t_str = datetime.now().strftime("%H:%M:%S")
        entry = f"[{t_str}] [ORQUESTRADOR] {message}"
        self.dashboard_logs.append(entry)
        if len(self.dashboard_logs) > 10:
            self.dashboard_logs.pop(0)

    # --------------------------------------------------------------------------
    # Mapeamento Dinâmico de Tópicos e Despacho para os Módulos
    # --------------------------------------------------------------------------
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
        if PowerInfo is not None:
            mapping['interface_protocol/msg/PowerInfo'] = PowerInfo
        if MotionState is not None:
            mapping['interface_protocol/msg/MotionState'] = MotionState
        if JointMotionPlanState is not None:
            mapping['interface_protocol/msg/JointMotionPlanState'] = JointMotionPlanState
        if MotorDebug is not None:
            mapping['interface_protocol/msg/MotorDebug'] = MotorDebug
        if ImuInfo is not None:
            mapping['interface_protocol/msg/ImuInfo'] = ImuInfo
        if GamepadKeys is not None:
            mapping['interface_protocol/msg/GamepadKeys'] = GamepadKeys
        if Heartbeat is not None:
            mapping['interface_protocol/msg/Heartbeat'] = Heartbeat
        if InterfaceJointState is not None:
            mapping['interface_protocol/msg/JointState'] = InterfaceJointState
        if LedControl is not None:
            mapping['interface_protocol/msg/LedControl'] = LedControl
        return mapping.get(msg_type_str, None)

    def discover_and_subscribe(self):
        if not ROS2_AVAILABLE:
            return
        try:
            names_and_types = self.get_topic_names_and_types()
            self.total_topics_found = len(names_and_types)
            active_names = [t[0] for t in names_and_types]

            # 1. Watchdog do driver de câmeras
            cam_topics = [
                '/manifold/ODIN2/device0/camera0/compressed',
                '/manifold/ODIN2/device0/camera1/compressed',
                '/manifold/ODIN2/device0/camera0',
                '/manifold/ODIN2/device0/camera1'
            ]
            has_cam_pubs = any(self.count_publishers(t) > 0 for t in cam_topics)
            if True:
                self.camera_service.check_and_start_driver(has_publishers=has_cam_pubs)

            # 2. Watchdogs de fala e pescoço
            if not OBSERVER:
                self.speech_manager.check_watchdog()
                self.neck_manager.check_watchdog()

            active_graph_topics = set()
            camera_topics = {}
            other_topics = []

            for topic_name, types in names_and_types:
                msg_type = types[0]
                active_graph_topics.add(topic_name)
                cam_key = get_camera_key(topic_name)
                is_cam_msg = 'image' in msg_type.lower() or 'compressed' in msg_type.lower()

                if cam_key and is_cam_msg:
                    if cam_key not in camera_topics:
                        camera_topics[cam_key] = []
                    camera_topics[cam_key].append((topic_name, msg_type))
                else:
                    other_topics.append((topic_name, msg_type))

            selected_camera_topics = set()
            for cam_key, topics in camera_topics.items():
                compressed = next((t for t in topics if 'compressed' in t[1].lower()), None)
                if compressed:
                    selected_camera_topics.add(compressed[0])
                    if compressed[0] not in self.subscriptions_map or self.subscriptions_map[compressed[0]].get('type') != compressed[1]:
                        self.subscribe_to_topic(compressed[0], compressed[1])
                else:
                    best = next((t for t in topics if 'rect' in t[0].lower() or 'undistort' in t[0].lower()), topics[0])
                    selected_camera_topics.add(best[0])
                    if best[0] not in self.subscriptions_map or self.subscriptions_map[best[0]].get('type') != best[1]:
                        self.subscribe_to_topic(best[0], best[1])

            for topic_name, msg_type in other_topics:
                if topic_name in self.subscriptions_map:
                    if self.subscriptions_map[topic_name].get('type') != msg_type:
                        self.subscribe_to_topic(topic_name, msg_type)
                    else:
                        self.subscriptions_map[topic_name]['active'] = True
                    continue

                should_subscribe = False
                if topic_name in self.priority_topics:
                    should_subscribe = True
                else:
                    name_lower = topic_name.lower()
                    type_lower = msg_type.lower()
                    if ('imu' in name_lower and 'imu' in type_lower) or \
                       ('odom' in name_lower and 'odom' in type_lower) or \
                       (('scan' in name_lower or 'cloud' in name_lower) and ('laserscan' in type_lower or 'pointcloud' in type_lower)) or \
                       ('joint' in name_lower and 'jointstate' in type_lower) or \
                       ('battery' in name_lower and 'battery' in type_lower) or \
                       ('joy' in name_lower or 'gamepad' in name_lower):
                        should_subscribe = True

                if should_subscribe:
                    self.subscribe_to_topic(topic_name, msg_type)

            for topic_name in list(self.subscriptions_map.keys()):
                cam_key = get_camera_key(topic_name)
                is_cam = 'image' in self.subscriptions_map[topic_name]['type'].lower() or 'compressed' in self.subscriptions_map[topic_name]['type'].lower()
                if cam_key and is_cam and topic_name not in selected_camera_topics and topic_name not in self.priority_topics:
                    self.unsubscribe_from_topic(topic_name)
                elif topic_name not in active_graph_topics and topic_name not in self.priority_topics:
                    self.unsubscribe_from_topic(topic_name)
        except Exception as e:
            self.log(f"Erro na auto-descoberta: {e}")

    def subscribe_to_topic(self, topic_name: str, msg_type_str: str):
        if msg_type_str in {'sensor_msgs/msg/PointCloud2', 'sensor_msgs/msg/LaserScan'}:
            return
        if topic_name in self.subscriptions_map:
            current_info = self.subscriptions_map[topic_name]
            if current_info.get('type') == msg_type_str:
                return
            self.log(f"Atualizando assinatura de {topic_name}: {current_info.get('type')} -> {msg_type_str}")
            self.unsubscribe_from_topic(topic_name)

        msg_class = self.get_msg_class(msg_type_str)
        if not msg_class:
            return

        # Roteamento direto de callbacks para os módulos responsáveis
        raw_cb = None
        if msg_class == CompressedImage:
            raw_cb = lambda msg, t=topic_name: self.camera_service.process_compressed_image(msg, t)
        elif msg_class == Image:
            raw_cb = lambda msg, t=topic_name: self.camera_service.process_raw_image(msg, t)
        elif msg_class == CameraInfo:
            raw_cb = lambda msg, t=topic_name: self.camera_service.process_camera_info(msg, t)
        elif msg_class == Imu:
            raw_cb = lambda msg, t=topic_name: self.sensor_service.process_imu_standard(msg, t)
        elif ImuInfo is not None and msg_class == ImuInfo:
            raw_cb = lambda msg, t=topic_name: self.sensor_service.process_imu_info(msg, t)
        elif msg_class == Odometry:
            if 'lidar2cam' in topic_name or 'lidar2imu' in topic_name:
                raw_cb = lambda msg, t=topic_name: self.sensor_service.process_calibration(msg, t)
            else:
                def _handle_odom(msg, t=topic_name):
                    self.sensor_service.process_odometry(msg, t)
                    if hasattr(self, 'map_stream') and self.map_stream and self.map_stream.odom_sub:
                        self.map_stream.odom_sub._handle_odometry(msg)
                raw_cb = _handle_odom
        elif LaserScan is not None and msg_class == LaserScan:
            raw_cb = lambda msg: self.sensor_service.process_laser_scan(msg)
        elif PointCloud2 is not None and msg_class == PointCloud2:
            def _handle_cloud(msg, t=topic_name):
                self.sensor_service.process_point_cloud(msg, t)
                if hasattr(self, 'camera_service') and self.camera_service and self.camera_service.is_camera_active('overlay'):
                    self.camera_service.update_point_cloud(msg)
            raw_cb = _handle_cloud
        elif msg_class == BatteryState:
            raw_cb = lambda msg: self.telemetry_service.process_battery_state(msg)
        elif PowerInfo is not None and msg_class == PowerInfo:
            raw_cb = lambda msg: self.telemetry_service.process_power_info(msg)
        elif MotionState is not None and msg_class == MotionState:
            raw_cb = lambda msg: self.telemetry_service.process_motion_state(msg)
        elif JointMotionPlanState is not None and msg_class == JointMotionPlanState:
            raw_cb = lambda msg: self.telemetry_service.process_motion_plan_state(msg)
        elif MotorDebug is not None and msg_class == MotorDebug:
            raw_cb = lambda msg: self.telemetry_service.process_motor_debug(msg)
        elif GamepadKeys is not None and msg_class == GamepadKeys:
            raw_cb = lambda msg: self.telemetry_service.process_gamepad_keys(msg)
        elif Heartbeat is not None and msg_class == Heartbeat:
            raw_cb = lambda msg: self.telemetry_service.process_heartbeat(msg)
        elif msg_class == Joy:
            raw_cb = lambda msg: self.telemetry_service.process_joy(msg)
        elif msg_class == JointState or (InterfaceJointState is not None and msg_class == InterfaceJointState):
            raw_cb = lambda msg: self.telemetry_service.process_joint_states(msg)
        elif msg_class == String:
            if 'bag_status' in topic_name:
                raw_cb = lambda msg: self.telemetry_service.process_bag_status(str(msg.data))
            else:
                raw_cb = lambda msg, t=topic_name: self.telemetry_service.process_system_driver_string(t, str(msg.data))
        elif msg_class == Bool:
            raw_cb = lambda msg, t=topic_name: self.telemetry_service.process_system_driver_bool(t, bool(msg.data))
        else:
            raw_cb = lambda msg: None

        # Callback com rastreamento ativo de estatísticas de mensagens, taxa (Hz) e timestamp
        def callback(msg, t=topic_name, target_fn=raw_cb):
            now = time.time()
            info = self.subscriptions_map.get(t)
            if info:
                info['msg_count'] += 1
                prev_time = info.get('last_msg_time', 0.0)
                if prev_time > 0.0:
                    dt = now - prev_time
                    if dt > 0.001:
                        instant_hz = 1.0 / dt
                        curr_hz = info.get('rate_hz', instant_hz)
                        info['rate_hz'] = round(0.85 * curr_hz + 0.15 * instant_hz, 1)
                info['last_msg_time'] = now
            if target_fn:
                try:
                    target_fn(msg)
                except Exception as ex:
                    self.log(f"Erro no callback de {t}: {ex}")

        try:
            is_hardware_or_motion = (
                (InterfaceJointState is not None and msg_class == InterfaceJointState)
                or (PowerInfo is not None and msg_class == PowerInfo)
                or (MotionState is not None and msg_class == MotionState)
                or (JointMotionPlanState is not None and msg_class == JointMotionPlanState)
                or (MotorDebug is not None and msg_class == MotorDebug)
                or (ImuInfo is not None and msg_class == ImuInfo)
                or (GamepadKeys is not None and msg_class == GamepadKeys)
                or (Heartbeat is not None and msg_class == Heartbeat)
                or msg_class == JointState
                or 'hardware' in topic_name.lower()
                or 'motion' in topic_name.lower()
                or 'joint' in topic_name.lower()
            )
            if is_hardware_or_motion:
                qos = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.VOLATILE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10
                )
            elif msg_class in [String, Bool, CameraInfo, Joy]:
                qos = QoSProfile(
                    reliability=ReliabilityPolicy.RELIABLE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=1
                )
            else:
                qos = QoSProfile(
                    reliability=ReliabilityPolicy.BEST_EFFORT,
                    durability=DurabilityPolicy.VOLATILE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=5
                )

            sub_kwargs = {}
            if getattr(self, 'cb_group', None) is not None:
                sub_kwargs['callback_group'] = self.cb_group

            sub = self.create_subscription(msg_class, topic_name, callback, qos, **sub_kwargs)
            self.subscriptions_map[topic_name] = {
                'sub': sub,
                'msg_count': 0,
                'type': msg_type_str,
                'last_msg_time': 0.0,
                'rate_hz': 0.0,
                'active': True
            }
            self.log(f"Inscrito em: {topic_name}")
        except Exception as e:
            self.log(f"Falha ao assinar {topic_name}: {e}")

    def unsubscribe_from_topic(self, topic_name: str):
        if topic_name in self.subscriptions_map:
            try:
                self.destroy_subscription(self.subscriptions_map[topic_name]['sub'])
                self.log(f"Desinscrito: {topic_name}")
            except Exception:
                pass
            del self.subscriptions_map[topic_name]

    # --------------------------------------------------------------------------
    # Compilação do Pacote de Telemetria Unificado (30 Hz)
    # --------------------------------------------------------------------------
    def get_telemetry_payload(self, include_cameras: bool = False) -> Dict[str, Any]:
        self.frame_count += 1
        is_slow_frame = (self.frame_count % 8 == 0)

        # 1. Câmeras
        cameras_payload = self.camera_service.extract_pending_cameras() if include_cameras else None
        camera_info_payload = self.camera_service.get_camera_info_payload()
        camera_stats_payload = self.camera_service.get_camera_stats_payload()

        # 2. Áudio
        audio_bytes, mic_vol = self.audio_service.get_and_clear_audio()
        audio_payload = {
            "pcm": (import_base64().b64encode(audio_bytes).decode('utf-8')) if audio_bytes else None,
            "sample_rate": self.audio_service.sample_rate,
            "channels": self.audio_service.channels,
            "volume_level": mic_vol
        }

        # 3. Sensores
        sensor_snap = self.sensor_service.get_telemetry_snapshot()
        cloud_pts = None

        # 4. Telemetria de Hardware
        telem_snap = self.telemetry_service.get_telemetry_snapshot(is_slow_frame=is_slow_frame)

        # 5. Pescoço Q25H com validação de segurança
        p_info = telem_snap.get("power") or telem_snap.get("battery") or {}
        bms_on = bool(p_info.get("enable", False)) if isinstance(p_info, dict) else False
        m_state = telem_snap.get("motion_state") or {}
        curr_task = str(m_state.get("current_motion_task", "")) if isinstance(m_state, dict) else ""
        neck_payload = self.neck_manager.get_telemetry_snapshot(
            bms_enabled=bms_on,
            current_task=curr_task,
            joints_data=telem_snap.get("joints")
        )

        payload = {
            "timestamp": time.time(),
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
            "status": {},
            "neck": neck_payload,
            "motion_state": telem_snap.get("motion_state"),
            "motion_plan": telem_snap.get("motion_plan"),
            "motors_debug": telem_snap.get("motors_debug"),
            "heartbeats": telem_snap.get("heartbeats"),
        }

        if is_slow_frame:
            payload["joints"] = telem_snap.get("joints")
            payload["gamepad"] = telem_snap.get("gamepad")
            payload["system"] = telem_snap.get("system")
            payload["modules_status"] = self.process_manager.get_all_status()
            payload["node_status"] = {
                "active_topics_count": len(self.subscriptions_map),
                "connected_ws_clients": len(self.connected_clients),
                "uptime_seconds": time.time() - self.start_time,
                "topics": {
                    topic.split('/')[-1]: {
                        "active": ((time.time() - info['last_msg_time']) < 3.0) if info.get('last_msg_time', 0.0) > 0 else False,
                        "msgs_total": info.get('msg_count', 0)
                    }
                    for topic, info in self.subscriptions_map.items()
                }
            }

        now = time.time()
        for topic, info in self.subscriptions_map.items():
            last_time = info.get('last_msg_time', 0.0)
            msg_count = info.get('msg_count', 0)
            elapsed = round(now - last_time, 1) if last_time > 0 else None
            is_connected = (elapsed is not None and elapsed < 3.0)

            if is_connected:
                state = "ONLINE"
            elif msg_count > 0:
                state = "TIMEOUT"
            else:
                state = "INACTIVE"

            payload["status"][topic] = {
                "connected": is_connected,
                "msgs": msg_count,
                "rate_hz": info.get('rate_hz', 0.0) if is_connected else 0.0,
                "last_msg_time": last_time,
                "elapsed_sec": elapsed,
                "state": state
            }

        if hasattr(self, "map_stream") and self.map_stream and self.map_stream.cloud_sub:
            csub = self.map_stream.cloud_sub
            if csub.active_topic:
                is_on = csub.is_online() if self.map_stream.lidar_enabled else False
                payload["status"][csub.active_topic] = {
                    "connected": is_on,
                    "msgs": csub.msg_count,
                    "rate_hz": csub.get_rate_hz() if self.map_stream.lidar_enabled else 0.0,
                    "lidar_enabled": self.map_stream.lidar_enabled,
                    "state": "ONLINE" if is_on else ("TIMEOUT" if csub.msg_count > 0 else "INACTIVE")
                }

        return payload

    def _control_state(self):
        if self.control_owner and time.monotonic() >= self.control_deadline:
            if self.physical:
                self.physical.stop()
            self.control_owner = None
            self.control_owner_id = None
            self.control_owner_name = None
        return {
            "type": "control_state",
            "enabled": CONTROL_ENABLED,
            "owner_id": self.control_owner_id,
            "owner_name": self.control_owner_name,
            "lease_expires_at": self.control_lease_expires,
            "lease_seconds": CONTROL_LEASE_SECONDS,
            "capabilities": self.physical.capabilities if self.physical else {},
        }

    def acquire_control(self, websocket, owner_id, owner_name):
        self._control_state()
        if not CONTROL_ENABLED:
            return False
        now = time.time()
        if self.control_owner and self.control_owner is not websocket:
            return False
        self.control_owner = websocket
        self.control_owner_id = str(owner_id or "client")[:80]
        self.control_owner_name = str(owner_name or self.control_owner_id)[:80]
        self.control_lease_expires = now + CONTROL_LEASE_SECONDS
        self.control_deadline = time.monotonic() + CONTROL_LEASE_SECONDS
        return True

    def release_control(self, websocket):
        if self.control_owner is websocket:
            if self.physical:
                self.physical.stop()
            self.control_owner = None
            self.control_owner_id = None
            self.control_owner_name = None
            self.control_lease_expires = 0.0

    def has_control(self, websocket, data):
        if not CONTROL_ENABLED:
            return False
        owner_id = str(data.get("owner_id") or data.get("client_id") or "")[:80]
        self._control_state()
        if self.control_owner is websocket and (not owner_id or owner_id == self.control_owner_id):
            self.control_lease_expires = time.time() + CONTROL_LEASE_SECONDS
            self.control_deadline = time.monotonic() + CONTROL_LEASE_SECONDS
            return True
        return False

    def draw_terminal(self):
        """Renderiza a interface do console com diagnóstico de ROS 2 e rede DDS."""
        if not NO_CLEAR:
            os.system('clear' if os.name != 'nt' else 'cls')
        print("======================================================================")
        print("            Dashgroup Arcanjo — Orquestrador Central T800            ")
        print("======================================================================")
        print(f"IP Local:       {self.local_ip}")
        print(f"WebSocket:      ws://{self.local_ip}:{self.port}")
        print(f"Status Server:  {self.ws_status}")
        print(f"Clientes Con:   {len(self.connected_clients)}")
        print(f"Frequência Tx:  {BROADCAST_RATE} Hz")
        print(f"Tempo de Exec:  {int(time.time() - self.start_time)}s")
        print("----------------------------------------------------------------------")
        ros_label = "🟢 ATIVO (Humble)" if ROS2_AVAILABLE else "🔴 NÃO DISPONÍVEL (Mocks)"
        print(f"ROS 2 Core:     {ros_label}")
        print(f"ROS_DOMAIN_ID:  {os.environ.get('ROS_DOMAIN_ID', '69')}")
        print(f"RMW DDS:        {os.environ.get('RMW_IMPLEMENTATION', 'padrão')}")
        if os.environ.get("CYCLONEDDS_URI"):
            print(f"CycloneDDS XML: {os.environ.get('CYCLONEDDS_URI')}")
        map_label = "🟢 ATIVO (Foxglove Streamer)" if (hasattr(self, "map_stream") and self.map_stream) else "⚠️ INATIVO"
        print(f"Mapeamento 3D:  {map_label}")
        print("----------------------------------------------------------------------")
        print("STATUS DOS MÓDULOS (modules_dashboard/):")
        for mod_name, mod_info in self.process_manager.get_all_status().items():
            status_color = "[ONLINE] " if mod_info.get("is_running") else "[PARADO] "
            print(f"  {status_color} {mod_name:<12} (Status: {mod_info.get('status')}, Erros: {mod_info.get('error_count')})")
        print("----------------------------------------------------------------------")
        print(f"Tópicos no Grafo DDS: {self.total_topics_found} encontrados | {len(self.subscriptions_map)} inscritos")
        
        # Tópicos recebendo dados ativos (>0 msgs)
        active_rx = [t for t, info in self.subscriptions_map.items() if info.get('msg_count', 0) > 0]
        if active_rx:
            print(f"Tópicos com dados ativos ({len(active_rx)}):")
            for t in sorted(active_rx)[:8]:
                cnt = self.subscriptions_map[t]['msg_count']
                dt = time.time() - self.subscriptions_map[t]['last_msg_time']
                print(f"  ⚡ {t} ({cnt} msgs, há {dt:.1f}s)")
        
        if not ROS2_AVAILABLE:
            print("  ⛔ ALERTA: 'rclpy' não encontrado! O auto-bootstrap tentará carregar.")
        elif self.total_topics_found == 0 and len(active_rx) == 0:
            print("  ⚠️ ALERTA: 0 tópicos detectados no DDS!")
            print("     1. Verifique se os nós do robô estão rodando ('ros2 topic list')")
            print("     2. Se o robô usa DOMAIN 0, rode: python3 ros2_websocket_bridge.py --domain 0")
            print("     3. Se usa FastDDS, rode: python3 ros2_websocket_bridge.py --rmw rmw_fastrtps_cpp")
        print("======================================================================")
        print("LOGS DO ORQUESTRADOR:")
        for log_msg in self.dashboard_logs[-8:]:
            print(log_msg)
        print("======================================================================")

def import_base64():
    import base64
    return base64


# ==============================================================================
# LOOP PRINCIPAL WEBSOCKET
# ==============================================================================
async def main_ws_loop(orchestrator: RosBridgeOrchestrator, port: int):
    views = {}
    def update_views():
        wanted = {cam for cam in views.values() if cam in {'cam0', 'cam1'}}
        orchestrator.camera_service.wanted_keys = wanted
        orchestrator.camera_service.set_active_view('overview', next(iter(wanted)) if len(wanted) == 1 else 'all' if wanted else 'none')

    async def send_control_state(target=None):
        msg = json.dumps(orchestrator._control_state())
        clients = [target] if target is not None else [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
        if clients:
            await asyncio.gather(*[asyncio.wait_for(c.send(msg), timeout=0.05) for c in clients], return_exceptions=True)

    def control_required(action):
        return action in CONTROL_ACTIONS

    async def handler(websocket, path=None):
        if getattr(getattr(websocket, 'request', None), 'path', path) == '/health-ws':
            from platform_runtime.health import bridge_snapshot
            try:
                async for _ in websocket:
                    await websocket.send(json.dumps(bridge_snapshot(orchestrator, ROS2_AVAILABLE), default=str))
            except websockets.exceptions.ConnectionClosed:
                pass
            return
        orchestrator.connected_clients.add(websocket)
        views[websocket] = "none"
        update_views()
        orchestrator.camera_service.set_has_clients(True)
        client_ip = websocket.remote_address[0] if websocket.remote_address else "painel"
        orchestrator.log(f"🟢 Dashboard conectado: {client_ip}")
        orchestrator.ws_status = "RUNNING (CLIENT CONNECTED)"
        
        # Sinal sonoro de conexão

        # Envio do snapshot inicial do Mapeamento 3D
        try:
            if hasattr(orchestrator, "map_stream") and orchestrator.map_stream:
                for evt in orchestrator.map_stream.get_initial_snapshot():
                    await websocket.send(json.dumps(evt))
        except Exception:
            pass
        await send_control_state(websocket)

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if not isinstance(data, dict):
                        raise ValueError("Mensagem inválida")
                    action = data.get("action") or data.get("type")

                    if action == "health":
                        from platform_runtime.health import bridge_snapshot
                        await websocket.send(json.dumps({"type": "health", **bridge_snapshot(orchestrator, ROS2_AVAILABLE)}, default=str))
                        continue
                    if action == "acquire_control":
                        ok = orchestrator.acquire_control(websocket, data.get("client_id"), data.get("name") or client_ip)
                        await websocket.send(json.dumps(orchestrator._control_state() | {"acquired": ok, "busy": not ok}))
                        await send_control_state()
                        if ok:
                            orchestrator.log(f"Controle adquirido por {orchestrator.control_owner_name}")
                        continue
                    if action in {"release_control", "control_release"}:
                        orchestrator.release_control(websocket)
                        await send_control_state()
                        orchestrator.log("Controle liberado")
                        continue
                    if action in {"renew_control", "control_renew"}:
                        ok = orchestrator.has_control(websocket, data)
                        await websocket.send(json.dumps(orchestrator._control_state() | {"renewed": ok}))
                        continue

                    if action not in CONTROL_ACTIONS:
                        try:
                            validate_observer_message(data)
                        except ValueError as exc:
                            await websocket.send(json.dumps({"type": "command_error", "error": str(exc)}))
                            continue

                    if control_required(action) and not orchestrator.has_control(websocket, data):
                        await websocket.send(json.dumps({
                            **orchestrator._control_state(),
                            "type": "control_busy",
                            "error": "Controle ocupado ou nao adquirido",
                        }))
                        continue

                    if action in {"body_velocity", "body_stop", "set_motion_state"}:
                        if not orchestrator.physical:
                            raise ValueError("Controle ROS indisponível")
                        if action == "set_motion_state":
                            orchestrator.physical.transition(data.get("target"))
                        elif action == "body_stop":
                            orchestrator.physical.watchdog.stop()
                        else:
                            orchestrator.physical.velocity(data.get("x", 0), data.get("y", 0), data.get("yaw", 0))
                        continue
                    if action in {"neck_move", "neck_control", "neck_step", "neck_center", "neck_balance", "neck_balance_mode", "enable_balance"}:
                        if not orchestrator.physical:
                            raise ValueError("Controle ROS indisponível")
                        state = orchestrator.telemetry_service.motion_state or {}
                        if state.get('current_motion_task') != 'lower_body_balance':
                            raise ValueError('Cabeça requer lower_body_balance confirmado')
                        orchestrator.physical.ensure('neck')
                        if not orchestrator.physical.fresh('/hardware/joint_state'):
                            raise ValueError("Posição das juntas indisponível")
                        orchestrator.physical.neck_active = True

                    # 1. Fala (TTS)
                    if action == "speak":
                        text = data.get("text", "").strip()
                        voice = data.get("voice", "pt-BR-AntonioNeural")
                        speed = str(data.get("speed", "+20%"))
                        orchestrator.speech_manager.speak_text(text, voice=voice, speed=speed)

                    # 2. Gravação de Vídeo
                    elif action == "start_recording":
                        cam = data.get("camera", orchestrator.camera_service.active_cam)
                        fps = data.get("fps", 30.0)
                        orchestrator.camera_service.video_recorder.start(camera=cam, fps=fps)
                    elif action == "stop_recording":
                        orchestrator.camera_service.video_recorder.stop()

                    # 3. Configurações de Câmera
                    elif action in ["set_camera_config", "set_camera_quality"]:
                        w = data.get("target_width") or data.get("target_image_width")
                        q = data.get("jpeg_quality")
                        orchestrator.camera_service.set_camera_config(w, q)
                    elif action == "set_active_view":
                        views[websocket] = data.get("active_cam", "none")
                        update_views()

                    # 4. Controle do Pescoço Q25H
                    elif action in ["neck_move", "neck_control"]:
                        orchestrator.neck_manager.send_command("move", {
                            "pitch": float(data.get("pitch", 0.0)),
                            "yaw": float(data.get("yaw", 0.0)),
                            "duration": float(data.get("duration", 1.5))
                        })
                    elif action == "neck_step":
                        orchestrator.neck_manager.send_command("step", {
                            "d_pitch": float(data.get("d_pitch", 0.0)),
                            "d_yaw": float(data.get("d_yaw", 0.0)),
                            "duration": float(data.get("duration", 0.4))
                        })
                    elif action == "neck_center":
                        orchestrator.neck_manager.send_command("center", {
                            "duration": float(data.get("duration", 1.5))
                        })
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
                            orchestrator.log(f"⛔ Intertravamento rejeitou modo balance: {reason}")

                    # 5. LEDs
                    elif action in ["set_led", "led_control"]:
                        if not orchestrator.physical:
                            raise ValueError("Controle ROS indisponível")
                        orchestrator.telemetry_service.led_publisher = orchestrator.physical.ensure('led')
                        orchestrator.telemetry_service.led_msg_class = LedControl
                        orchestrator.telemetry_service.set_led_control(int(data.get("color", 5)))

                    # 6. Gravação de Caixa-Preta (ROS 2 Bag Recorder)
                    elif action in ["start_bag_recording", "bag_record"]:
                        fname = str(data.get("filename", "")).strip()
                        orchestrator.telemetry_service.start_bag_recording(fname)
                    elif action in ["stop_bag_recording", "bag_stop"]:
                        orchestrator.telemetry_service.stop_bag_recording()

                    # 7. Ping / Latência
                    elif action == "ping":
                        client_ts = data.get("timestamp", time.time() * 1000)
                        await websocket.send(json.dumps({
                            "type": "pong",
                            "client_timestamp": client_ts,
                            "server_timestamp": time.time() * 1000
                        }))

                    # 8. Diagnóstico de Tópicos e Grafo ROS 2
                    elif action == "query_ros_topics":
                        all_topics = orchestrator.get_topic_names_and_types() if ROS2_AVAILABLE else []
                        await websocket.send(json.dumps({
                            "type": "ros_topics_list",
                            "topics": all_topics
                        }))

                    elif action == "query_topic_info":
                        target_topic = data.get("topic", "")
                        pubs = []
                        if ROS2_AVAILABLE and target_topic:
                            try:
                                for p in orchestrator.get_publishers_info_by_topic(target_topic):
                                    pubs.append({
                                        "node_name": p.node_name,
                                        "node_namespace": p.node_namespace,
                                        "topic_type": p.topic_type
                                    })
                            except Exception as ex:
                                pubs = [{"error": str(ex)}]
                        await websocket.send(json.dumps({
                            "type": "topic_info_res",
                            "topic": target_topic,
                            "publishers": pubs
                        }))

                    elif action == "query_system_cmd":
                        await websocket.send(json.dumps({
                            "type": "command_error", "error": "Shell remoto removido"
                        }))

                    # Comandos de Mapeamento 3D (Foxglove Style)
                    elif action and action.startswith("map_3d/"):
                        if hasattr(orchestrator, "map_stream") and orchestrator.map_stream:
                            resp = orchestrator.map_stream.handle_action(action, data)
                            if resp:
                                await websocket.send(json.dumps(resp))
                except Exception as e:
                    await websocket.send(json.dumps({"type": "command_error", "error": str(e)}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if websocket in orchestrator.connected_clients:
                orchestrator.connected_clients.remove(websocket)
            orchestrator.release_control(websocket)
            views.pop(websocket, None)
            update_views()
            await send_control_state()
            orchestrator.log("🔴 Dashboard desconectado.")
            if not orchestrator.connected_clients:
                orchestrator.ws_status = "RUNNING (NO CLIENTS)"
                orchestrator.camera_service.set_has_clients(False)
                # Sinal sonoro de desconexão

    async def broadcast_loop():
        last_telemetry = 0.0
        last_video = 0.0
        last_map = 0.0
        while True:
            await asyncio.sleep(1.0 / BROADCAST_RATE)
            if not orchestrator.connected_clients:
                continue
            now = time.time()
            orchestrator._control_state()

            # Função auxiliar de envio com timeout individual para isolar clientes lentos
            async def safe_send(client, data):
                try:
                    timeout = 0.08 if isinstance(data, (bytes, bytearray)) else 0.20
                    await asyncio.wait_for(client.send(data), timeout=timeout)
                    return True
                except asyncio.TimeoutError:
                    # Cliente lento: descarta esta atualização/frame.
                    # Não derruba a conexão só por atraso temporário.
                    return False
                except Exception:
                    try:
                        await client.close()
                    except Exception:
                        pass
                    return False

            clients = [c for c in orchestrator.connected_clients if getattr(c, 'open', True)]
            if not clients:
                continue

            # 1. Telemetria Geral limitada; sem video dentro do JSON.
            try:
                if now - last_telemetry >= (1.0 / TELEMETRY_RATE):
                    last_telemetry = now
                    await send_control_state()
                    payload = orchestrator.get_telemetry_payload(include_cameras=False)
                    msg = json.dumps(payload)
                    await asyncio.gather(*[safe_send(c, msg) for c in clients], return_exceptions=True)
            except Exception as e:
                orchestrator.log(f"Erro no broadcast WebSocket: {e}")

            # 2. Video em binario, ultimo frame conhecido, com drop para cliente lento.
            try:
                if now - last_video >= (1.0 / VIDEO_RATE):
                    last_video = now
                    cameras = orchestrator.camera_service.extract_pending_cameras() or {}
                    frames = [value for value in cameras.values() if isinstance(value, bytes)]
                    for frame in frames:
                        key = ['cam0', 'cam1', 'gray', 'overlay'][frame[4]]
                        eligible = [c for c in clients if views.get(c) == key and c.transport.get_write_buffer_size() < 65536]
                        await asyncio.gather(*[safe_send(c, frame) for c in eligible], return_exceptions=True)
            except Exception as e:
                orchestrator.log(f"Erro no broadcast de video: {e}")

            # 3. Eventos dedicados de Mapeamento 3D apenas quando a aba ativa pede.
            try:
                map_active = orchestrator.camera_service.active_tab in {"pointcloud", "map3d", "map_3d"}
                if map_active and now - last_map >= (1.0 / MAP_RATE) and hasattr(orchestrator, "map_stream") and orchestrator.map_stream:
                    last_map = now
                    # 2a. Frames binários Float32Array de altíssimo desempenho (Zero-Copy)
                    bin_frames = orchestrator.map_stream.pop_pending_binary_frames()
                    if bin_frames:
                        for bframe in bin_frames[-1:]:
                            await asyncio.gather(*[safe_send(c, bframe) for c in clients], return_exceptions=True)

                    # 2b. Eventos JSON de controle e status
                    map3d_events = orchestrator.map_stream.pop_pending_events()
                    for evt in map3d_events[-3:]:
                        evt_msg = json.dumps(evt)
            except Exception:
                pass

    async def terminal_draw_loop():
        while True:
            if not cli_args.headless:
                orchestrator.draw_terminal()
            await asyncio.sleep(1.0)

    async def health_request(connection, request):
        if request.path == '/health':
            from http import HTTPStatus
            from platform_runtime.health import bridge_snapshot
            snapshot = bridge_snapshot(orchestrator, ROS2_AVAILABLE)
            response = connection.respond(HTTPStatus.OK, json.dumps(snapshot, default=str))
            response.headers['Content-Type'] = 'application/json'
            return response
        return None

    server = await websockets.serve(
        handler,
        HOST,
        port,
        process_request=health_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=16384,
        max_queue=4,
        compression=None
    )
    orchestrator.log(f"Servidor WebSocket iniciado na porta {port}.")
    await asyncio.gather(broadcast_loop(), terminal_draw_loop(), return_exceptions=True)


# ==============================================================================
# PONTO DE ENTRADA PRINCIPAL
# ==============================================================================
def main():
    print("=" * 70)
    print("  DASHGROUP ARCANJO — INICIALIZANDO ORQUESTRADOR CENTRAL T800  ")
    print("=" * 70)

    # 1. Liberação de portas presas
    configure_logging(os.environ.get("T800_STATE_DIR", ".state"), "bridge")
    if HOST not in {"127.0.0.1", "::1"}:
        raise ValueError("Host invalido para modo teste")
    if HOST == "0.0.0.0" and not OBSERVER:
        raise ValueError("Host LAN permitido apenas em modo observer")
    # Nunca encerra processos de outro dashboard.
    # Se nossa porta estiver ocupada, o bind falhara explicitamente.
    pass

    # 2. Inicialização do ROS 2 se disponível
    node_ctx = None
    if ROS2_AVAILABLE:
        try:
            rclpy.init(args=None)
        except Exception as e:
            print(f"[ORQUESTRADOR] Aviso ao iniciar rclpy: {e}")

    # 3. Instanciação e registro dos módulos de 'modules_dashboard/'
    pm = ProcessManager()
    
    audio_svc = AudioCaptureService()
    pm.register_module(audio_svc)

    speech_mgr = SpeechManager(ros_node=None)
    pm.register_module(speech_mgr)

    neck_mgr = NeckManager()
    pm.register_module(neck_mgr)

    cam_svc = CameraService()
    cam_svc.binary_transport = True
    pm.register_module(cam_svc)

    sensor_svc = SensorService()
    pm.register_module(sensor_svc)

    telemetry_svc = TelemetryService()
    pm.register_module(telemetry_svc)

    # 4. Inicializa e inicia todos os módulos
    pm.initialize_all({
        "camera": {"speech_callback": None, "auto_start_driver": True, "recorder_enabled": False}
    })
    for module in pm.modules.values():
        if module.name == "audio" or (OBSERVER and module.name in {"speech", "neck"}):
            module.status = "DISABLED"
        else:
            module.start()
    cam_svc.set_has_clients(False)

    local_ip = get_local_ip()

    # 5. Criação do Nó Orquestrador
    orchestrator = RosBridgeOrchestrator(PORT, local_ip, pm)

    if ROS2_AVAILABLE and CONTROL_ENABLED:
        from platform_runtime.control import RosControl
        orchestrator.physical = RosControl(orchestrator)

    # Conecta o nó ao speech_mgr se ativo
    if ROS2_AVAILABLE:
        if not OBSERVER:
            speech_mgr.ros_node = orchestrator
            speech_mgr.initialize()
        if hasattr(orchestrator, "map_stream") and orchestrator.map_stream:
            orchestrator.map_stream.notify_node_ready(orchestrator)

    # Thread de spin do ROS 2 com MultiThreadedExecutor (4 threads de trabalho)
    ros_executor = None
    if ROS2_AVAILABLE:
        try:
            from rclpy.executors import MultiThreadedExecutor
            ros_executor = MultiThreadedExecutor(num_threads=4)
            ros_executor.add_node(orchestrator)
            ros_thread = threading.Thread(target=ros_executor.spin, daemon=True)
            orchestrator.log("Executor ROS 2 MultiThreaded ativado (4 threads dedicadas a I/O e callbacks).")
        except Exception as e:
            orchestrator.log(f"Aviso ao inicializar MultiThreadedExecutor ({e}). Usando spin padrão.")
            ros_thread = threading.Thread(target=lambda: rclpy.spin(orchestrator), daemon=True)
        ros_thread.start()

    # Sistema pronto para conexões
    orchestrator.log("Sistema pronto para conexões do dashboard.")

    # 6. Executa o loop WebSocket assíncrono na thread principal
    try:
        asyncio.run(main_ws_loop(orchestrator, PORT))
    except KeyboardInterrupt:
        print("\n[ORQUESTRADOR] Encerrando sistema...")
    finally:
        if orchestrator.physical:
            orchestrator.physical.close()
        # Encerramento limpo do stream 3D e do worker
        if hasattr(orchestrator, "map_stream") and orchestrator.map_stream:
            try:
                orchestrator.map_stream.stop()
            except Exception:
                pass
        # Encerramento limpo de todos os módulos de modules_dashboard/
        pm.stop_all()
        if ROS2_AVAILABLE:
            if ros_executor is not None:
                try:
                    ros_executor.shutdown()
                except Exception:
                    pass
            try:
                orchestrator.destroy_node()
            except Exception:
                pass
            try:
                if rclpy.ok():
                    rclpy.shutdown()
            except Exception:
                pass
        print("[ORQUESTRADOR] Sistema encerrado com sucesso.")

if __name__ == '__main__':
    main()
