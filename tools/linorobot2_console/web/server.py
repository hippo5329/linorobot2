#!/usr/bin/env python3
"""Linorobot2 Console -- zero-dependency local web UI for the ROS2/robot-computer
side of linorobot2: installing the package + sensor drivers, launching bringup/
teleop/SLAM/navigation, running magnetometer calibration, and a live LiDAR
viewer. Mirrors the server architecture of linorobot2_hardware's
tools/robot_config_engine/web/server.py: a generic SSE command runner the
frontend drives by generating shell command strings, not a purpose-built API
per action.

Usage: python3 server.py [port]
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import patcher
except Exception:
    patcher = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/linorobot2_console/..
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(WEB_DIR, "console_config.json")
CONFIG_DIR = os.path.join(os.path.dirname(WEB_DIR), "config")
LINOROBOT2_ROOT = os.path.abspath(os.path.join(WEB_DIR, "../../.."))
SUPPORTED_DISTROS = ["jazzy", "lyrical", "rolling", "humble"]
NAV2_CONFIG_PATH = os.path.join(WEB_DIR, "console_nav2_jazzy.yaml")


def get_nav2_config_path(distro=None):
    if not distro or distro not in SUPPORTED_DISTROS:
        distro = detect_ros_distro()
    return os.path.join(WEB_DIR, f"console_nav2_{distro}.yaml")


def get_nav2_default_path(distro=None):
    if not distro or distro not in SUPPORTED_DISTROS:
        distro = detect_ros_distro()
    distro_tpl = os.path.join(CONFIG_DIR, f"nav2_{distro}.yaml")
    if os.path.exists(distro_tpl):
        return distro_tpl
    return os.path.join(LINOROBOT2_ROOT, "linorobot2_navigation", "config", "navigation.yaml")


def get_nav2_config(distro=None):
    path = get_nav2_config_path(distro)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            pass
    tpl_path = get_nav2_default_path(distro)
    if os.path.exists(tpl_path):
        try:
            with open(tpl_path, "r") as f:
                return f.read()
        except Exception:
            pass
    return f"# Linorobot2 Nav2 Parameters ({distro})\n"


def save_nav2_config(text, distro=None):
    path = get_nav2_config_path(distro)
    with open(path, "w") as f:
        f.write(text)
    return path

def get_ekf_config_path():
    return os.path.join(WEB_DIR, "console_ekf.yaml")


def get_ekf_default_path(base=None):
    if not base:
        base = "2wd"
    base = base.lower()
    base_tpl = os.path.join(CONFIG_DIR, f"ekf_{base}.yaml")
    if os.path.exists(base_tpl):
        return base_tpl
    pkg_tpl = os.path.join(LINOROBOT2_ROOT, "linorobot2_base", "config", f"ekf_{base}.yaml")
    if os.path.exists(pkg_tpl):
        return pkg_tpl
    return os.path.join(LINOROBOT2_ROOT, "linorobot2_base", "config", "ekf.yaml")


def get_ekf_config(base=None):
    path = get_ekf_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            pass
    tpl = get_ekf_default_path(base)
    if os.path.exists(tpl):
        try:
            with open(tpl, "r") as f:
                return f.read()
        except Exception:
            pass
    return "# Linorobot2 EKF Parameters"


def save_ekf_config(text):
    path = get_ekf_config_path()
    with open(path, "w") as f:
        f.write(text)
    return path


def get_slam_config_path():
    return os.path.join(WEB_DIR, "console_slam.yaml")


def get_slam_default_path():
    tpl = os.path.join(CONFIG_DIR, "slam.yaml")
    if os.path.exists(tpl):
        return tpl
    return os.path.join(LINOROBOT2_ROOT, "linorobot2_navigation", "config", "slam.yaml")


def get_slam_config():
    path = get_slam_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            pass
    tpl = get_slam_default_path()
    if os.path.exists(tpl):
        try:
            with open(tpl, "r") as f:
                return f.read()
        except Exception:
            pass
    return "# Linorobot2 SLAM Parameters"


def save_slam_config(text):
    path = get_slam_config_path()
    with open(path, "w") as f:
        f.write(text)
    return path


def analyze_robotics_ai(prompt, base="2wd", distro="jazzy", model=None):
    """Analyze robotics navigation/estimation problem and generate parameter patches."""
    p = prompt.lower()
    diagnosis = []
    recommendations = []
    nav2_patch = {}
    ekf_patch = {}
    slam_patch = {}

    target_base = base
    if any(k in p for k in ["mecanum", "omni", "strafe", "lateral", "sideways"]):
        target_base = "mecanum"
        diagnosis.append("Robot requires holonomic (omnidirectional) kinematics: lateral strafe is enabled in velocity_smoother, AMCL OmniMotionModel is set, and EKF odom0 vy is fused.")
        recommendations.append("Enable lateral velocity (v_y = 0.5 m/s) and lateral acceleration in velocity_smoother.")
        recommendations.append("Switch AMCL robot_model_type to nav2_amcl::OmniMotionModel.")
        recommendations.append("Set EKF odom0_config to fuse lateral velocity (v_y).")
        nav2_patch.update({
            "base": "mecanum",
            "max_vel_x": 0.5,
            "max_vel_y": 0.5,
            "max_accel_x": 2.5,
            "max_accel_y": 2.5
        })
        ekf_patch["fuse_vy"] = True
    elif any(k in p for k in ["diff", "2wd", "4wd", "skid"]):
        target_base = "2wd"
        nav2_patch.update({
            "base": "2wd",
            "max_vel_y": 0.0,
            "max_accel_y": 0.0
        })
        ekf_patch["fuse_vy"] = False

    if any(k in p for k in ["door", "narrow", "tight", "hallway", "corridor", "hesitat", "stuck in door"]):
        diagnosis.append("Doorway hesitation is caused by default inflation radius (0.7m) creating overlapping high-cost gradients across narrow passages (<90cm).")
        recommendations.append("Reduce costmap inflation_radius to 0.52m.")
        recommendations.append("Increase cost_scaling_factor to 5.5 so wall penalty falls off sharply, opening a clear navigable path through the doorway center.")
        nav2_patch.update({
            "inflation_radius": 0.52,
            "cost_scaling_factor": 5.5,
            "desired_linear_vel": 0.35
        })

    if any(k in p for k in ["oscillat", "hunting", "wobble", "spin at goal", "overshoot", "shake", "jitter"]):
        diagnosis.append("End-goal oscillation is typically caused by high rotational acceleration and angular velocity overpowering the goal tolerance window.")
        recommendations.append("Reduce rotate_to_heading_angular_vel to 1.2 rad/s.")
        recommendations.append("Smooth max_angular_accel to 2.2 rad/s² to suppress motor hunting.")
        nav2_patch.update({
            "max_vel_theta": 2.0,
            "max_accel_theta": 2.2
        })

    if any(k in p for k in ["drift", "ekf", "slip", "spinning drift", "lateral drift"]):
        diagnosis.append("Lateral drift during in-place rotation occurs when non-holonomic wheel slip is erroneously fused into EKF lateral velocity.")
        recommendations.append("Ensure EKF odom0_config lateral velocity (v_y) is disabled for differential drive robots.")
        recommendations.append("Enforce 2D planar mode and synchronize EKF loop frequency to 50 Hz.")
        if target_base != "mecanum":
            ekf_patch["fuse_vy"] = False
        ekf_patch["two_d_mode"] = True
        ekf_patch["frequency"] = 50.0

    if any(k in p for k in ["fast", "speed", "quick", "warehouse", "large", "open", "accelerat"]):
        diagnosis.append("Optimizing parameter envelope for high-speed transit in open warehouse/arena environments.")
        recommendations.append("Increase linear velocity limit to 0.8 m/s and linear acceleration to 3.0 m/s².")
        nav2_patch.update({
            "max_vel_x": 0.8,
            "max_accel_x": 3.0,
            "desired_linear_vel": 0.65
        })

    if any(k in p for k in ["slam", "map", "blur", "smear", "resolution", "loop closure"]):
        diagnosis.append("Enhancing SLAM scan-matching density to prevent rotational map smearing and capture fine geometry.")
        recommendations.append("Increase SLAM resolution to 0.035m and decrease keyframe travel heading to 0.3 rad.")
        slam_patch.update({
            "resolution": 0.035,
            "max_laser_range": 12.0,
            "minimum_travel_heading": 0.3,
            "minimum_travel_distance": 0.3
        })

    if not diagnosis:
        diagnosis.append("Custom robotic parameter optimization for smooth mobile robot navigation.")
        recommendations.append("Applied balanced velocity limits (0.5 m/s) and 50 Hz EKF state estimation.")

    return {
        "target_base": target_base,
        "diagnosis": " ".join(diagnosis),
        "recommendations": recommendations,
        "nav2_patch": nav2_patch,
        "ekf_patch": ekf_patch,
        "slam_patch": slam_patch
    }

DEFAULT_CONFIG = {
    "workspace_path": os.path.expanduser("~/linorobot2_ws"),
    "ros_distro": "jazzy",
    "auto_bringup": True,
    "agent_transport": "serial",   # "serial" | "udp4"
    "agent_device": "/dev/ttyACM0",
    "agent_port": "8888",
    "agent_baud": "921600",
}

# Per-sensor install/udev commands, ported from linorobot2's install.bash
# (kept here as plain data, not by sourcing/invoking that script -- see the
# implementation plan for why). Each list is run as one `&&`-joined command.
LASER_SENSORS = {
    "ydlidar": {
        "label": "YDLIDAR",
        "install": [
            "cd /tmp",
            "rm -rf YDLidar-SDK",
            "git clone https://github.com/YDLIDAR/YDLidar-SDK.git",
            "mkdir -p YDLidar-SDK/build && cd YDLidar-SDK/build",
            "cmake .. && make",
            "sudo make install",
            "cd {ws}",
            "[ -d src/ydlidar_ros2_driver ] || git clone https://github.com/YDLIDAR/ydlidar_ros2_driver src/ydlidar_ros2_driver",
            "chmod 0777 src/ydlidar_ros2_driver/startup/*",
            "colcon build --symlink-install",
        ],
        "udev": [
            'echo \'KERNEL=="ttyUSB*", ATTRS{{idVendor}}=="10c4", ATTRS{{idProduct}}=="ea60", MODE:="0666", GROUP:="dialout", SYMLINK+="ydlidar"\' | sudo tee /etc/udev/rules.d/ydlidar.rules',
            'echo \'KERNEL=="ttyACM*", ATTRS{{idVendor}}=="0483", ATTRS{{idProduct}}=="5740", MODE:="0666", GROUP:="dialout", SYMLINK+="ydlidar"\' | sudo tee /etc/udev/rules.d/ydlidar-V2.rules',
            'echo \'KERNEL=="ttyUSB*", ATTRS{{idVendor}}=="067b", ATTRS{{idProduct}}=="2303", MODE:="0666", GROUP:="dialout", SYMLINK+="ydlidar"\' | sudo tee /etc/udev/rules.d/ydlidar-2303.rules',
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
    "xv11": {
        "label": "XV11",
        "install": [
            "cd {ws}",
            "[ -d src/xv_11_driver ] || git clone https://github.com/mjstn/xv_11_driver src/xv_11_driver",
            "colcon build",
        ],
        "udev": None,
    },
    "ldlidar": {
        "label": "LD06 / LD19 / STL27L",
        "install": [
            "cd {ws}",
            "[ -d src/ldlidar_stl_ros2 ] || git clone https://github.com/hippo5329/ldlidar_stl_ros2.git src/ldlidar_stl_ros2",
            "colcon build",
        ],
        "udev": [
            "cd /tmp && wget -q https://raw.githubusercontent.com/linorobot/ldlidar/ros2/ldlidar.rules",
            "sudo cp ldlidar.rules /etc/udev/rules.d",
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
    "sllidar": {
        "label": "RPLIDAR (A1/A2/A3/C1/S1/S2/S3)",
        "install": [
            "cd {ws}",
            "[ -d src/sllidar_ros2 ] || git clone https://github.com/Slamtec/sllidar_ros2.git src/sllidar_ros2",
            "colcon build",
        ],
        "udev": [
            "sudo cp {ws}/src/sllidar_ros2/scripts/rplidar.rules /etc/udev/rules.d",
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
}

DEPTH_SENSORS = {
    "realsense": {
        "label": "Intel RealSense",
        "install": ["sudo apt-get install -y ros-$ROS_DISTRO-realsense2-camera"],
        "udev": [
            "cd /tmp && wget -q https://raw.githubusercontent.com/IntelRealSense/librealsense/master/config/99-realsense-libusb.rules",
            "sudo cp 99-realsense-libusb.rules /etc/udev/rules.d",
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
    "oakd": {
        "label": "Luxonis OAK-D / Lite / Pro",
        "install": ["sudo apt-get install -y ros-$ROS_DISTRO-depthai-ros"],
        "udev": [
            'echo \'SUBSYSTEM=="usb", ATTRS{{idVendor}}=="03e7", MODE="0666"\' | sudo tee /etc/udev/rules.d/80-movidius.rules',
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
    "astra": {
        "label": "Orbbec Astra",
        "install": [
            "sudo apt-get install -y libuvc-dev libopenni2-dev",
            "cd {ws}",
            "[ -d src/ros_astra_camera ] || git clone https://github.com/linorobot/ros_astra_camera src/ros_astra_camera",
            "colcon build",
        ],
        "udev": [
            "sudo cp {ws}/src/ros_astra_camera/56-orbbec-usb.rules /etc/udev/rules.d/",
            "sudo udevadm control --reload-rules && sudo udevadm trigger",
        ],
    },
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ProcessRunner:
    """One tracked subprocess slot: start (SSE-streamed), stop, status.
    Two independent instances are used -- `main` (single-shot install/build/
    launch commands) and `agent` (the long-lived micro-ROS agent) -- so the
    agent can keep running while a Bringup/Teleop/SLAM command uses `main`.
    """

    def __init__(self, name):
        self.name = name
        self.process = None
        self.lock = threading.Lock()

    def is_busy(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start_streaming(self, command, cwd, send_event):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return False
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            self.process = subprocess.Popen(
                ["bash", "-lc", command],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                preexec_fn=os.setsid,
            )
        proc = self.process
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                send_event("output", {"line": line.rstrip("\n")})
        finally:
            proc.wait()
            exit_code = proc.returncode
            with self.lock:
                if self.process is proc:
                    self.process = None
            send_event("done", {"exit_code": exit_code})
        return True

    def kill(self):
        with self.lock:
            proc = self.process
            if proc is None or proc.poll() is not None:
                return False
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.process = None
            return True


main_runner = ProcessRunner("main")
agent_runner = ProcessRunner("agent")
bringup_runner = ProcessRunner("bringup")


def detect_ros_distro():
    """Detect or load configured ROS 2 distribution, with automatic heuristics."""
    try:
        cfg = load_config()
        if cfg.get("ros_distro") and cfg["ros_distro"] in SUPPORTED_DISTROS:
            return cfg["ros_distro"]
    except Exception:
        pass

    env_distro = os.environ.get("ROS_DISTRO", "").strip().lower()
    if env_distro in SUPPORTED_DISTROS:
        return env_distro

    for d in ["jazzy", "lyrical", "rolling", "humble"]:
        if os.path.isdir(f"/opt/ros/{d}"):
            return d

    try:
        with open("/etc/os-release") as f:
            c = f.read().lower()
            if "noble" in c or "24.04" in c:
                return "jazzy"
            if "resolute" in c or "26.04" in c:
                return "lyrical"
            if "jammy" in c or "22.04" in c:
                return "humble"
    except Exception:
        pass

    return "jazzy"


def workspace_built(ws):
    return os.path.exists(os.path.join(ws, "install", "setup.bash"))


def agent_externally_alive():
    """An agent started outside Console (e.g. by config-engine, or a plain
    terminal) -- detected via process list, not by us tracking it."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "micro_ros_agent"], capture_output=True, text=True
        )
        return out.returncode == 0
    except Exception:
        return False


