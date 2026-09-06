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
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node

def resolve_nav2_params_file(context, *args, **kwargs):
    distro = context.launch_configurations.get('distro', os.environ.get('ROS_DISTRO', 'jazzy'))
    passed_params = context.launch_configurations.get('params_file', '').strip()
    console_dir = os.path.dirname(os.path.abspath(__file__))

    if passed_params and os.path.exists(passed_params):
        selected_params = passed_params
    else:
        # Check per-distro active config
        distro_active = os.path.join(console_dir, 'web', f'console_nav2_{distro}.yaml')
        distro_tpl = os.path.join(console_dir, 'config', f'nav2_{distro}.yaml')
        if os.path.exists(distro_active):
            selected_params = distro_active
        elif os.path.exists(distro_tpl):
            selected_params = distro_tpl
        else:
            selected_params = os.path.join(console_dir, 'web', 'console_nav2_params.yaml')

    nav2_launch_path = PathJoinSubstitution(
        [FindPackageShare('nav2_bringup'), 'launch', 'bringup_launch.py']
    )

    return [
        LogInfo(msg=f'[Linorobot2 Console] Launching Nav2 for distro {distro} with params: {selected_params}'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav2_launch_path),
            launch_arguments={
                'map': LaunchConfiguration('map'),
                'use_sim_time': LaunchConfiguration('sim'),
                'params_file': selected_params,
                'autostart': LaunchConfiguration('autostart'),
                'initial_pose_x': LaunchConfiguration('initial_pose_x'),
                'initial_pose_y': LaunchConfiguration('initial_pose_y'),
                'initial_pose_yaw': LaunchConfiguration('initial_pose_yaw')
            }.items()
        )
    ]

def generate_launch_description():
    rviz_config_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'rviz', 'linorobot2_navigation.rviz']
    )
    default_map_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'maps', 'turtlebot3_world.yaml']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='distro',
            default_value=os.environ.get('ROS_DISTRO', 'jazzy'),
            description='ROS 2 distribution (jazzy, lyrical, rolling, humble)'
        ),
        DeclareLaunchArgument(
            name='sim',
            default_value='false',
            description='Enable use_sim_time'
        ),
        DeclareLaunchArgument(
            name='rviz',
            default_value='false',
            description='Run RViz2'
        ),
        DeclareLaunchArgument(
            name='map',
            default_value=default_map_path,
            description='Navigation map path (.yaml)'
        ),
        DeclareLaunchArgument(
            name='params_file',
            default_value='',
            description='Path to ROS 2 parameters file (blank = auto-resolve per distro)'
        ),
        DeclareLaunchArgument(
            name='autostart',
            default_value='true',
            description='Automatically start Nav2 lifecycle nodes'
        ),
        DeclareLaunchArgument(
            name='initial_pose_x',
            default_value='0.0',
            description='Initial robot X position'
        ),
        DeclareLaunchArgument(
            name='initial_pose_y',
            default_value='0.0',
            description='Initial robot Y position'
        ),
        DeclareLaunchArgument(
            name='initial_pose_yaw',
            default_value='0.0',
            description='Initial robot yaw'
        ),

        OpaqueFunction(function=resolve_nav2_params_file),

        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config_path],
            condition=IfCondition(LaunchConfiguration('rviz')),
            parameters=[{'use_sim_time': LaunchConfiguration('sim')}]
        )
    ])

if __name__ == '__main__':
    import subprocess
    args = sys.argv[1:]
    cmd = ["ros2", "launch", __file__] + args
    print(f"[Linorobot2 Console] Executing: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)
