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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

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
            cfg_path = get_nav2_config_path(requested_distro)
            self._send_json({
                "distro": requested_distro,
                "config": get_nav2_config(requested_distro),
                "path": cfg_path,
                "exists": os.path.exists(cfg_path),
                "supported_distros": SUPPORTED_DISTROS,
            })
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
            tpl_path = get_nav2_default_path(distro)
            if os.path.exists(tpl_path):
                with open(tpl_path, "r") as f:
                    reset_content = f.read()
                saved_path = save_nav2_config(reset_content, distro)
                self._send_json({"status": "reset", "distro": distro, "config": reset_content, "path": saved_path})
            else:
                self._send_json({"error": f"Default template for {distro} not found"}, 404)
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