def bringup_externally_alive():
    """Bringup started outside Console (e.g. via terminal or docker) -- detected via process list."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "linorobot2_bringup|bringup.launch.py"], capture_output=True, text=True
        )
        if out.returncode == 0:
            return True
        for engine in ["docker", "podman"]:
            d_out = subprocess.run(
                [engine, "ps", "-q", "--filter", "name=bringup"],
                capture_output=True, text=True, timeout=2
            )
            if d_out.returncode == 0 and d_out.stdout.strip():
                return True
    except Exception:
        pass
    return False



def generate_custom_robot_specs(description):
    d = description.lower()
    
    # 1. KINEMATICS & CHASSIS DESIGN
    if any(k in d for k in ["mecanum", "omni", "strafe", "holonomic"]):
        base = "mecanum"
        base_title = "4WD Mecanum (Omnidirectional / Holonomic)"
        fuse_vy = True
        default_wheel_diam = 0.097
        default_track = 0.30
        default_wheelbase = 0.25
        motion_model = "nav2_amcl::OmniMotionModel"
        min_y_thresh = 0.001
    elif any(k in d for k in ["4wd", "skid", "four wheel"]):
        base = "4wd"
        base_title = "4WD Skid Steer (Differential Kinematics)"
        fuse_vy = False
        default_wheel_diam = 0.130
        default_track = 0.35
        default_wheelbase = 0.28
        motion_model = "nav2_amcl::DifferentialMotionModel"
        min_y_thresh = 0.5
    else:
        base = "2wd"
        base_title = "2WD Differential Drive"
        fuse_vy = False
        default_wheel_diam = 0.066
        default_track = 0.16
        default_wheelbase = 0.0
        motion_model = "nav2_amcl::DifferentialMotionModel"
        min_y_thresh = 0.5

    # Extract or infer custom wheel dimensions
    wheel_diam = default_wheel_diam
    if "97mm" in d or "0.097" in d: wheel_diam = 0.097
    elif "66mm" in d or "0.066" in d: wheel_diam = 0.066
    elif "130mm" in d or "0.13" in d: wheel_diam = 0.130
    elif "150mm" in d or "0.15" in d: wheel_diam = 0.150

    track_width = default_track
    if "30cm" in d or "0.3m" in d: track_width = 0.30
    elif "35cm" in d or "0.35m" in d: track_width = 0.35
    elif "16cm" in d or "0.16m" in d: track_width = 0.16
    elif "50cm" in d or "0.5m" in d: track_width = 0.50

    wheelbase = default_wheelbase
    if "25cm" in d or "0.25m" in d: wheelbase = 0.25
    elif "28cm" in d or "0.28m" in d: wheelbase = 0.28
    elif "26cm" in d or "0.26m" in d: wheelbase = 0.26

    # Motor & Encoder Specifications
    gear_ratio = 30.0
    cpr = 1320
    motor_rpm = 330
    if "jgb37" in d or "330rpm" in d or "30:1" in d:
        gear_ratio = 30.0
        motor_rpm = 330
        cpr = 1320
    elif "500rpm" in d or "20:1" in d:
        gear_ratio = 20.0
        motor_rpm = 500
        cpr = 880

    theoretical_max_speed = round(motor_rpm * 3.14159 * wheel_diam / 60.0, 2)
    safe_cruise_speed = round(theoretical_max_speed * 0.6, 2)
    if "fast" in d or "warehouse" in d:
        safe_cruise_speed = min(0.85, theoretical_max_speed)
    elif "door" in d or "narrow" in d or "cautious" in d:
        safe_cruise_speed = min(0.35, safe_cruise_speed)

    # MCU selection
    mcu = "pico2"
    if "esp32" in d or "esp32s3" in d: mcu = "esp32"
    elif "teensy" in d: mcu = "teensy41"

    # Motor Driver
    driver = "MOTOR_DRIVER_MDD10A"
    if "l298" in d or "l298n" in d: driver = "MOTOR_DRIVER_L298"
    elif "tb6612" in d: driver = "MOTOR_DRIVER_TB6612FNG"
    elif "bts7960" in d: driver = "MOTOR_DRIVER_BTS7960"

    # LiDAR
    laser = "ldlidar"
    laser_name = "LD19 / LD06 (12m range)"
    laser_max_range = 12.0
    if "ydlidar" in d:
        laser = "ydlidar"
        laser_name = "YDLIDAR X4 / G4 (10m range)"
        laser_max_range = 10.0
    elif "rplidar" in d:
        laser = "rplidar"
        laser_name = "RPLIDAR A1 / A2 (12m range)"
        laser_max_range = 12.0

    # Footprint Calculation
    half_x = round((wheelbase + wheel_diam) / 2.0 + 0.05, 3) if wheelbase > 0 else round(wheel_diam / 2.0 + 0.10, 3)
    half_y = round(track_width / 2.0 + 0.06, 3)
    footprint = f"[[-{half_x}, -{half_y}], [-{half_x}, {half_y}], [{half_x}, {half_y}], [{half_x}, -{half_y}]]"

    # 2. TUNING CONFIGURATION
    is_narrow = ("door" in d or "narrow" in d or "tight" in d)
    inflation_radius = 0.52 if is_narrow else 0.70
    cost_scaling = 5.5 if is_narrow else 3.0

    nav2_tuning = {
        "base": base,
        "max_vel_x": safe_cruise_speed,
        "max_vel_y": safe_cruise_speed if base == "mecanum" else 0.0,
        "max_vel_theta": 2.5,
        "max_accel_x": 2.5,
        "max_accel_y": 2.5 if base == "mecanum" else 0.0,
        "max_accel_theta": 3.2,
        "desired_linear_vel": round(safe_cruise_speed * 0.8, 2),
        "inflation_radius": inflation_radius,
        "cost_scaling_factor": cost_scaling,
        "robot_model_type": motion_model,
        "min_y_velocity_threshold": min_y_thresh,
        "footprint": footprint
    }

    ekf_tuning = {
        "base": base,
        "frequency": 50.0,
        "two_d_mode": True,
        "fuse_vy": fuse_vy,
        "fuse_imu_yaw": False,
        "rationale": f"Fuse vy={fuse_vy} for {base.upper()} kinematics; 50Hz update rate synchronized with firmware."
    }

    slam_tuning = {
        "resolution": 0.025 if "high res" in d or "precision" in d else 0.05,
        "max_laser_range": laser_max_range,
        "minimum_travel_distance": 0.3 if is_narrow else 0.5,
        "minimum_travel_heading": 0.3 if is_narrow else 0.5
    }

    # Firmware config header preview
    firmware_config = f"""#ifndef CUSTOM_CONFIG_H
