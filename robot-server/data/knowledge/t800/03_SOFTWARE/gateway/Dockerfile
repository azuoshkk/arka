# Usa a imagem oficial e super leve do ROS2
FROM ros:humble-ros-base

# Instala o OpenCV e os plugins de vídeo sem latência (GStreamer)
RUN apt-get update && apt-get install -y \
    python3-opencv python3-numpy \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    && rm -rf /var/lib/apt/lists/*

# Prepara a pasta de trabalho
WORKDIR /app
COPY t800_bridge.py .

# Comando que será executado ao ligar o contentor
CMD ["/bin/bash", "-c", "source /opt/ros/humble/setup.bash && python3 t800_bridge.py"]
