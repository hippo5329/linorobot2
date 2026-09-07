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
try:
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
    from launch.substitutions import LaunchConfiguration
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.conditions import IfCondition
    from launch_ros.substitutions import FindPackageShare
    from launch_ros.actions import Node
except ImportError:
    LaunchDescription = None


def _default_config_path():
    """Active robot's repo config: <linorobot2>/config/<name>_config.yaml.
    Falls back to the legacy ~/.config/linorobot2/robot_config.yaml."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg_dir = os.path.join(repo_root, "config")
    name = "linorobot2"
    try:
        with open(os.path.join(cfg_dir, ".active_robot")) as f:
            cand = f.read().strip()
        if re.match(r"^[a-z0-9_]+$", cand):
            name = cand
    except OSError:
        pass
    repo_cfg = os.path.join(cfg_dir, name + "_config.yaml")
    if os.path.isfile(repo_cfg):
        return repo_cfg
    legacy = os.path.expanduser("~/.config/linorobot2/robot_config.yaml")
    return legacy if os.path.isfile(legacy) else repo_cfg


DEFAULT_CONFIG_PATH = _default_config_path()

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
                        k, v = m.group(1), m.group(2).strip().strip("'\"")
                        params[k] = v
    except Exception:
        pass

    if "base" in params:
        os.environ["LINOROBOT2_BASE"] = params["base"]
    if "laser_sensor" in params:
        os.environ["LINOROBOT2_LASER_SENSOR"] = params["laser_sensor"]
    if "depth_sensor" in params:
        os.environ["LINOROBOT2_DEPTH_SENSOR"] = params["depth_sensor"]
    return params

_load_robot_config_yaml()

def resolve_nav2_and_slam(context, *args, **kwargs):
    cfg_file = context.launch_configurations.get('config_file', DEFAULT_CONFIG_PATH).strip()
    lino_cfg = _load_robot_config_yaml(cfg_file)
    distro = context.launch_configurations.get('distro', os.environ.get('ROS_DISTRO', 'jazzy')).strip().lower()
    base = context.launch_configurations.get('base', lino_cfg.get('base', os.environ.get('LINOROBOT2_BASE', '2wd'))).strip().lower()
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

    # Depth camera -> costmap gating (Console-side). The console's config
    # templates list `observation_sources: scan pointcloud`; when there is no
    # depth camera we pass a copy with `pointcloud` dropped (its inert
    # `pointcloud:` block stays). 'auto' = on iff LINOROBOT2_DEPTH_SENSOR is
    # set (the same env var linorobot2_bringup uses). Same transform as
    # tools/linorobot2_console/patcher.py:patch_costmap_sources.
    depth_arg = context.launch_configurations.get('depth_costmap', 'auto').strip().lower()
    if depth_arg in ('', 'auto'):
        depth_enabled = bool(lino_cfg.get('depth_sensor') or os.environ.get('LINOROBOT2_DEPTH_SENSOR', '').strip())
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

    # SLAM mode: nav2_bringup/bringup_launch.py feeds one `params_file` to BOTH
    # slam_toolbox and the nav2 stack, so concatenate the two console param
    # docs (disjoint top-level mappings -- `slam_toolbox:` vs `amcl:` / ... --
    # so plain text concat is valid YAML).
    bringup_params = selected_params
    if is_slam and selected_slam_params and os.path.exists(selected_slam_params):
        try:
            with open(selected_params) as f:
                nav_txt = f.read()
            with open(selected_slam_params) as f:
                slam_txt = f.read()
            tmp = tempfile.NamedTemporaryFile(
                mode='w', prefix='console_slamnav_', suffix='.yaml', delete=False)
            tmp.write(nav_txt.rstrip() + "\n\n" + slam_txt)
            tmp.close()
            bringup_params = tmp.name
        except OSError:
            pass

    # Self-contained: pull in nav2_bringup's own bringup_launch.py (a stock
    # ROS 2 package) directly + an RViz node -- no include of the
    # linorobot2_navigation package launch file.
    nav2_bringup_launch = os.path.join(
        FindPackageShare('nav2_bringup').find('nav2_bringup'), 'launch', 'bringup_launch.py')

    rviz_args = []
    try:
        nav_pkg = FindPackageShare('linorobot2_navigation').find('linorobot2_navigation')
        rviz_cfg = os.path.join(
            nav_pkg, 'rviz',
            'linorobot2_slam.rviz' if is_slam else 'linorobot2_navigation.rviz')
        if os.path.exists(rviz_cfg):
            rviz_args = ['-d', rviz_cfg]
    except Exception:
        pass

    mode_str = "SLAM Mapping" if is_slam else "AMCL Navigation"
    return [
        LogInfo(msg=f"[Linorobot2 Console] Launching {mode_str} (distro: '{distro}', base: '{base}') "
                    f"via nav2_bringup | params: '{bringup_params}' | depth->costmap: {depth_note}"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav2_bringup_launch),
            launch_arguments={
                'slam': 'True' if is_slam else 'False',
                'map': '' if is_slam else LaunchConfiguration('map'),
                'use_sim_time': LaunchConfiguration('sim'),
                'params_file': bringup_params,
                'autostart': LaunchConfiguration('autostart'),
            }.items()
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=rviz_args,
            condition=IfCondition(LaunchConfiguration('rviz')),
            parameters=[{'use_sim_time': LaunchConfiguration('sim')}],
        ),
    ]


def generate_launch_description():
    try:
        default_map_path = os.path.join(
            FindPackageShare('linorobot2_navigation').find('linorobot2_navigation'),
            'maps', 'turtlebot3_world.yaml')
    except Exception:
        default_map_path = ''

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