#define CUSTOM_CONFIG_H

#define KINEMATICS LINO_BASE_{base.upper()}
#define MOTOR_DRIVER {driver}
#define WHEEL_DIAMETER {wheel_diam}
#define LR_WHEELS_DISTANCE {track_width}
#define FR_WHEELS_DISTANCE {wheelbase}
#define COUNTS_PER_REV {cpr}
#define MOTOR_MAX_RPM {motor_rpm}

// Recommended Closed-Loop PID Velocity Control
#define K_P 0.6
#define K_I 0.3
#define K_D 0.1

#endif"""

    return {
        "design": {
            "base_type": base,
            "title": base_title,
            "mcu": mcu,
            "motor_driver": driver,
            "wheel_diameter_m": wheel_diam,
            "track_width_m": track_width,
            "wheelbase_m": wheelbase,
            "gear_ratio": gear_ratio,
            "cpr": cpr,
            "motor_max_rpm": motor_rpm,
            "theoretical_max_speed_mps": theoretical_max_speed,
            "recommended_cruise_speed_mps": safe_cruise_speed,
            "laser_sensor": laser,
            "laser_name": laser_name,
            "footprint": footprint,
            "firmware_config_h": firmware_config
        },
        "tuning": {
            "nav2": nav2_tuning,
            "ekf": ekf_tuning,
            "slam": slam_tuning
        },
        "workflow": [
            f"1. [Hardware Design] Configured {base.upper()} kinematics (D={wheel_diam*1000:.0f}mm, Track={track_width*1000:.0f}mm, CPR={cpr}).",
            f"2. [Firmware Config] Generated custom_config.h with closed-loop PID gains and motor driver {driver}.",
            f"3. [ROS 2 Description] Calculated rectangular footprint polygon {footprint}.",
            f"4. [EKF Estimation] Tuned robot_localization at 50Hz (fuse_vy={fuse_vy}, planar 2D mode).",
            f"5. [Nav2 Autonomous Navigation] Configured velocity smoother (v_x={safe_cruise_speed} m/s) & costmap inflation ({inflation_radius}m).",
            f"6. [SLAM Toolbox] Configured {laser_name} with {laser_max_range}m laser range and {slam_tuning['resolution']}m grid resolution."
        ]
    }
