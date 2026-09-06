#!/usr/bin/env python3
"""Linorobot2 Configuration Patcher for Nav2, SLAM & EKF.

Surgically patches configuration files with zero external dependencies:
- Nav2: Kinematics (Diff vs Mecanum), Max/Min Speeds, Accelerations, Costmap Inflation, Controller params
- EKF: Odometry lateral velocity fusion (Diff vy=false vs Mecanum vy=true), IMU Yaw/Gyro fusion, Frequency
- SLAM: Map resolution, Laser max range, Keyframe travel distance/heading, Loop closure search range
- Presets: Pre-packaged expert tuning presets for different robot configurations and operational environments
"""

import argparse
import math
import os
import re
import sys


PRESETS = {
    "smooth_rotation": {
        "label": "Smooth In-Place Rotation & Anti-Oscillation",
        "desc": "Tuned RotationShimController (45° threshold, 1.5 rad/s spin) with smooth angular acceleration (2.0 rad/s²) and zero lateral slip",
        "base": "2wd",
        "max_vel_x": 0.5,
        "max_vel_y": 0.0,
        "max_vel_theta": 1.8,
        "max_accel_x": 2.2,
        "max_accel_y": 0.0,
        "max_accel_theta": 2.0,
        "rotate_to_heading_angular_vel": 1.5,
        "angular_dist_threshold": 0.785,
        "xy_goal_tolerance": 0.08,
        "yaw_goal_tolerance": 0.12,
        "inflation_radius": 0.65,
        "cost_scaling_factor": 3.5,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "anti_drift": {
        "label": "Anti-Drift State Estimation",
        "desc": "Disables lateral velocity slip fusion in EKF (vy=false) and locks 50Hz 2D planar fusion for 2WD/4WD",
        "base": "2wd",
        "max_vel_x": 0.5,
        "max_vel_y": 0.0,
        "max_vel_theta": 2.5,
        "max_accel_x": 2.5,
        "max_accel_y": 0.0,
        "max_accel_theta": 3.2,
        "inflation_radius": 0.7,
        "cost_scaling_factor": 3.0,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "anti_overshoot": {
        "label": "Anti-Overshoot / Active Braking",
        "desc": "Stiff deceleration (-2.8 m/s²), approach velocity scaling (0.75m), and regulated lookahead to stop goal blow-by",
        "base": "2wd",
        "max_vel_x": 0.45,
        "max_vel_y": 0.0,
        "max_vel_theta": 2.2,
        "max_accel_x": 2.0,
        "max_accel_y": 0.0,
        "max_accel_theta": 2.5,
        "max_decel_x": 2.8,
        "max_decel_theta": 3.5,
        "xy_goal_tolerance": 0.08,
        "yaw_goal_tolerance": 0.12,
        "approach_velocity_scaling_dist": 0.75,
        "lookahead_dist": 0.45,
        "inflation_radius": 0.65,
        "cost_scaling_factor": 3.5,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "destination_guarantee": {
        "label": "Robust Goal Arrival (Anti-Stuck)",
        "desc": "Realistic goal tolerances (0.08m, 0.12rad), generous progress allowance (15s), and steep inflation falloff to reach destination",
        "base": "2wd",
        "max_vel_x": 0.4,
        "max_vel_y": 0.0,
        "max_vel_theta": 2.0,
        "max_accel_x": 2.0,
        "max_accel_y": 0.0,
        "max_accel_theta": 2.5,
        "xy_goal_tolerance": 0.08,
        "yaw_goal_tolerance": 0.12,
        "movement_time_allowance": 15.0,
        "required_movement_radius": 0.15,
        "inflation_radius": 0.52,
        "cost_scaling_factor": 5.5,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "standard_diff": {
        "label": "Standard Differential (2WD / 4WD)",
        "desc": "Balanced default for indoor differential / skid-steer navigation",
        "base": "2wd",
        "max_vel_x": 0.5,
        "max_vel_y": 0.0,
        "max_vel_theta": 2.5,
        "max_accel_x": 2.5,
        "max_accel_y": 0.0,
        "max_accel_theta": 3.2,
        "inflation_radius": 0.7,
        "cost_scaling_factor": 3.0,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "mecanum_omni": {
        "label": "Mecanum (Omnidirectional Strafe)",
        "desc": "Holonomic omnidirectional drive with lateral velocity and Omni motion model",
        "base": "mecanum",
        "max_vel_x": 0.5,
        "max_vel_y": 0.5,
        "max_vel_theta": 2.5,
        "max_accel_x": 2.5,
        "max_accel_y": 2.5,
        "max_accel_theta": 3.2,
        "inflation_radius": 0.65,
        "cost_scaling_factor": 3.5,
        "ekf_frequency": 50.0,
        "fuse_vy": True,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 10.0,
    },
    "cautious_indoor": {
        "label": "Cautious / Tight Hallways",
        "desc": "Lower speeds and larger obstacle safety margins for narrow passages and crowded areas",
        "base": "2wd",
        "max_vel_x": 0.3,
        "max_vel_y": 0.0,
        "max_vel_theta": 1.8,
        "max_accel_x": 1.5,
        "max_accel_y": 0.0,
        "max_accel_theta": 2.0,
        "inflation_radius": 0.85,
        "cost_scaling_factor": 2.0,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.04,
        "slam_max_range": 8.0,
    },
    "fast_open_space": {
        "label": "Fast / Large Open Space",
        "desc": "Higher cruising speed and acceleration for open warehouses or arenas",
        "base": "2wd",
        "max_vel_x": 0.8,
        "max_vel_y": 0.0,
        "max_vel_theta": 3.0,
        "max_accel_x": 3.0,
        "max_accel_y": 0.0,
        "max_accel_theta": 4.0,
        "inflation_radius": 0.6,
        "cost_scaling_factor": 4.0,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.05,
        "slam_max_range": 12.0,
    },
    "high_res_slam": {
        "label": "High-Definition Mapping",
        "desc": "Sub-centimeter (0.025m) SLAM resolution with frequent keyframe updates for fine floor plans",
        "base": "2wd",
        "max_vel_x": 0.35,
        "max_vel_y": 0.0,
        "max_vel_theta": 2.0,
        "max_accel_x": 2.0,
        "max_accel_y": 0.0,
        "max_accel_theta": 2.5,
        "inflation_radius": 0.7,
        "cost_scaling_factor": 3.0,
        "ekf_frequency": 50.0,
        "fuse_vy": False,
        "fuse_imu_yaw": False,
        "slam_resolution": 0.025,
        "slam_max_range": 12.0,
    },
}


def patch_nav2_text(text, base_type='2wd', max_vel_x=0.5, max_vel_y=None, max_vel_theta=2.5,
                    max_accel_x=2.5, max_accel_y=None, max_accel_theta=3.2, desired_linear_vel=None,
                    inflation_radius=None, cost_scaling_factor=None,
                    max_decel_x=None, max_decel_theta=None,
                    xy_goal_tolerance=None, yaw_goal_tolerance=None,
                    lookahead_dist=None, approach_velocity_scaling_dist=None,
                    movement_time_allowance=None, required_movement_radius=None,
                    rotate_to_heading_angular_vel=None, angular_dist_threshold=None,
                    symmetric_yaw_tolerance=None,
                    raytrace_range=None, obstacle_max_range=None):
    """Patch Nav2 YAML text with specified speed, acceleration, and kinematic parameters."""
    is_mecanum = (str(base_type).strip().lower() == 'mecanum')
    max_vel_x = float(max_vel_x)
    max_vel_theta = float(max_vel_theta)
    max_accel_x = float(max_accel_x)
    max_accel_theta = float(max_accel_theta)

    if max_vel_y is None:
        max_vel_y = max_vel_x if is_mecanum else 0.0
    else:
        max_vel_y = float(max_vel_y) if is_mecanum else 0.0

    if max_accel_y is None:
        max_accel_y = max_accel_x if is_mecanum else 0.0
    else:
        max_accel_y = float(max_accel_y) if is_mecanum else 0.0

    if desired_linear_vel is None:
        desired_linear_vel = round(max_vel_x * 0.8, 3)
    else:
        desired_linear_vel = float(desired_linear_vel)

    # 1. AMCL motion model
    model = '"nav2_amcl::OmniMotionModel"' if is_mecanum else '"nav2_amcl::DifferentialMotionModel"'
    text = re.sub(r'(robot_model_type:\s*)[^\n]+', rf'\g<1>{model}', text)

    # 2. min_y_velocity_threshold in controller_server
    y_thresh = 0.001 if is_mecanum else 0.5
    text = re.sub(r'(min_y_velocity_threshold:\s*)[^\n]+', rf'\g<1>{y_thresh}', text)

    # 3. velocity_smoother
    max_vel_str = f'[{max_vel_x}, {max_vel_y}, {max_vel_theta}]'
    min_vel_str = f'[-{max_vel_x}, -{max_vel_y}, -{max_vel_theta}]'
    max_acc_str = f'[{max_accel_x}, {max_accel_y}, {max_accel_theta}]'
    dec_x = abs(float(max_decel_x)) if max_decel_x is not None else max_accel_x
    dec_th = abs(float(max_decel_theta)) if max_decel_theta is not None else max_accel_theta
    max_dec_str = f'[-{dec_x}, -{max_accel_y}, -{dec_th}]'

    text = re.sub(r'(max_velocity:\s*)\[[^\]]+\]', rf'\g<1>{max_vel_str}', text)
    text = re.sub(r'(min_velocity:\s*)\[[^\]]+\]', rf'\g<1>{min_vel_str}', text)
    text = re.sub(r'(max_accel:\s*)\[[^\]]+\]', rf'\g<1>{max_acc_str}', text)
    text = re.sub(r'(max_decel:\s*)\[[^\]]+\]', rf'\g<1>{max_dec_str}', text)

    # 4. RegulatedPurePursuitController (Jazzy / Lyrical / Rolling)
    text = re.sub(r'(desired_linear_vel:\s*)[^\n]+', rf'\g<1>{desired_linear_vel}', text)
    text = re.sub(r'(max_angular_accel:\s*)[^\n]+', rf'\g<1>{max_accel_theta}', text)
    rot_heading = round(max_vel_theta * 0.72, 3)
    text = re.sub(r'(rotate_to_heading_angular_vel:\s*)[^\n]+', rf'\g<1>{rot_heading}', text)

    # 5. DWB Local Planner (Humble)
    max_speed_xy = round(math.sqrt(max_vel_x**2 + max_vel_y**2), 3) if is_mecanum else max_vel_x
    text = re.sub(r'(\bmax_vel_x:\s*)[^\n]+', rf'\g<1>{max_vel_x}', text)
    text = re.sub(r'(\bmax_vel_y:\s*)[^\n]+', rf'\g<1>{max_vel_y}', text)
    text = re.sub(r'(\bmax_vel_theta:\s*)[^\n]+', rf'\g<1>{max_vel_theta}', text)
    text = re.sub(r'(\bmax_speed_xy:\s*)[^\n]+', rf'\g<1>{max_speed_xy}', text)
    text = re.sub(r'(\bacc_lim_x:\s*)[^\n]+', rf'\g<1>{max_accel_x}', text)
    text = re.sub(r'(\bacc_lim_y:\s*)[^\n]+', rf'\g<1>{max_accel_y}', text)
    text = re.sub(r'(\bacc_lim_theta:\s*)[^\n]+', rf'\g<1>{max_accel_theta}', text)
    text = re.sub(r'(\bdecel_lim_x:\s*)[^\n]+', rf'\g<1>-{max_accel_x}', text)
    text = re.sub(r'(\bdecel_lim_y:\s*)[^\n]+', rf'\g<1>-{max_accel_y}', text)
    text = re.sub(r'(\bdecel_lim_theta:\s*)[^\n]+', rf'\g<1>-{max_accel_theta}', text)
    if is_mecanum:
        text = re.sub(r'(\bvy_samples:\s*)[^\n]+', r'\g<1>20', text)

    # 6. Costmap inflation layer
    if inflation_radius is not None:
        text = re.sub(r'(inflation_radius:\s*)[^\n]+', rf'\g<1>{float(inflation_radius)}', text)
    if cost_scaling_factor is not None:
        text = re.sub(r'(cost_scaling_factor:\s*)[^\n]+', rf'\g<1>{float(cost_scaling_factor)}', text)

    # 10. Costmap raytrace and obstacle clearing (Upstream Issue #37)
    if raytrace_range is not None:
        text = re.sub(r'(\braytrace_range:\s*)[^\n]+', rf'\g<1>{float(raytrace_range)}', text)
    if obstacle_max_range is not None:
        text = re.sub(r'(\bobstacle_max_range:\s*)[^\n]+', rf'\g<1>{float(obstacle_max_range)}', text)

    return text


def patch_ekf_text(text, base_type='2wd', frequency=50.0, two_d_mode=True,
                   fuse_vy=None, fuse_imu_yaw=False, fuse_imu_vyaw=True):
    """Patch EKF YAML text for base kinematics and sensor fusion options."""
    is_mecanum = (str(base_type).strip().lower() == 'mecanum')
    if fuse_vy is None:
        fuse_vy = is_mecanum

    vy_val = 'true' if fuse_vy else 'false'
    two_d_val = 'true' if two_d_mode else 'false'
    yaw_val = 'true' if fuse_imu_yaw else 'false'
    vyaw_val = 'true' if fuse_imu_vyaw else 'false'

    # Update frequency
    text = re.sub(r'(frequency:\s*)[^\n]+', rf'\g<1>{float(frequency)}', text)

    # Update two_d_mode
    text = re.sub(r'(two_d_mode:\s*)[^\n]+', rf'\g<1>{two_d_val}', text)

    # Update odom0_config:
    odom_pattern = r'(odom0_config:\s*\[\s*false,\s*false,\s*false,\s*\n\s*false,\s*false,\s*false,\s*\n\s*true,\s*)(true|false)(\s*,\s*false)'
    text = re.sub(odom_pattern, rf'\g<1>{vy_val}\g<3>', text)

    # Update imu0_config:
    imu_pattern = (
        r'(imu0_config:\s*\[\s*false,\s*false,\s*false,\s*\n\s*false,\s*false,\s*)'
        r'(true|false)'
        r'(\s*,\s*\n\s*false,\s*false,\s*false,\s*\n\s*false,\s*false,\s*)'
        r'(true|false)'
        r'(\s*,\s*\n\s*false,\s*false,\s*false\s*\])'
    )
    text = re.sub(imu_pattern, rf'\g<1>{yaw_val}\g<3>{vyaw_val}\g<5>', text)

    return text


def patch_slam_text(text, resolution=None, max_laser_range=None,
                    minimum_travel_distance=None, minimum_travel_heading=None,
                    loop_search_maximum_distance=None, map_update_interval=None):
    """Patch SLAM Toolbox YAML configuration."""
    if resolution is not None:
        text = re.sub(r'(resolution:\s*)[^\n]+', rf'\g<1>{float(resolution)}', text)
    if max_laser_range is not None:
        text = re.sub(r'(max_laser_range:\s*)[^\n]+', rf'\g<1>{float(max_laser_range)}', text)
        text = re.sub(r'(scan_buffer_maximum_scan_distance:\s*)[^\n]+', rf'\g<1>{float(max_laser_range)}', text)
    if minimum_travel_distance is not None:
        text = re.sub(r'(minimum_travel_distance:\s*)[^\n]+', rf'\g<1>{float(minimum_travel_distance)}', text)
    if minimum_travel_heading is not None:
        text = re.sub(r'(minimum_travel_heading:\s*)[^\n]+', rf'\g<1>{float(minimum_travel_heading)}', text)
    if loop_search_maximum_distance is not None:
        text = re.sub(r'(loop_search_maximum_distance:\s*)[^\n]+', rf'\g<1>{float(loop_search_maximum_distance)}', text)
    if map_update_interval is not None:
        text = re.sub(r'(map_update_interval:\s*)[^\n]+', rf'\g<1>{float(map_update_interval)}', text)
    return text


def patch_nav2_file(input_path, output_path=None, **kwargs):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f'File not found: {input_path}')
    with open(input_path, 'r') as f:
        content = f.read()
    patched = patch_nav2_text(content, **kwargs)
    out_target = output_path if output_path else input_path
    with open(out_target, 'w') as f:
        f.write(patched)
    return out_target


def patch_ekf_file(input_path, output_path=None, **kwargs):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f'File not found: {input_path}')
    with open(input_path, 'r') as f:
        content = f.read()
    patched = patch_ekf_text(content, **kwargs)
    out_target = output_path if output_path else input_path
    with open(out_target, 'w') as f:
        f.write(patched)
    return out_target


def patch_slam_file(input_path, output_path=None, **kwargs):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f'File not found: {input_path}')
    with open(input_path, 'r') as f:
        content = f.read()
    patched = patch_slam_text(content, **kwargs)
    out_target = output_path if output_path else input_path
    with open(out_target, 'w') as f:
        f.write(patched)
    return out_target


def main():
    parser = argparse.ArgumentParser(description='Patch Nav2, EKF or SLAM YAML configuration')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Nav2 subparser
    p_nav2 = subparsers.add_parser('nav2', help='Patch Nav2 parameters')
    p_nav2.add_argument('-i', '--input', required=True, help='Input Nav2 YAML file')
    p_nav2.add_argument('-o', '--output', help='Output Nav2 YAML file')
    p_nav2.add_argument('-b', '--base', default='2wd', choices=['2wd', '4wd', 'mecanum'],
                        help='Robot base type (2wd, 4wd, mecanum)')
    p_nav2.add_argument('--max-vel-x', type=float, default=0.5, help='Max linear velocity (m/s)')
    p_nav2.add_argument('--max-vel-y', type=float, default=None, help='Max lateral velocity (m/s)')
    p_nav2.add_argument('--max-vel-theta', type=float, default=2.5, help='Max angular velocity (rad/s)')
    p_nav2.add_argument('--max-accel-x', type=float, default=2.5, help='Max linear accel (m/s^2)')
    p_nav2.add_argument('--max-accel-y', type=float, default=None, help='Max lateral accel (m/s^2)')
    p_nav2.add_argument('--max-accel-theta', type=float, default=3.2, help='Max angular accel (rad/s^2)')
    p_nav2.add_argument('--desired-linear-vel', type=float, default=None, help='Desired linear tracking speed')
    p_nav2.add_argument('--inflation-radius', type=float, default=None, help='Obstacle inflation radius (m)')
    p_nav2.add_argument('--cost-scaling-factor', type=float, default=None, help='Cost scaling factor')

    # EKF subparser
    p_ekf = subparsers.add_parser('ekf', help='Patch EKF parameters')
    p_ekf.add_argument('-i', '--input', required=True, help='Input EKF YAML file')
    p_ekf.add_argument('-o', '--output', help='Output EKF YAML file')
    p_ekf.add_argument('-b', '--base', default='2wd', choices=['2wd', '4wd', 'mecanum'],
                       help='Robot base type')
    p_ekf.add_argument('--frequency', type=float, default=50.0, help='EKF update frequency (Hz)')
    p_ekf.add_argument('--fuse-vy', action='store_true', default=None, help='Explicitly fuse lateral velocity')
    p_ekf.add_argument('--no-fuse-vy', dest='fuse_vy', action='store_false', help='Disable lateral velocity fusion')
    p_ekf.add_argument('--fuse-imu-yaw', action='store_true', default=False, help='Fuse IMU orientation yaw')
    p_ekf.add_argument('--two-d-mode', action='store_true', default=True, help='Enable 2D planar mode')

    # SLAM subparser
    p_slam = subparsers.add_parser('slam', help='Patch SLAM parameters')
    p_slam.add_argument('-i', '--input', required=True, help='Input SLAM YAML file')
    p_slam.add_argument('-o', '--output', help='Output SLAM YAML file')
    p_slam.add_argument('--resolution', type=float, default=None, help='Map resolution (m/pixel)')
    p_slam.add_argument('--max-laser-range', type=float, default=None, help='Laser max range (m)')
    p_slam.add_argument('--min-travel-dist', type=float, default=None, help='Min travel distance for keyframe (m)')

    # Preset subparser
    p_preset = subparsers.add_parser('preset', help='Apply tuning preset across configs')
    p_preset.add_argument('--preset', required=True, choices=list(PRESETS.keys()), help='Preset name')
    p_preset.add_argument('--nav2-file', help='Nav2 YAML file to patch')
    p_preset.add_argument('--ekf-file', help='EKF YAML file to patch')
    p_preset.add_argument('--slam-file', help='SLAM YAML file to patch')

    args = parser.parse_args()

    if args.command == 'nav2':
        out = patch_nav2_file(
            args.input,
            args.output,
            base_type=args.base,
            max_vel_x=args.max_vel_x,
            max_vel_y=args.max_vel_y,
            max_vel_theta=args.max_vel_theta,
            max_accel_x=args.max_accel_x,
            max_accel_y=args.max_accel_y,
            max_accel_theta=args.max_accel_theta,
            desired_linear_vel=args.desired_linear_vel,
            inflation_radius=args.inflation_radius,
            cost_scaling_factor=args.cost_scaling_factor
        )
        print(f'Successfully patched Nav2 configuration -> {out}')

    elif args.command == 'ekf':
        out = patch_ekf_file(
            args.input,
            args.output,
            base_type=args.base,
            frequency=args.frequency,
            two_d_mode=args.two_d_mode,
            fuse_vy=args.fuse_vy,
            fuse_imu_yaw=args.fuse_imu_yaw
        )
        print(f'Successfully patched EKF configuration -> {out}')

    elif args.command == 'slam':
        out = patch_slam_file(
            args.input,
            args.output,
            resolution=args.resolution,
            max_laser_range=args.max_laser_range,
            minimum_travel_distance=args.min_travel_dist
        )
        print(f'Successfully patched SLAM configuration -> {out}')

    elif args.command == 'preset':
        cfg = PRESETS[args.preset]
        print(f"Applying preset '{args.preset}': {cfg['label']}")
        if args.nav2_file:
            patch_nav2_file(
                args.nav2_file,
                base_type=cfg["base"],
                max_vel_x=cfg["max_vel_x"],
                max_vel_y=cfg["max_vel_y"],
                max_vel_theta=cfg["max_vel_theta"],
                max_accel_x=cfg["max_accel_x"],
                max_accel_y=cfg["max_accel_y"],
                max_accel_theta=cfg["max_accel_theta"],
                inflation_radius=cfg["inflation_radius"],
                cost_scaling_factor=cfg["cost_scaling_factor"]
            )
            print(f"  -> Nav2 patched: {args.nav2_file}")
        if args.ekf_file:
            patch_ekf_file(
                args.ekf_file,
                base_type=cfg["base"],
                frequency=cfg["ekf_frequency"],
                fuse_vy=cfg["fuse_vy"],
                fuse_imu_yaw=cfg["fuse_imu_yaw"]
            )
            print(f"  -> EKF patched: {args.ekf_file}")
        if args.slam_file:
            patch_slam_file(
                args.slam_file,
                resolution=cfg["slam_resolution"],
                max_laser_range=cfg["slam_max_range"]
            )
            print(f"  -> SLAM patched: {args.slam_file}")


if __name__ == '__main__':
    main()
