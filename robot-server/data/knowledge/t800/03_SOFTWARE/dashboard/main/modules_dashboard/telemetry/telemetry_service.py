#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Telemetria de Hardware, Energia e Máquina de Estados (FSM).
Localização: modules_dashboard/telemetry/telemetry_service.py
Agrega diagnósticos de bateria/BMS, atuadores, juntas, gamepad, batimentos cardíacos e LEDs.
"""

import time
import math
import threading
from typing import Optional, Dict, Any, List
from modules_dashboard.common.base_module import BaseModule

STANDARD_JOINT_NAMES = [
    "leg_l_hip_yaw", "leg_l_hip_roll", "leg_l_hip_pitch", "leg_l_knee", "leg_l_ankle_pitch", "leg_l_ankle_roll",
    "leg_r_hip_yaw", "leg_r_hip_roll", "leg_r_hip_pitch", "leg_r_knee", "leg_r_ankle_pitch", "leg_r_ankle_roll",
    "waist_yaw",
    "arm_l_shoulder_pitch", "arm_l_shoulder_roll", "arm_l_shoulder_yaw", "arm_l_elbow", "arm_l_wrist",
    "arm_r_shoulder_pitch", "arm_r_shoulder_roll", "arm_r_shoulder_yaw", "arm_r_elbow", "arm_r_wrist",
    "head_pitch", "head_yaw"
]

class TelemetryService(BaseModule):
    """Serviço centralizador de telemetria de hardware e diagnóstico elétrico/mecânico."""
    def __init__(self, logger: Optional[Any] = None):
        super().__init__("telemetry", logger)
        self.lock = threading.RLock()
        
        self.battery_data = None
        self.power_data = None
        self.motion_state = None
        self.motion_plan = None
        self.motors_debug = None
        self.joints_data = None
        self.gamepad_data = None
        self.heartbeats: Dict[str, Dict[str, Any]] = {}
        self.bag_recorder_status = "IDLE"
        self.system_info = {
            "device_info": "T800 Robot System",
            "is_offline": False,
            "network_quality": "Good",
            "resolution": "640x480",
            "topic_prefix": ""
        }
        
        self.led_publisher = None
        self.led_msg_class = None
        self.bag_record_publisher = None
        self.bag_stop_publisher = None
        self.string_msg_class = None
        self.bool_msg_class = None

    def initialize(self, context: Optional[Dict[str, Any]] = None) -> bool:
        if context:
            self.led_publisher = context.get("led_publisher", self.led_publisher)
            self.led_msg_class = context.get("led_msg_class", self.led_msg_class)
            self.bag_record_publisher = context.get("bag_record_publisher", self.bag_record_publisher)
            self.bag_stop_publisher = context.get("bag_stop_publisher", self.bag_stop_publisher)
            self.string_msg_class = context.get("string_msg_class", self.string_msg_class)
            self.bool_msg_class = context.get("bool_msg_class", self.bool_msg_class)
        self.is_initialized = True
        self.status = "INITIALIZED"
        self.log("Módulo de telemetria inicializado.")
        return True

    def start(self) -> bool:
        self.is_running = True
        self.start_time = time.time()
        self.status = "RUNNING"
        self.log("Módulo de telemetria ativo.")
        return True

    def stop(self) -> bool:
        self.is_running = False
        self.status = "STOPPED"
        return True

    # --------------------------------------------------------------------------
    # Callbacks de Dados de Hardware
    # --------------------------------------------------------------------------
    def process_power_info(self, msg):
        """Processa telemetria do barramento elétrico e relé BMS (/hardware/power_info)."""
        pct = round(float(getattr(msg, 'percentage', 0.0)), 1)
        v = round(float(getattr(msg, 'voltage', 0.0)), 2)
        c = round(float(getattr(msg, 'current', 0.0)), 2)
        limit = round(float(getattr(msg, 'current_limit', 0.0)), 2)
        enable = bool(getattr(msg, 'enable', True))
        err = int(getattr(msg, 'error_code', 0))

        with self.lock:
            self.battery_data = {
                "percentage": pct, "voltage": v, "current": c,
                "current_limit": limit, "enable": enable, "error_code": err
            }
            self.power_data = {
                "battery_pct": pct, "voltage": v, "current": c,
                "current_limit": limit, "enable": enable, "error_code": err
            }

    def process_battery_state(self, msg):
        """Processa sensor_msgs/msg/BatteryState padrão."""
        pct = 100.0 if math.isnan(msg.percentage) else (msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage)
        v = float(msg.voltage) if not math.isnan(msg.voltage) else 0.0
        c = float(msg.current) if not math.isnan(msg.current) else 0.0

        with self.lock:
            b_data = {"percentage": round(pct, 1), "voltage": round(v, 2), "current": round(c, 2)}
            self.battery_data = b_data
            if not self.power_data:
                self.power_data = {
                    "battery_pct": round(pct, 1), "voltage": round(v, 2),
                    "current": round(c, 2), "enable": True, "error_code": 0
                }

    def process_motion_state(self, msg):
        """Processa a máquina de estados finitos (/motion/motion_state)."""
        with self.lock:
            self.motion_state = {
                "current_motion_task": str(getattr(msg, 'current_motion_task', '')),
                "available_transition_motions": [str(m) for m in getattr(msg, 'available_transition_motions', [])]
            }

    def process_motion_plan_state(self, msg):
        """Processa estado e progresso do planejador (/motion/joint_motion_plan/state)."""
        with self.lock:
            self.motion_plan = {
                "status": int(getattr(msg, 'status', 0)),
                "progress": round(float(getattr(msg, 'progress', 0.0)), 3),
                "request_id": int(getattr(msg, 'request_id', 0))
            }

    def process_motor_debug(self, msg):
        """Processa diagnóstico elétrico e térmico de todos os motores (/hardware/motor_debug)."""
        m_temp = [round(float(x), 1) for x in getattr(msg, 'motor_temperature', [])]
        mos_temp = [round(float(x), 1) for x in getattr(msg, 'mos_temperature', [])]
        with self.lock:
            self.motors_debug = {
                "motor_temperature": m_temp,
                "mos_temperature": mos_temp,
                "voltage": [round(float(x), 2) for x in getattr(msg, 'voltage', [])],
                "current": [round(float(x), 2) for x in getattr(msg, 'current', [])],
                "error_code": [int(x) for x in getattr(msg, 'error_code', [])],
                "offline": [bool(x) for x in getattr(msg, 'offline', [])],
                "enable": [bool(x) for x in getattr(msg, 'enable', [])],
                "max_motor_temp": max(m_temp) if m_temp else 0.0,
                "max_mos_temp": max(mos_temp) if mos_temp else 0.0
            }

    def process_joint_states(self, msg):
        """Processa posições, velocidades e esforços articulares."""
        names = list(getattr(msg, 'name', [])) or STANDARD_JOINT_NAMES[:len(msg.position)]
        efforts = getattr(msg, 'effort', None) or getattr(msg, 'torque', [])
        with self.lock:
            self.joints_data = {
                "names": names,
                "position": [round(float(p), 4) for p in msg.position],
                "velocity": [round(float(v), 4) for v in getattr(msg, 'velocity', [])],
                "effort": [round(float(e), 3) for e in efforts]
            }

    def process_gamepad_keys(self, msg):
        """Processa botões e eixos analógicos do controle oficial (/hardware/gamepad_keys)."""
        dig = [int(x) for x in getattr(msg, 'digital_states', [])]
        with self.lock:
            self.gamepad_data = {
                "hardware_connected": bool(getattr(msg, 'hardware_connected', False)),
                "digital_states": dig,
                "analog_states": [round(float(x), 3) for x in getattr(msg, 'analog_states', [])],
                "keys": dig
            }

    def process_joy(self, msg):
        """Processa sensor_msgs/msg/Joy."""
        with self.lock:
            self.gamepad_data = {"keys": [bool(b) for b in msg.buttons]}

    def process_heartbeat(self, msg):
        """Processa heartbeat de sincronismo (/heartbeat)."""
        with self.lock:
            self.heartbeats[str(getattr(msg, 'node_name', 'node'))] = {
                "status": str(getattr(msg, 'node_status', 'running')),
                "error_code": int(getattr(msg, 'error_code', 0)),
                "error_message": str(getattr(msg, 'error_message', '')),
                "last_seen": time.time()
            }

    def process_system_driver_string(self, topic_name: str, val: str):
        with self.lock:
            for k in ['device_info', 'resolution', 'topic_prefix']:
                if k in topic_name:
                    self.system_info[k] = val

    def process_system_driver_bool(self, topic_name: str, val: bool):
        with self.lock:
            if 'device_offline' in topic_name:
                self.system_info['is_offline'] = val

    def process_bag_status(self, val: str):
        with self.lock:
            self.bag_recorder_status = str(val).strip()

    def start_bag_recording(self, filename: str = "") -> bool:
        if not self.bag_record_publisher or not self.string_msg_class:
            return False
        try:
            fname = filename or f"t800_session_{int(time.time())}"
            msg = self.string_msg_class()
            msg.data = fname
            self.bag_record_publisher.publish(msg)
            with self.lock:
                self.bag_recorder_status = f"RECORDING ({fname})"
            return True
        except Exception as e:
            self.record_error(e, "start_bag_recording")
            return False

    def stop_bag_recording(self) -> bool:
        if not self.bag_stop_publisher or not self.bool_msg_class:
            return False
        try:
            msg = self.bool_msg_class()
            msg.data = True
            self.bag_stop_publisher.publish(msg)
            with self.lock:
                self.bag_recorder_status = "STOPPING"
            return True
        except Exception as e:
            self.record_error(e, "stop_bag_recording")
            return False

    def set_led_control(self, color: int) -> bool:
        if not self.led_publisher or not self.led_msg_class:
            return False
        try:
            msg = self.led_msg_class()
            msg.color = int(color)
            self.led_publisher.publish(msg)
            return True
        except Exception as e:
            self.record_error(e, "set_led_control")
            return False

    def get_telemetry_snapshot(self, is_slow_frame: bool = False) -> Dict[str, Any]:
        """Retorna os dados compilados de hardware para o pacote de telemetria."""
        with self.lock:
            snap = {
                "battery": self.battery_data,
                "power": self.power_data,
                "motion_state": self.motion_state,
                "motion_plan": self.motion_plan,
                "motors_debug": self.motors_debug,
                "gamepad": self.gamepad_data,
                "bag_recorder": {
                    "status": self.bag_recorder_status,
                    "is_recording": "RECORDING" in self.bag_recorder_status.upper()
                },
                "heartbeats": dict(self.heartbeats)
            }
            if is_slow_frame:
                snap["joints"] = self.joints_data
                snap["system"] = dict(self.system_info)
            return snap

    def get_status(self) -> Dict[str, Any]:
        st = super().get_status()
        with self.lock:
            st.update({
                "bms_enabled": bool(self.power_data.get("enable", False)) if self.power_data else False,
                "fsm_task": self.motion_state.get("current_motion_task", "") if self.motion_state else "",
                "heartbeats_count": len(self.heartbeats),
                "has_joints": self.joints_data is not None
            })
        return st
