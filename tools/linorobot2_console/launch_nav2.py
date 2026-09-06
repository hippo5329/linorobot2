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
import tempfile
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.conditions import IfCondition
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node


def resolve_nav2_and_slam(context, *args, **kwargs):
    distro = context.launch_configurations.get('distro', os.environ.get('ROS_DISTRO', 'jazzy')).strip().lower()
    base = context.launch_configurations.get('base', os.environ.get('LINOROBOT2_BASE', '2wd')).strip().lower()
    is_slam = context.launch_configurations.get('slam', 'false').strip().lower() in ['true', '1', 'yes']
    passed_params = context.launch_configurations.get('params_file', '').strip()
    passed_slam_params = context.launch_configurations.get('slam_params_file', '').strip()

    console_dir = os.path.dirname(os.path.abspath(__file__))

    # Resolve Nav2 params:
    if passed_params and os.path.exists(passed_params):
        selected_params = passed_params
    else:
        distro_active = os.path.join(console_dir, 'web', f'console_nav2_{distro}.yaml')
        base_tpl = os.path.join(console_dir, 'config', f'nav2_{distro}_{base}.yaml')
        distro_tpl = os.path.join(console_dir, 'config', f'nav2_{distro}.yaml')
        if os.path.exists(distro_active):
            selected_params = distro_active
        elif os.path.exists(base_tpl):
            selected_params = base_tpl
        elif os.path.exists(distro_tpl):
            selected_params = distro_tpl
        else:
            selected_params = os.path.join(console_dir, 'web', 'console_nav2_params.yaml')

    # Depth camera -> costmap gating (Console-side; upstream navigation.launch.py
    # is left untouched -- we resolve it here and hand it a finished params
    # file). The shipped configs list `observation_sources: scan pointcloud`;
    # when there is no depth camera we pass a copy with `pointcloud` dropped
    # (its inert `pointcloud:` block stays). 'auto' = on iff
    # LINOROBOT2_DEPTH_SENSOR is set (the same env var linorobot2_bringup uses).
    # Same transform as tools/linorobot2_console/patcher.py:patch_costmap_sources.
    depth_arg = context.launch_configurations.get('depth_costmap', 'auto').strip().lower()
    if depth_arg in ('', 'auto'):
        depth_enabled = bool(os.environ.get('LINOROBOT2_DEPTH_SENSOR', '').strip())
    else:
        depth_enabled = depth_arg in ('true', '1', 'yes', 'on')

    depth_note = "on"
    if not depth_enabled:
        depth_note = "off"
        try:
            with open(selected_params) as f:
                original = f.read()
            gated = re.sub(
                r'(?m)^([ \t]*observation_sources:[ \t]*)scan[ \t]+pointcloud[ \t]*$',
                r'\1scan', original)
            if gated != original:
                tmp = tempfile.NamedTemporaryFile(
                    mode='w', prefix='console_nav2_gated_', suffix='.yaml', delete=False)
                tmp.write(gated)
                tmp.close()
                selected_params = tmp.name
                depth_note = "off (generated %s)" % os.path.basename(tmp.name)
        except OSError:
            pass

    # Resolve SLAM params:
    if passed_slam_params and os.path.exists(passed_slam_params):
        selected_slam_params = passed_slam_params
    else:
        slam_active = os.path.join(console_dir, 'web', 'console_slam.yaml')
        slam_tpl = os.path.join(console_dir, 'config', 'slam.yaml')
        if os.path.exists(slam_active):
            selected_slam_params = slam_active
        elif os.path.exists(slam_tpl):
            selected_slam_params = slam_tpl
        else:
            selected_slam_params = ''

    nav_launch_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'launch', 'navigation.launch.py']
    )

    mode_str = "SLAM Mapping" if is_slam else "AMCL Navigation"
    return [
        LogInfo(msg=f"[Linorobot2 Console] Launching {mode_str} (distro: '{distro}', base: '{base}') "
                    f"with Nav2: '{selected_params}' | depth->costmap: {depth_note}"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav_launch_path),
            launch_arguments={
                'slam': 'true' if is_slam else 'false',
                'distro': distro,
                'base': base,
                'params_file': selected_params,
                'slam_params_file': selected_slam_params,
                'map': LaunchConfiguration('map'),
                'sim': LaunchConfiguration('sim'),
                'rviz': LaunchConfiguration('rviz'),
                'autostart': LaunchConfiguration('autostart'),
                'initial_pose_x': LaunchConfiguration('initial_pose_x'),
                'initial_pose_y': LaunchConfiguration('initial_pose_y'),
                'initial_pose_yaw': LaunchConfiguration('initial_pose_yaw')
            }.items()
        )
    ]


def generate_launch_description():
    default_map_path = PathJoinSubstitution(
        [FindPackageShare('linorobot2_navigation'), 'maps', 'turtlebot3_world.yaml']
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            name='slam',
            default_value='false',
            description='Run SLAM mapping (true) or AMCL navigation (false)'
        ),
        DeclareLaunchArgument(
            name='distro',
            default_value=os.environ.get('ROS_DISTRO', 'jazzy'),
            description='ROS 2 distribution (jazzy, lyrical, rolling)'
        ),
        DeclareLaunchArgument(
            name='base',
            default_value=os.environ.get('LINOROBOT2_BASE', '2wd'),
            description='Robot base kinematics (2wd, 4wd, mecanum)'
        ),
        DeclareLaunchArgument(
            name='params_file',
            default_value='',
            description='Path to ROS 2 parameters file (blank = auto-resolve)'
        ),
        DeclareLaunchArgument(
            name='slam_params_file',
            default_value='',
            description='Path to SLAM parameters file (blank = auto-resolve)'
        ),
        DeclareLaunchArgument(
            name='depth_costmap',
            default_value='auto',
            description="Depth-camera pointcloud into costmap: 'auto' | 'true' | 'false'"
        ),
        DeclareLaunchArgument(
            name='map',
            default_value=default_map_path,
            description='Navigation map path (.yaml)'
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
            name='autostart',
            default_value='true',
            description='Automatically startup nav2 stack'
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

        OpaqueFunction(function=resolve_nav2_and_slam)
    ])


if __name__ == '__main__':
    import subprocess
    args = sys.argv[1:]
    cmd = ["ros2", "launch", __file__] + args
    print(f"[Linorobot2 Console] Executing: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)