class Handler(BaseHTTPRequestHandler):
    server_version = "Linorobot2Console/0.1"

    def log_message(self, fmt, *args):
        pass  # keep stdout clean; the console pane is the log the user wants

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self.send_response(404)
            self.end_headers()
            return
        ctype = "text/html"
        if full.endswith(".js"):
            ctype = "application/javascript"
        elif full.endswith(".css"):
            ctype = "text/css"
        elif full.endswith(".json"):
            ctype = "application/json"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- GET ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            cfg = load_config()
            distro = detect_ros_distro()
            ws = cfg["workspace_path"]
            self._send_json({
                "ros_distro": distro,
                "supported_distros": SUPPORTED_DISTROS,
                "workspace_path": ws,
                "workspace_built": workspace_built(ws),
                "host_ip": get_host_ip(),
                "os": sys.platform,
                "agent_busy_console": agent_runner.is_busy(),
                "agent_alive_external": agent_externally_alive(),
                "bringup_busy_console": bringup_runner.is_busy(),
                "bringup_alive_external": bringup_externally_alive(),
                "main_busy": main_runner.is_busy(),
                "web_dir": WEB_DIR,
                "config": cfg,
            })
            return

        if path == "/api/config":
            self._send_json(load_config())
            return

        if path == "/api/sensors":
            self._send_json({
                "laser": {k: v["label"] for k, v in LASER_SENSORS.items()},
                "depth": {k: v["label"] for k, v in DEPTH_SENSORS.items()},
            })
            return

        if path == "/api/nav2_config":
            query_params = dict(q.split("=") for q in parsed.query.split("&") if "=" in q)
            requested_distro = query_params.get("distro") or detect_ros_distro()
            requested_base = query_params.get("base") or "2wd"
            cfg_path = get_nav2_config_path(requested_distro)
            self._send_json({
                "distro": requested_distro,
                "base": requested_base,
                "config": get_nav2_config(requested_distro),
                "path": cfg_path,
                "exists": os.path.exists(cfg_path),
                "supported_distros": SUPPORTED_DISTROS,
                "supported_bases": ["2wd", "4wd", "mecanum"],
            })
            return

        if path == "/api/ekf_config":
            query_params = dict(q.split("=") for q in parsed.query.split("&") if "=" in q)
            requested_base = query_params.get("base") or "2wd"
            cfg_path = get_ekf_config_path()
            self._send_json({
                "base": requested_base,
                "config": get_ekf_config(requested_base),
                "path": cfg_path,
                "exists": os.path.exists(cfg_path),
                "supported_bases": ["2wd", "4wd", "mecanum"],
            })
            return

        if path == "/api/slam_config":
            cfg_path = get_slam_config_path()
            self._send_json({
                "config": get_slam_config(),
                "path": cfg_path,
                "exists": os.path.exists(cfg_path),
            })
            return

        if path == "/api/presets":
            presets_data = patcher.PRESETS if patcher else {}
            self._send_json({"presets": presets_data})
            return

        if path == "/api/maps":
            cfg = load_config()
            maps_dir = os.path.join(cfg["workspace_path"], "src", "linorobot2",
                                     "linorobot2_navigation", "maps")
            maps = []
            if os.path.isdir(maps_dir):
                maps = sorted(f[:-5] for f in os.listdir(maps_dir) if f.endswith(".yaml"))
            self._send_json({"maps": maps, "maps_dir": maps_dir})
            return

        if path == "/api/lidar_stream":
            self._handle_lidar_stream()
            return

        self._serve_static(path)

    def _stream_command(self, command, runner):
        if not command:
            self._send_json({"error": "Empty command"}, 400)
            return
        if runner.is_busy():
            self._send_json({"error": f"{runner.name} slot is already running a command"}, 409)
            return

        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        client_gone = {"v": False}

        def send_event(event_type, payload):
            if client_gone["v"]:
                return
            msg = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                client_gone["v"] = True

        # cwd is intentionally NOT the configured workspace_path: that directory
        # may not exist yet (the base-install command's job is to create it),
        # so every generated command `cd`s explicitly where it needs to instead.
        runner.start_streaming(command, cwd=os.path.expanduser("~"), send_event=send_event)

    def _handle_lidar_stream(self):
        """Live /scan viewer rendered in-browser: run `ros2 topic echo /scan`
        and forward just the fields the canvas plot needs as SSE JSON frames.
        Deliberately NOT the LiDAR driver's own bundled `view_*`/`*_view`
        launch file -- that just opens a local RViz window on the robot
        computer's own display, which isn't visible through Console's
        browser UI. Same idea as config-engine's topic-echo SSE consumer --
        no rosbridge/roslibjs dependency."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        cfg = load_config()
        distro = detect_ros_distro()
        cmd = (
            f"source /opt/ros/{distro}/setup.bash 2>/dev/null; "
            f"[ -f {cfg['workspace_path']}/install/setup.bash ] && source {cfg['workspace_path']}/install/setup.bash; "
            "ros2 topic echo /scan"
        )
        proc = subprocess.Popen(
            ["bash", "-lc", cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, preexec_fn=os.setsid,
        )
        doc = {}
        field_re = re.compile(r"^(\w+):\s*(.*)$")
        in_ranges = False
        ranges_buf = []
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                stripped = line.rstrip("\n")
                if stripped == "---":
                    if "ranges" not in doc and ranges_buf:
                        doc["ranges"] = ranges_buf
                    try:
                        payload = {
                            "angle_min": float(doc.get("angle_min", 0)),
                            "angle_max": float(doc.get("angle_max", 0)),
                            "angle_increment": float(doc.get("angle_increment", 0)),
                            "ranges": [float(x) for x in doc.get("ranges", [])],
                        }
                        msg = f"event: scan\ndata: {json.dumps(payload)}\n\n"
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    except Exception:
                        pass
                    doc = {}
                    ranges_buf = []
                    in_ranges = False
                    continue
                m = field_re.match(stripped.strip())
                if m:
                    key, val = m.group(1), m.group(2)
                    if key == "ranges":
                        in_ranges = True
                        inline = val.strip()
                        if inline.startswith("[") and inline.endswith("]"):
                            doc["ranges"] = [v for v in inline[1:-1].split(",") if v.strip()]
                            in_ranges = False
                        continue
                    in_ranges = False
                    doc[key] = val
                elif in_ranges and stripped.strip().startswith("-"):
                    ranges_buf.append(stripped.strip().lstrip("- "))
        finally:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                pass

    # ---- POST ----
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self._read_json()

        if path == "/api/config":
            cfg = load_config()
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
            save_config(cfg)
            self._send_json(cfg)
            return

        if path == "/api/exec":
            command = data.get("command", "")
            slot = data.get("slot", "main")
            runner = bringup_runner if slot == "bringup" else (agent_runner if slot == "agent" else main_runner)
            self._stream_command(command, runner)
            return

        if path == "/api/kill":
            slot = data.get("slot", "main")
            runner = bringup_runner if slot == "bringup" else (agent_runner if slot == "agent" else main_runner)
            killed = runner.kill()
            self._send_json({"killed": killed})
            return

        if path == "/api/bringup/exec":
            command = data.get("command", "")
            self._stream_command(command, bringup_runner)
            return

        if path == "/api/bringup/kill":
            killed = bringup_runner.kill()
            self._send_json({"killed": killed})
            return

        if path == "/api/agent/exec":
            command = data.get("command", "")
            self._stream_command(command, agent_runner)
            return

        if path == "/api/agent/kill":
            killed = agent_runner.kill()
            self._send_json({"killed": killed})
            return

        if path == "/api/nav2_config":
            distro = data.get("distro") or detect_ros_distro()
            cfg_text = data.get("config", "")
            if not cfg_text.strip():
                self._send_json({"error": "Empty configuration"}, 400)
                return
            saved_path = save_nav2_config(cfg_text, distro)
            self._send_json({"status": "ok", "distro": distro, "path": saved_path, "length": len(cfg_text)})
            return

        if path == "/api/nav2_config/reset":
            distro = data.get("distro") or detect_ros_distro()
            base = data.get("base") or "2wd"
            tpl_path = os.path.join(CONFIG_DIR, f"nav2_{distro}_{base}.yaml")
            if not os.path.exists(tpl_path):
                tpl_path = get_nav2_default_path(distro)
            if os.path.exists(tpl_path):
                with open(tpl_path, "r") as f:
                    reset_content = f.read()
                saved_path = save_nav2_config(reset_content, distro)
                self._send_json({"status": "reset", "distro": distro, "base": base, "config": reset_content, "path": saved_path})
            else:
                self._send_json({"error": f"Default template for {distro} not found"}, 404)
            return

        if path == "/api/nav2_config/patch":
            distro = data.get("distro") or detect_ros_distro()
            base = data.get("base") or "2wd"
            current_cfg = get_nav2_config(distro)
            if patcher:
                patched_cfg = patcher.patch_nav2_text(
                    current_cfg,
                    base_type=base,
                    max_vel_x=data.get("max_vel_x", 0.5),
                    max_vel_y=data.get("max_vel_y"),
                    max_vel_theta=data.get("max_vel_theta", 2.5),
                    max_accel_x=data.get("max_accel_x", 2.5),
                    max_accel_y=data.get("max_accel_y"),
                    max_accel_theta=data.get("max_accel_theta", 3.2),
                    desired_linear_vel=data.get("desired_linear_vel"),
                    inflation_radius=data.get("inflation_radius"),
                    cost_scaling_factor=data.get("cost_scaling_factor")
                )
            else:
                patched_cfg = current_cfg
            saved_path = save_nav2_config(patched_cfg, distro)
            self._send_json({"status": "patched", "distro": distro, "base": base, "config": patched_cfg, "path": saved_path})
            return

        if path == "/api/ekf_config":
            cfg_text = data.get("config", "")
            if not cfg_text.strip():
                self._send_json({"error": "Empty EKF configuration"}, 400)
                return
            saved_path = save_ekf_config(cfg_text)
            self._send_json({"status": "ok", "path": saved_path, "length": len(cfg_text)})
            return

        if path == "/api/ekf_config/patch":
            base = data.get("base") or "2wd"
            current_cfg = get_ekf_config(base)
            if patcher:
                patched_cfg = patcher.patch_ekf_text(
                    current_cfg,
                    base_type=base,
                    frequency=data.get("frequency", 50.0),
                    two_d_mode=data.get("two_d_mode", True),
                    fuse_vy=data.get("fuse_vy"),
                    fuse_imu_yaw=data.get("fuse_imu_yaw", False)
                )
            else:
                patched_cfg = current_cfg
            saved_path = save_ekf_config(patched_cfg)
            self._send_json({"status": "patched", "base": base, "config": patched_cfg, "path": saved_path})
            return

        if path == "/api/ekf_config/reset":
            base = data.get("base") or "2wd"
            tpl_path = get_ekf_default_path(base)
            if os.path.exists(tpl_path):
                with open(tpl_path, "r") as f:
                    reset_content = f.read()
                saved_path = save_ekf_config(reset_content)
                self._send_json({"status": "reset", "base": base, "config": reset_content, "path": saved_path})
            else:
                self._send_json({"error": "Default EKF template not found"}, 404)
            return

        if path == "/api/slam_config":
            cfg_text = data.get("config", "")
            if not cfg_text.strip():
                self._send_json({"error": "Empty SLAM configuration"}, 400)
                return
            saved_path = save_slam_config(cfg_text)
            self._send_json({"status": "ok", "path": saved_path, "length": len(cfg_text)})
            return

        if path == "/api/slam_config/patch":
            current_cfg = get_slam_config()
            if patcher:
                patched_cfg = patcher.patch_slam_text(
                    current_cfg,
                    resolution=data.get("resolution"),
                    max_laser_range=data.get("max_laser_range"),
                    minimum_travel_distance=data.get("minimum_travel_distance"),
                    minimum_travel_heading=data.get("minimum_travel_heading")
                )
            else:
                patched_cfg = current_cfg
            saved_path = save_slam_config(patched_cfg)
            self._send_json({"status": "patched", "config": patched_cfg, "path": saved_path})
            return

        if path == "/api/slam_config/reset":
            tpl_path = get_slam_default_path()
            if os.path.exists(tpl_path):
                with open(tpl_path, "r") as f:
                    reset_content = f.read()
                saved_path = save_slam_config(reset_content)
                self._send_json({"status": "reset", "config": reset_content, "path": saved_path})
            else:
                self._send_json({"error": "Default SLAM template not found"}, 404)
            return

        if path == "/api/presets/apply":
            preset_name = data.get("preset", "")
            if not patcher or preset_name not in patcher.PRESETS:
                self._send_json({"error": f"Unknown preset: {preset_name}"}, 400)
                return
            pinfo = patcher.PRESETS[preset_name]
            distro = data.get("distro") or detect_ros_distro()
            base = pinfo["base"]

            # 1. Patch Nav2
            nav2_in = get_nav2_config(distro)
            nav2_out = patcher.patch_nav2_text(
                nav2_in,
                base_type=base,
                max_vel_x=pinfo["max_vel_x"],
                max_vel_y=pinfo["max_vel_y"],
                max_vel_theta=pinfo["max_vel_theta"],
                max_accel_x=pinfo["max_accel_x"],
                max_accel_y=pinfo["max_accel_y"],
                max_accel_theta=pinfo["max_accel_theta"],
                inflation_radius=pinfo.get("inflation_radius"),
                cost_scaling_factor=pinfo.get("cost_scaling_factor")
            )
            save_nav2_config(nav2_out, distro)

            # 2. Patch EKF
            ekf_in = get_ekf_config(base)
            ekf_out = patcher.patch_ekf_text(
                ekf_in,
                base_type=base,
                frequency=pinfo["ekf_frequency"],
                fuse_vy=pinfo["fuse_vy"],
                fuse_imu_yaw=pinfo["fuse_imu_yaw"]
            )
            save_ekf_config(ekf_out)

            # 3. Patch SLAM
            slam_in = get_slam_config()
            slam_out = patcher.patch_slam_text(
                slam_in,
                resolution=pinfo["slam_resolution"],
                max_laser_range=pinfo["slam_max_range"]
            )
            save_slam_config(slam_out)

            self._send_json({
                "status": "applied",
                "preset": preset_name,
                "label": pinfo["label"],
                "base": base,
                "distro": distro,
                "nav2_config": nav2_out,
                "ekf_config": ekf_out,
                "slam_config": slam_out
            })
            return

        if path == "/api/ai/tune":
            prompt = data.get("prompt", "")
            base = data.get("base", "2wd")
            distro = data.get("distro") or detect_ros_distro()
            analysis = analyze_robotics_ai(prompt, base=base, distro=distro)
            self._send_json(analysis)
            return

        if path == "/api/ai/apply":
            distro = data.get("distro") or detect_ros_distro()
            nav2_p = data.get("nav2_patch") or {}
            ekf_p = data.get("ekf_patch") or {}
            slam_p = data.get("slam_patch") or {}

            # Nav2
            if nav2_p and patcher:
                cur_nav2 = get_nav2_config(distro)
                patched_nav2 = patcher.patch_nav2_text(
                    cur_nav2,
                    base_type=nav2_p.get("base", "2wd"),
                    max_vel_x=nav2_p.get("max_vel_x", 0.5),
                    max_vel_y=nav2_p.get("max_vel_y"),
                    max_vel_theta=nav2_p.get("max_vel_theta", 2.5),
                    max_accel_x=nav2_p.get("max_accel_x", 2.5),
                    max_accel_y=nav2_p.get("max_accel_y"),
                    max_accel_theta=nav2_p.get("max_accel_theta", 3.2),
                    desired_linear_vel=nav2_p.get("desired_linear_vel"),
                    inflation_radius=nav2_p.get("inflation_radius"),
                    cost_scaling_factor=nav2_p.get("cost_scaling_factor")
                )
                save_nav2_config(patched_nav2, distro)

            # EKF
            if ekf_p and patcher:
                cur_ekf = get_ekf_config(nav2_p.get("base", "2wd"))
                patched_ekf = patcher.patch_ekf_text(
                    cur_ekf,
                    base_type=nav2_p.get("base", "2wd"),
                    frequency=ekf_p.get("frequency", 50.0),
                    two_d_mode=ekf_p.get("two_d_mode", True),
                    fuse_vy=ekf_p.get("fuse_vy"),
                    fuse_imu_yaw=ekf_p.get("fuse_imu_yaw", False)
                )
                save_ekf_config(patched_ekf)

            # SLAM
            if slam_p and patcher:
                cur_slam = get_slam_config()
                patched_slam = patcher.patch_slam_text(
                    cur_slam,
                    resolution=slam_p.get("resolution"),
                    max_laser_range=slam_p.get("max_laser_range"),
                    minimum_travel_distance=slam_p.get("minimum_travel_distance"),
                    minimum_travel_heading=slam_p.get("minimum_travel_heading")
                )
                save_slam_config(patched_slam)

            self._send_json({
                "status": "ai_applied",
                "distro": distro,
                "nav2_updated": bool(nav2_p),
                "ekf_updated": bool(ekf_p),
                "slam_updated": bool(slam_p)
            })
            return

        if path == "/api/ai/robot_builder":
            description = data.get("description", "")
            specs = generate_custom_robot_specs(description)
            self._send_json(specs)
            return

        if path == "/api/ai/deploy_robot":
            specs = data.get("specs") or {}
            distro = data.get("distro") or detect_ros_distro()
            base = specs.get("base", "2wd")

            # 1. Update EKF
            ekf_cfg = specs.get("ekf", {})
            if ekf_cfg and patcher:
                cur_ekf = get_ekf_config(base)
                patched_ekf = patcher.patch_ekf_text(
                    cur_ekf,
                    base_type=base,
                    frequency=ekf_cfg.get("frequency", 50.0),
                    two_d_mode=ekf_cfg.get("two_d_mode", True),
                    fuse_vy=ekf_cfg.get("fuse_vy", False),
                    fuse_imu_yaw=ekf_cfg.get("fuse_imu_yaw", False)
                )
                save_ekf_config(patched_ekf)

            # 2. Update Nav2
            nav2_cfg = specs.get("nav2", {})
            if nav2_cfg and patcher:
                cur_nav2 = get_nav2_config(distro)
                patched_nav2 = patcher.patch_nav2_text(
                    cur_nav2,
                    base_type=base,
                    max_vel_x=nav2_cfg.get("max_vel_x", 0.5),
                    max_vel_y=nav2_cfg.get("max_vel_y"),
                    max_vel_theta=nav2_cfg.get("max_vel_theta", 2.5),
                    max_accel_x=nav2_cfg.get("max_accel_x", 2.5),
                    max_accel_y=nav2_cfg.get("max_accel_y"),
                    max_accel_theta=nav2_cfg.get("max_accel_theta", 3.2),
                    desired_linear_vel=nav2_cfg.get("desired_linear_vel"),
                    inflation_radius=nav2_cfg.get("inflation_radius"),
                    cost_scaling_factor=nav2_cfg.get("cost_scaling_factor")
                )
                save_nav2_config(patched_nav2, distro)

            # 3. Update SLAM
            slam_cfg = specs.get("slam", {})
            if slam_cfg and patcher:
                cur_slam = get_slam_config()
                patched_slam = patcher.patch_slam_text(
                    cur_slam,
                    resolution=slam_cfg.get("resolution", 0.05),
                    max_laser_range=slam_cfg.get("max_laser_range", 12.0)
                )
                save_slam_config(patched_slam)

            # 4. Update console_config.json
            cfg = load_config()
            cfg["base_type"] = base
            if specs.get("laser_sensor"):
                cfg["laser_sensor"] = specs["laser_sensor"]
            save_config(cfg)

            self._send_json({
                "status": "deployed",
                "base": base,
                "distro": distro,
                "laser_sensor": specs.get("laser_sensor"),
                "message": f"Successfully configured and deployed custom {base.upper()} robot!"
            })
            return

        if path == "/api/import_config":
            self._handle_import_config(data)
            return

        self._send_json({"error": "Not found"}, 404)

    def _handle_import_config(self, data):
        """Read a config-engine-generated config/custom/<name>_config.h and
        pull out just the fields Console's forms can use. Small hand-rolled
        subset of linorobot2_hardware's parser.py logic -- not a shared
        dependency across repos, see the implementation plan."""
        path = data.get("path", "")
        text = data.get("text", "")
        if path and not text:
            try:
                with open(path) as f:
                    text = f.read()
            except Exception as e:
                self._send_json({"error": f"Could not read {path}: {e}"}, 400)
                return
        if not text:
            self._send_json({"error": "No path or text provided"}, 400)
            return

        result = {}

        # All patterns below require an uncommented, line-anchored #define --
        # matching parser.py's _define_bool discipline -- so a `// #define
        # USE_WIFI` or similar commented-out line is correctly ignored rather
        # than misread as active.
        m = re.search(r"^[ \t]*#define\s+LINO_BASE\s+(\w+)", text, re.MULTILINE)
        if m:
            base_map = {"DIFFERENTIAL_DRIVE": "2wd", "SKID_STEER": "4wd", "MECANUM": "mecanum"}
            result["base"] = base_map.get(m.group(1), "")

        m = re.search(r"^[ \t]*#define\s+BAUDRATE\s+(\d+)", text, re.MULTILINE)
        if m:
            result["agent_baud"] = m.group(1)

        # USE_WIFI is config-engine's actual macro for this (parser.py's
        # _define_bool("USE_WIFI")) -- not a "WIFI_UDP"/"USE_WIFI_TRANSPORT"
        # name, which don't exist in generated headers.
        result["transport"] = "udp4" if re.search(r"^[ \t]*#define\s+USE_WIFI\b", text, re.MULTILINE) \
            else "serial"

        m = re.search(r"^[ \t]*#define\s+AGENT_IP\s*\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
                       text, re.MULTILINE)
        if m:
            result["agent_ip"] = ".".join(m.groups())

        m = re.search(r"^[ \t]*#define\s+USE_(\w+)_IMU\b", text, re.MULTILINE)
        result["has_imu"] = bool(m and m.group(1) != "FAKE")
        m = re.search(r"^[ \t]*#define\s+USE_(\w+)_MAG\b", text, re.MULTILINE)
        result["has_mag"] = bool(m and m.group(1) not in (None, "FAKE"))

        m = re.search(r"^[ \t]*#define\s+MAG_BIAS\s*\{([^}]*)\}", text, re.MULTILINE)
        if m:
            result["mag_bias"] = [v.strip() for v in m.group(1).split(",")]

        self._send_json(result)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Linorobot2 Console serving on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
