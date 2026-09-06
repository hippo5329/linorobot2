# Nav2 Customization & Tuning Guide
*(Synthesized from the Official Nav2 Documentation: First-Time Robot Setup Guide, Nav2 Tuning Guide & Plugin Customization Guides)*

This guide details the complete customization and parameter tuning architecture for **Navigation 2 (Nav2)**, **SLAM Toolbox**, and **robot_localization (EKF)** on Linorobot2 mobile robots across all supported ROS 2 distributions (**Jazzy**, **Lyrical**, **Rolling**, and **Humble**).

---

## 1. Nav2 System Architecture & Multi-Distro Parity

Nav2 relies on a managed lifecycle state machine (Unconfigured -> Inactive -> Active) and modular `pluginlib` components. Across ROS 2 distributions, Nav2 has evolved:

| Subsystem / Feature | ROS 2 Jazzy (24.04) / Lyrical (26.04) / Rolling | ROS 2 Humble (22.04 LTS) |
| :--- | :--- | :--- |
| **Recovery Engine** | `behavior_server` (Spin, BackUp, DriveOnHeading, AssistedTeleop) | `recoveries_server` (Spin, BackUp, Wait) |
| **Path Follower** | `RegulatedPurePursuitController` with `RotationShimController` | `DWBLocalPlanner` with `RotationShimController` |
| **Path Smoothing** | `smoother_server` (SimpleSmoother) | Custom planner smoothing |
| **Charging & Docking**| `docking_server` (SimpleChargingDock) | External docking node |
| **Velocity Limiter** | `nav2_velocity_smoother::VelocitySmoother` | `velocity_smoother` node |
| **Behavior Trees** | BehaviorTree.CPP v4 (`NavigateToPose`, `NavigateThroughPoses`) | BehaviorTree.CPP v3 legacy nodes |

Linorobot2 maintains validated per-distro configurations in:
- `linorobot2_navigation/config/navigation_<distro>.yaml` (Differential 2WD/4WD)
- `linorobot2_navigation/config/navigation_<distro>_mecanum.yaml` (Holonomic Mecanum)

---

## 2. Drive Kinematics & Coordinate Frames (TF2)

Per the **Nav2 First-Time Robot Setup Guide**, the coordinate transformation tree must be strictly maintained:

$$\text{map} \xrightarrow{\text{AMCL / SLAM}} \text{odom} \xrightarrow{\text{robot\_localization}} \text{base\_footprint} \xrightarrow{\text{URDF}} \text{base\_link} \xrightarrow{\text{URDF}} \text{laser / camera}$$

### 2.1 Differential Drive (2WD / 4WD Skid Steer)
Non-holonomic platforms cannot translate sideways ($v_y = 0$).

1. **Velocity Smoother (`velocity_smoother`)**:
   ```yaml
   velocity_smoother:
     ros__parameters:
       smoothing_frequency: 20.0
       scale_velocities: False
       feedback: "OPEN_LOOP"
       max_velocity: [0.5, 0.0, 2.5]       # [vx, vy, vtheta] -- vy is 0.0!
       min_velocity: [-0.5, 0.0, -2.5]
       max_accel: [2.5, 0.0, 3.2]          # [ax, ay, atheta] -- ay is 0.0!
       max_decel: [-2.5, 0.0, -3.2]
   ```
2. **AMCL Motion Model**:
   ```yaml
   amcl:
     ros__parameters:
       robot_model_type: "nav2_amcl::DifferentialMotionModel"
   ```
3. **Controller Lateral Velocity Filter**:
   ```yaml
   controller_server:
     ros__parameters:
       min_y_velocity_threshold: 0.5       # Suppresses encoder noise in Y
   ```
4. **EKF Fusion (`linorobot2_base/config/ekf_2wd.yaml`)**:
   `odom0_config` **MUST** set $v_y$ (row 3, column 2) to `false`. If enabled on differential drive, in-place wheel slip gets integrated into false lateral position drift!

---

### 2.2 Holonomic Mecanum Drive
Mecanum robots move omnidirectionally with independent forward ($v_x$), lateral ($v_y$), and rotational ($\omega$) motion.

1. **Velocity Smoother (`velocity_smoother`)**:
   ```yaml
   velocity_smoother:
     ros__parameters:
       max_velocity: [0.5, 0.5, 2.5]       # vy enabled (0.5 m/s)
       min_velocity: [-0.5, -0.5, -2.5]
       max_accel: [2.5, 2.5, 3.2]          # ay enabled (2.5 m/s^2)
       max_decel: [-2.5, -2.5, -3.2]
   ```
2. **AMCL Motion Model**:
   ```yaml
   amcl:
     ros__parameters:
       robot_model_type: "nav2_amcl::OmniMotionModel"
   ```
3. **Controller Lateral Velocity Filter**:
   ```yaml
   controller_server:
     ros__parameters:
       min_y_velocity_threshold: 0.001     # Allows fine lateral strafing maneuvers
   ```
4. **EKF Fusion (`linorobot2_base/config/ekf_mecanum.yaml`)**:
   `odom0_config` sets $v_y$ to `true` to integrate genuine lateral strafe velocity from the 4 mecanum wheels.

---

## 3. Costmap Inflation Layer & The Potential Field Formula

