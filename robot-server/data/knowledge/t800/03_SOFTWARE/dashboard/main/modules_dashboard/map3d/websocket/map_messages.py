#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contratos e Tipos de Mensagens WebSocket para o Mapeamento 3D.
Localização: backend/websocket/map_messages.py
"""

class MapMessages:
    # Tipos de eventos enviados do Robô para o Dashboard
    TYPE_POINTCLOUD = "map_3d/pointcloud"
    TYPE_POSE = "map_3d/pose"
    TYPE_TRAJECTORY = "map_3d/trajectory"
    TYPE_STATUS = "map_3d/status"
    TYPE_SCAN_STATUS = "map_3d/scan/status"
    TYPE_SCAN_LIST = "map_3d/scan/list"
    TYPE_STORAGE_INFO = "map_3d/storage/info"
    TYPE_CAMERA_POSE = "map_3d/camera_pose"

    # Ações recebidas do Dashboard pelo Robô
    ACTION_CLEAR = "map_3d/clear"
    ACTION_PAUSE = "map_3d/pause"
    ACTION_RESUME = "map_3d/resume"
    ACTION_SET_CONFIG = "map_3d/set_config"
    ACTION_REQUEST_SNAPSHOT = "map_3d/request_snapshot"
    ACTION_SCAN_START = "map_3d/scan/start"
    ACTION_SCAN_STOP = "map_3d/scan/stop"
    ACTION_SCAN_LIST = "map_3d/scan/list"
    ACTION_SCAN_DELETE = "map_3d/scan/delete"
    ACTION_SCAN_VIEW = "map_3d/scan/view"
    ACTION_STORAGE_INFO = "map_3d/storage/info"
    ACTION_ENABLE_LIDAR = "map_3d/enable_lidar"
    TYPE_LIDAR_STATUS = "map_3d/lidar_status"
