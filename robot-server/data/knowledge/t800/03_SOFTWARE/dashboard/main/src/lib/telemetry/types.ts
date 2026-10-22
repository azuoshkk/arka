export type ConnectionStatus = 'CONNECTED' | 'DEGRADED' | 'DISCONNECTED' | 'WAITING';

export type TopicStatus = 'OK' | 'WARN' | 'ERROR' | 'ACTIVE' | 'SILENT' | 'DISCONNECTED';

export interface Quaternion {
  x: number | null;
  y: number | null;
  z: number | null;
  w: number | null;
}

export interface EulerAngles {
  pitch: number | null;
  roll: number | null;
  yaw: number | null;
}

export interface PowerState {
  battery_pct?: number | null;
  voltage?: number | null;
  current?: number | null;
  current_limit?: number | null;
  enable?: boolean | null;
  error_code?: number | null;
}

export interface TopicInfo {
  connected: boolean;
  msgs?: number;
  rate_hz?: number;
  last_msg_time?: number;
  elapsed_sec?: number | null;
  state?: 'ONLINE' | 'TIMEOUT' | 'INACTIVE' | 'DISCONNECTED';
}

// T800 Telemetry Payload
export interface JointStateData {
  names: string[];
  position: number[];
  velocity: number[];
  effort: number[];
}

export interface GamepadData {
  keys?: (number | boolean)[];
  hardware_connected?: boolean;
  digital_states?: number[];
  analog_states?: number[];
}

export interface BatteryData {
  percentage?: number | null;
  voltage?: number | null;
  current?: number | null;
  current_limit?: number | null;
  enable?: boolean | null;
  error_code?: number | null;
}

export interface MotionStateData {
  current_motion_task: string;
  available_transition_motions: string[];
}

export interface MotionPlanData {
  status: number;
  progress: number;
  request_id: number;
}

export interface MotorDebugData {
  motor_temperature: number[];
  mos_temperature: number[];
  voltage: number[];
  current: number[];
  error_code: number[];
  offline: boolean[];
  enable: boolean[];
  max_motor_temp?: number;
  max_mos_temp?: number;
}

export interface HeartbeatData {
  status: string;
  error_code: number;
  error_message: string;
  last_seen: number;
}

export interface ImuData {
  orientation?: Quaternion;
  angular_velocity?: { x: number; y: number; z: number };
  linear_acceleration?: { x: number; y: number; z: number };
  roll?: number;
  pitch?: number;
  yaw?: number;
  type?: string;
}

export interface T800Telemetry {
  timestamp?: number;
  connection_status?: 'CONNECTED' | 'DISCONNECTED';
  battery?: BatteryData | null;
  joints?: JointStateData | null;
  gamepad?: GamepadData | null;
  cameras?: {
    cam0?: string | null;
    cam1?: string | null;
    overlay?: string | null;
    gray?: string | null;
    person_annotated?: string | null;
    [key: string]: string | null | undefined;
  };
  camera_stats?: Record<string, {
    active?: boolean;
    msg_count?: number;
    fps?: number;
    [key: string]: unknown;
  }>;
  camera_info?: {
    [key: string]: {
      width: number;
      height: number;
    };
  };
  imu?: ImuData | null;
  imu_torso?: ImuData | null;
  imu_head?: ImuData | null;
  quaternion?: Quaternion;
  odometry?: {
    standard?: {
      pos: { x: number; y: number; z: number };
      vel: { linear: number; angular: number };
    };
    high_freq?: {
      pos: { x: number; y: number; z: number };
      vel: { linear: number; angular: number };
    };
    calibration?: {
      lidar2cam_x: number;
      lidar2imu_x: number;
    };
  };
  cloud_points?: number[];
  cloud_mode?: 'raw' | 'slam';
  audio?: {
    pcm?: string | null;
    sample_rate?: number;
    channels?: number;
    volume_level?: number;
  } | null;
  status?: Record<string, TopicInfo>;
  power?: PowerState;
  system?: {
    device_info?: string;
    is_offline?: boolean;
    network_quality?: string;
    resolution?: string;
    topic_prefix?: string;
  };
  recording?: {
    is_recording: boolean;
    camera?: string;
    filename?: string | null;
    duration?: number;
    frames?: number;
    download_url?: string | null;
  } | null;
  bag_recorder?: {
    status: string;
    is_recording: boolean;
  } | null;
  neck?: NeckData | null;
  motion_state?: MotionStateData | null;
  motion_plan?: MotionPlanData | null;
  motors_debug?: MotorDebugData | null;
  heartbeats?: Record<string, HeartbeatData> | null;
}

