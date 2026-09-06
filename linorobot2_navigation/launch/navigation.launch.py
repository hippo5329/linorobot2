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

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node

MAP_NAME = 'turtlebot3_world'


def resolve_nav2_bringup(context, *args, **kwargs):
    distro = context.launch_configurations.get('distro', os.environ.get('ROS_DISTRO', 'jazzy')).strip().lower()
    base = context.launch_configurations.get('base', os.environ.get('LINOROBOT2_BASE', '2wd')).strip().lower()
    is_slam = context.launch_configurations.get('slam', 'false').strip().lower() in ['true', '1', 'yes']
    custom_params = context.launch_configurations.get('params_file', '').strip()
    custom_slam_params = context.launch_configurations.get('slam_params_file', '').strip()

    pkg_share = FindPackageShare('linorobot2_navigation').find('linorobot2_navigation')

    # Resolve Nav2 params
    if custom_params and os.path.exists(custom_params):
        selected_params = custom_params
    else:
        mecanum_cfg = os.path.join(pkg_share, 'config', f'navigation_{distro}_mecanum.yaml')
        distro_cfg = os.path.join(pkg_share, 'config', f'navigation_{distro}.yaml')
        default_cfg = os.path.join(pkg_share, 'config', 'navigation.yaml')
        if base == 'mecanum' and os.path.exists(mecanum_cfg):
            selected_params = mecanum_cfg
        elif os.path.exists(distro_cfg):
            selected_params = distro_cfg
        else:
            selected_params = default_cfg

    # Resolve SLAM params
    if custom_slam_params and os.path.exists(custom_slam_params):
        selected_slam_params = custom_slam_params
    else:
        selected_slam_params = os.path.join(pkg_share, 'config', 'slam.yaml')

    nav2_launch_path = PathJoinSubstitution(
        [FindPackageShare('nav2_bringup'), 'launch', 'bringup_launch.py']
    )

    mode_label = "SLAM Mapping" if is_slam else "AMCL Navigation"
    log_msg = f"[linorobot2_navigation] Mode: {mode_label} | Distro: '{distro}' | Base: '{base}' | Nav2: '{selected_params}'"
    if is_slam:
        log_msg += f" | SLAM: '{selected_slam_params}'"

    launch_args = {
        'slam': 'True' if is_slam else 'False',
        'use_sim_time': LaunchConfiguration('sim'),
        'params_file': selected_params,
        'autostart': LaunchConfiguration('autostart'),
        'initial_pose_x': LaunchConfiguration('initial_pose_x'),
        'initial_pose_y': LaunchConfiguration('initial_pose_y'),
        'initial_pose_yaw': LaunchConfiguration('initial_pose_yaw'),
    }

    if is_slam:
        launch_args['slam_params_file'] = selected_slam_params
    else:
        launch_args['map'] = LaunchConfiguration('map')

    rviz_file = 'linorobot2_slam.rviz' if is_slam else 'linorobot2_navigation.rviz'
    rviz_config_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'rviz', rviz_file]
    )

    return [
        LogInfo(msg=log_msg),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav2_launch_path),
            launch_arguments=launch_args.items()
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config_path],
            condition=IfCondition(LaunchConfiguration('rviz')),
            parameters=[{'use_sim_time': LaunchConfiguration('sim')}]
        )
    ]


def generate_launch_description():
    default_map_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'maps', f'{MAP_NAME}.yaml']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='slam',
            default_value='false',
            description='Run SLAM mapping (true) or AMCL localization (false)'
        ),
        DeclareLaunchArgument(
            name='distro',
            default_value=os.environ.get('ROS_DISTRO', 'jazzy'),
            description='ROS 2 distribution (jazzy, lyrical, rolling, humble)'
        ),
        DeclareLaunchArgument(
            name='base',
            default_value=os.environ.get('LINOROBOT2_BASE', '2wd'),
            description='Robot base kinematics (2wd, 4wd, mecanum)'
        ),
        DeclareLaunchArgument(
            name='params_file',
            default_value='',
            description='Path to Nav2 params file (blank = auto-resolve per distro/base)'
        ),
        DeclareLaunchArgument(
            name='slam_params_file',
            default_value='',
            description='Path to SLAM params file (blank = auto-resolve slam.yaml)'
        ),
        DeclareLaunchArgument(
            name='autostart',
            default_value='true',
            description='Automatically startup the nav2 stack'
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
            description='Navigation map path (ignored when slam:=true)'
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

        OpaqueFunction(function=resolve_nav2_bringup)
    ])