Per the official **Nav2 Tuning Guide**, the inflation layer should not merely create an obstacle barrier, but rather establish a smooth, consistent **potential field** that guides global and local planners:

$$\text{Cost}(d) = \exp\left(-1.0 \times \text{cost\_scaling\_factor} \times (d - r_{inscribed})\right) \times (\text{INSCRIBED\_INFLATED\_OBSTACLE} - 1)$$

```
Cost ^
254  | [Lethal Obstacle: Physical Wall]
253  |----+ [Inscribed Radius: Robot collision boundary]
     |     \
     |      \  <-- Higher cost_scaling_factor (5.0 - 10.0) = steep dropoff (open doors)
     |       \ <-- Lower cost_scaling_factor  (2.0 - 3.5)  = gentle slope (center in aisles)
  0  +--------+-------------------> Distance (d)
              r_inscribed   inflation_radius
```

### 3.1 Resolving the 80cm Doorway Problem
- **Symptom**: The robot refuses to pass through standard 80cm interior doorways, hesitating, oscillating, or aborting with "no valid path".
- **Nav2 Tuning Guide Remedy**:
  When `inflation_radius: 0.70` and `cost_scaling_factor: 3.0` are used, inflation from both door posts overlaps across the center of an 80cm doorway. The planner sees costs $> 180$ across the entire opening and refuses to traverse it.
- **Solution**:
  1. Reduce `inflation_radius` to `0.52` m (just above the inscribed radius).
  2. Increase `cost_scaling_factor` to `5.5` – `6.0`.
  This creates a steep potential drop, opening a low-cost valley ($< 50$) through the exact center of the door.

---

## 4. Path Tracking & Oscillation Damping (RPP & DWB)

### 4.1 Regulated Pure Pursuit Controller (Jazzy / Lyrical / Rolling)
The official Nav2 documentation recommends RPP for robust path tracking with velocity regulation:

- **Adaptive Lookahead**:
  Enable `use_velocity_scaled_lookahead_dist: true`. Set `min_lookahead_dist: 0.3` m and `max_lookahead_dist: 0.9` m with `lookahead_time: 1.5` s. The controller looks further ahead at high speeds for stability, and tightens up at low speeds for precision.
- **Curvature Regulation**:
  `use_regulated_linear_velocity_scaling: true` automatically slows the robot on sharp turns to prevent wheel slip and rollover.
- **Goal Hunting / In-Place Oscillation**:
  If the robot rapidly shakes or oscillates at the final goal pose:
  1. Reduce `rotate_to_heading_angular_vel` from 1.8 down to `1.2` rad/s.
  2. Reduce `max_angular_accel` from 3.2 down to `2.2` rad/s².
  3. Increase `general_goal_checker` `yaw_goal_tolerance` to `0.15` rad (~8.5°).

### 4.2 DWB Local Planner (Humble)
In ROS 2 Humble:
- Set `min_vel_x: 0.0`, `max_vel_x: 0.4` m/s.
- For differential drive: `max_vel_y: 0.0`, `vy_samples: 1`.
- For mecanum drive: `max_vel_y: 0.4` m/s, `vy_samples: 20` (enables lateral trajectory rollout evaluation).

---

## 5. Unified Navigation & SLAM Launch Pipeline

In Linorobot2, `navigation.launch.py` and `slam.launch.py` are unified into a single architecture:

```bash
# Autonomous Navigation (with an existing map)
ros2 launch linorobot2_navigation navigation.launch.py \
  distro:=jazzy base:=mecanum map:=/path/to/my_map.yaml

# SLAM Mapping (generates map live without AMCL)
ros2 launch linorobot2_navigation navigation.launch.py \
  distro:=jazzy base:=mecanum slam:=true
```

> [!NOTE]
> `slam.launch.py` is an alias into `navigation.launch.py slam:=true`.

---

## 6. Automated Patcher Tool (`patcher.py`)

Linorobot2 includes a zero-dependency CLI patcher in `tools/linorobot2_console/patcher.py`:

```bash
# Apply a pre-configured expert preset:
python3 tools/linorobot2_console/patcher.py preset \
  --preset mecanum_omni \
  --nav2-file linorobot2_navigation/config/navigation_jazzy.yaml \
  --ekf-file linorobot2_base/config/ekf.yaml \
  --slam-file linorobot2_navigation/config/slam.yaml

# Patch specific velocity, acceleration, and inflation parameters:
python3 tools/linorobot2_console/patcher.py nav2 \
  -i linorobot2_navigation/config/navigation_jazzy.yaml \
  -b mecanum --max-vel-x 0.6 --inflation-radius 0.52 --cost-scaling-factor 5.5
```

---

## 7. AI Tuning Studio & Custom Robot Builder in Console

Linorobot2 Console (`http://localhost:8090/`) provides an interactive web-based studio:
- **AI Robotics Tuning Assistant**: Click prompt chips or describe symptoms (e.g. *"Doorway hesitation"* or *"Mecanum strafe"*) to receive physics diagnoses and 1-click parameter patches.
- **Curated Presets**: Quick application of `standard_diff`, `mecanum_omni`, `cautious_indoor`, `fast_open_space`, and `high_res_slam`.
- **AI Custom Robot Builder Studio**: Complete guided workflow from chassis design, wheel diameter, and motor RPM to firmware `custom_config.h`, URDF footprint, EKF 50Hz filter, and Nav2 profiles.