export interface NeckData {
  online?: boolean;
  is_moving?: boolean;
  current_pitch: number;
  current_yaw: number;
  current_pitch_deg?: number;
  current_yaw_deg?: number;
  target_pitch?: number;
  target_yaw?: number;
  target_pitch_deg?: number;
  target_yaw_deg?: number;
  actual_pitch?: number;
  actual_yaw?: number;
  has_hardware_feedback?: boolean;
  limits?: {
    pitch_min: number;
    pitch_max: number;
    pitch_min_deg?: number;
    pitch_max_deg?: number;
    yaw_min: number;
    yaw_max: number;
    yaw_min_deg?: number;
    yaw_max_deg?: number;
  };
  gains?: {
    kp: number;
    kd: number;
  };
  balance_mode_requested?: boolean;
  balance_mode_active?: boolean;
  simulation?: boolean;
}

export interface NetworkDiagnostics {
  latencyMs: number | null;
  packetRateHz: number;
  bandwidthKbps: number;
  totalPackets: number;
  lastPacketTime: number | null;
  reconnectAttempts: number;
}

// ==============================================================================
// TIPOS DE MAPEAMENTO 3D (ESTILO FOXGLOVE STUDIO)
// ==============================================================================
export interface Map3DPointCloud {
  type?: 'map_3d/pointcloud';
  timestamp?: number;
  frame_id: string;
  points: number[] | Float32Array; // Flat array or binary Float32Array
  point_count: number;
  min_z?: number;
  max_z?: number;
  is_paused?: boolean;
  t0_sensor?: number;
  t2_backend?: number;
  is_binary?: boolean;
}

export interface Map3DPose {
  type?: 'map_3d/pose';
  timestamp?: number;
  frame_id: string;
  position: {
    x: number;
    y: number;
    z: number;
  };
  orientation: {
    qx: number;
    qy: number;
    qz: number;
    qw: number;
  };
  yaw_deg: number;
  pitch_deg: number;
  roll_deg: number;
  camera_pose?: {
    x: number;
    y: number;
    z: number;
    qx: number;
    qy: number;
    qz: number;
    qw: number;
    frame_id: string;
  };
}

export interface Map3DTrajectoryPoint {
  x: number;
  y: number;
  z: number;
}

export interface Map3DTrajectory {
  type?: 'map_3d/trajectory';
  timestamp?: number;
  frame_id: string;
  points: Map3DTrajectoryPoint[];
  count: number;
}

export interface Map3DSensorsStatus {
  cloud: string;
  cloud_topic?: string;
  odometry: string;
  odometry_topic?: string;
  tf: string;
  slam: string;
}

export interface LatencyMetrics {
  sensor_to_backend_ms: number;
  backend_processing_ms: number;
  websocket_latency_ms: number;
  frontend_render_ms: number;
  total_latency_ms: number;
  cloud_hz?: number;
}

export interface ScanRecordingStatus {
  state: 'IDLE' | 'RECORDING' | 'PROCESSING' | 'READY' | 'ERROR';
  scan_id: string | null;
  profile: string;
  elapsed_sec: number;
  total_points: number;
  total_frames: number;
  disk_free_gb: number;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_usage_pct: number;
  error_message: string | null;
}

export interface StorageInfo {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  total_gb: number;
  used_gb: number;
  free_gb: number;
  usage_pct: number;
  scans_count: number;
  scans_total_mb: number;
  is_low_storage: boolean;
}

export interface ScanItem {
  id: string;
  name: string;
  date: string;
  start_time: number;
  duration: string;
  duration_sec: number;
  size_formatted: string;
  size_bytes: number;
  points: number;
  raw_points?: number;
  status: 'RECORDING' | 'PROCESSING' | 'READY' | 'ERROR' | string;
  profile: 'LIGHT' | 'STANDARD' | 'FULL';
  has_ply: boolean;
  has_pcd: boolean;
}

export interface Map3DStatus {
  type?: 'map_3d/status';
  timestamp?: number;
  state: 'ACTIVE' | 'PAUSED';
  lidar_enabled?: boolean;
  active_frame: string;
  fps: number;
  total_points: number;
  min_z?: number;
  max_z?: number;
  sensors?: Map3DSensorsStatus;
  latency?: Partial<LatencyMetrics>;
  recorder?: ScanRecordingStatus;
  storage?: StorageInfo;
  metrics?: {
    dropped_scans?: number;
    lidar_enabled?: boolean;
    total_binary_bytes?: number;
  };
}

export type CameraMode =
  | 'free'
  | 'fpv'
  | 'follow'
  | 'top'
  | 'front'
  | 'side'
  | 'orbit'
  | 'slam';

export type CameraLayout =
  | 'pip'
  | 'split-50'
  | 'split-70'
  | 'maximized'
  | 'hidden';

export type CameraFeedKey = 'cam0' | 'overlay';

export interface FollowCameraSettings {
  distance: number; // e.g. 2.0 to 15.0 meters (default 4.5)
  height: number;   // e.g. 0.5 to 6.0 meters (default 2.0)
  angle: number;    // e.g. 10 to 60 degrees (default 30)
}

export interface Map3DLayers {
  pointCloud: boolean;
  robot: boolean;
  trajectory: boolean;
  grid: boolean;
  axes: boolean;
  obstacles: boolean;
}

