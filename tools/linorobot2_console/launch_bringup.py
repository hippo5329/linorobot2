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
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    bringup_launch_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_bringup'), 'launch', 'bringup.launch.py']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='base_serial_port',
            default_value='/dev/ttyACM0',
            description='Microcontroller serial port device'
        ),
        DeclareLaunchArgument(
            name='micro_ros_transport',
            default_value='serial',
            description='micro-ROS agent transport (serial or udp4)'
        ),
        DeclareLaunchArgument(
            name='micro_ros_port',
            default_value='8888',
            description='micro-ROS agent UDP port'
        ),

        LogInfo(msg=['[Linorobot2 Console] Launching robot bringup on ', LaunchConfiguration('base_serial_port')]),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(bringup_launch_path),
            launch_arguments={
                'base_serial_port': LaunchConfiguration('base_serial_port'),
                'micro_ros_transport': LaunchConfiguration('micro_ros_transport'),
                'micro_ros_port': LaunchConfiguration('micro_ros_port')
            }.items()
        )
    ])

if __name__ == '__main__':
    import subprocess
    args = sys.argv[1:]
    cmd = ["ros2", "launch", __file__] + args
    print(f"[Linorobot2 Console] Executing: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)
