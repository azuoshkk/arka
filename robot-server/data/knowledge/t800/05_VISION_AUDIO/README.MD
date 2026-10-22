# Vision-Based Anti-Collision and Safety System for Autonomous Robots

A high-performance, multi-threaded computer vision pipeline designed for real-time robotic collision avoidance. This system utilizes a dual-loop architecture that separates rapid reflex reactions from heavy deep-learning perception to ensure low-latency safety responses without sacrificing accuracy.

---

## 🏗️ System Architecture

The project is built on a four-layer framework distributed across a multi-threaded processing pipeline:

1. **Fast Reflex Loop (Main Thread - Real-time / ~30 FPS):**
   * **Layer 1 (Ground Segmentation):** Rapidly identifies navigable floor space vs. obstacles.
   * **Layer 2 (Optical Flow):** Detects sudden motion vectors and imminent closure rates.
   * *Outcome:* Immediately triggers `GO`, `SLOW`, or `STOP` decisions for low-latency emergency reflexes.
2. **Heavy Perception Loop (Background Worker Thread - Async):**
   * **Layer 3 (YOLOv8n):** Detects and classifies known objects with bounding boxes and calculated risks.
   * **Layer 4 (Anomaly Detector / Autoencoder):** Identifies unknown obstacles or safety hazards that are neither recognized classes nor normal ground.
   * *Outcome:* Continuously updates safety weights, seamlessly integrated into the decision-making fusion engine.

---

## 🚀 Key Features

* **Interactive Camera Scanner:** Automatically detects, tests, and lists available camera indices (supporting integrated webcams and external 1080p USB cameras) with force-enabled MJPEG configuration.
* **Asynchronous Multi-threading:** Decouples heavy AI workloads from the core video capture loop to prevent system freezing or lag spikes.
* **Dynamic Calibration:** Includes an initial anomaly detector calibration sequence to map out a clear baseline path.
* **Hardware Agnostic Integration:** Modular stub design (`send_to_robot`) ready for integration with serial communication, ROS, GPIO, or custom microcontrollers.

---

## 📂 Project Structure

```text
visao_comp_arcanjo/
├── main.py              # Main execution loop, threading, and camera scanner
├── config.py            # System parameters, resolutions, and tuning variables
├── ground.py            # Layer 1: Ground segmentation module
├── optical_flow.py      # Layer 2: Optical flow motion tracking
├── obj_detector.py      # Layer 3: YOLOv8n object detection wrapper
├── anomaly_detector.py  # Layer 4: Autoencoder anomaly monitoring
├── fusion.py            # Decision fusion engine (GO / SLOW / STOP)
├── geometry.py          # Danger zones and spatial geometry utilities
├── requirements.txt     # Project dependencies
└── README.md            # Project documentation