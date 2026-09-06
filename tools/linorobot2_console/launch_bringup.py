#!/usr/bin/env python3
# Copyright (c) 2026 Linorobot contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import sys

try:
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
    from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch_ros.substitutions import FindPackageShare
except ImportError:
    LaunchDescription = None

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/linorobot2/robot_config.yaml")

def _load_robot_config_yaml(custom_path=None):
    cfg_file = custom_path or os.environ.get("ROBOT_CONFIG_FILE") or DEFAULT_CONFIG_PATH
    if not os.path.isfile(cfg_file):
        return {}
    params = {}
    try:
        with open(cfg_file, "r") as f:
            in_lino = False
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if line.startswith("linorobot2:"):
                    in_lino = True
                    continue
                elif in_lino and re.match(r"^[A-Za-z0-9_]+:\s*", line):
                    in_lino = False
                if in_lino:
                    m = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*?)(?:\s+#.*)?$", line)
                    if m:
                        k, v = m.group(1), m.group(2).strip().strip("\x27\x22")
                        params[k] = v
    except Exception:
        pass

    if "base" in params:
        os.environ["LINOROBOT2_BASE"] = params["base"]
    if "laser_sensor" in params:
        os.environ["LINOROBOT2_LASER_SENSOR"] = params["laser_sensor"]
    if "depth_sensor" in params:
        os.environ["LINOROBOT2_DEPTH_SENSOR"] = params["depth_sensor"]
    if "micro_ros_port" in params:
        os.environ["BASE_SERIAL_PORT"] = params["micro_ros_port"]
        os.environ["MICRO_ROS_PORT"] = params["micro_ros_port"]
    if "micro_ros_baudrate" in params:
        os.environ["MICRO_ROS_BAUDRATE"] = str(params["micro_ros_baudrate"])
    if "micro_ros_transport" in params:
        os.environ["MICRO_ROS_TRANSPORT"] = params["micro_ros_transport"]
    if "madgwick" in params:
        os.environ["MADGWICK"] = "true" if params["madgwick"].lower() in ("true", "1") else "false"

    return params

def generate_launch_description():
    if LaunchDescription is None:
        raise RuntimeError("ROS 2 launch package not found in current environment")

    bringup_launch_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_bringup'), 'launch', 'bringup.launch.py']
    )

    cfg = _load_robot_config_yaml()
    def_base = cfg.get('base', os.environ.get('LINOROBOT2_BASE', '2wd'))
    def_port = cfg.get('micro_ros_port', os.environ.get('BASE_SERIAL_PORT', '/dev/ttyACM0'))
    def_baud = str(cfg.get('micro_ros_baudrate', os.environ.get('MICRO_ROS_BAUDRATE', '1500000')))
    def_transport = cfg.get('micro_ros_transport', os.environ.get('MICRO_ROS_TRANSPORT', 'serial'))
    def_madgwick = "true" if cfg.get('madgwick', True) in (True, 'true', 'True', '1') else "false"

    return LaunchDescription([
        DeclareLaunchArgument(
            name='config_file',
            default_value=DEFAULT_CONFIG_PATH,
            description='Path to robot_config.yaml (defines kinematics, sensors, micro-ros params)'
        ),
        DeclareLaunchArgument(
            name='base',
            default_value=def_base,
            description='Robot base kinematics (2wd, 4wd, mecanum)'
        ),
        DeclareLaunchArgument(
            name='base_serial_port',
            default_value=def_port,
            description='Microcontroller serial port device'
        ),
        DeclareLaunchArgument(
            name='micro_ros_baudrate',
            default_value=def_baud,
            description='micro-ROS agent serial baudrate'
        ),
        DeclareLaunchArgument(
            name='micro_ros_transport',
            default_value=def_transport,
            description='micro-ROS agent transport (serial or udp4)'
        ),
        DeclareLaunchArgument(
            name='micro_ros_port',
            default_value=def_port,
            description='micro-ROS agent UDP port or serial port'
        ),
        DeclareLaunchArgument(
            name='madgwick',
            default_value=def_madgwick,
            description='Use madgwick to fuse imu and magnetometer'
        ),

        LogInfo(msg=['[Linorobot2 Console] Launching robot bringup from robot_config.yaml on port ', LaunchConfiguration('base_serial_port')]),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(bringup_launch_path),
            launch_arguments={
                'base': LaunchConfiguration('base'),
                'base_serial_port': LaunchConfiguration('base_serial_port'),
                'micro_ros_baudrate': LaunchConfiguration('micro_ros_baudrate'),
                'micro_ros_transport': LaunchConfiguration('micro_ros_transport'),
                'micro_ros_port': LaunchConfiguration('micro_ros_port'),
                'madgwick': LaunchConfiguration('madgwick')
            }.items()
        )
    ])

if __name__ == '__main__':
    import subprocess
    args = sys.argv[1:]
    cmd = ["ros2", "launch", __file__] + args
    print(f"[Linorobot2 Console] Executing: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)
