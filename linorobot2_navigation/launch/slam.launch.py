# Copyright (c) 2021 Juan Miguel Jimeno
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SLAM Launch File -- thin alias into unified navigation.launch.py with slam:=true."""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    nav_launch_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'launch', 'navigation.launch.py']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='distro',
            default_value=os.environ.get('ROS_DISTRO', 'jazzy'),
            description='ROS 2 distribution'
        ),
        DeclareLaunchArgument(
            name='base',
            default_value=os.environ.get('LINOROBOT2_BASE', '2wd'),
            description='Robot base kinematics'
        ),
        DeclareLaunchArgument(
            name='params_file',
            default_value='',
            description='Nav2 parameters file'
        ),
        DeclareLaunchArgument(
            name='slam_params_file',
            default_value='',
            description='SLAM Toolbox parameters file'
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
            name='initial_pose_x',
            default_value='0.5',
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

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav_launch_path),
            launch_arguments={
                'slam': 'true',
                'distro': LaunchConfiguration('distro'),
                'base': LaunchConfiguration('base'),
                'params_file': LaunchConfiguration('params_file'),
                'slam_params_file': LaunchConfiguration('slam_params_file'),
                'sim': LaunchConfiguration('sim'),
                'rviz': LaunchConfiguration('rviz'),
                'initial_pose_x': LaunchConfiguration('initial_pose_x'),
                'initial_pose_y': LaunchConfiguration('initial_pose_y'),
                'initial_pose_yaw': LaunchConfiguration('initial_pose_yaw')
            }.items()
        )
    ])
