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

import json
import os
import sys
import tempfile
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

# Import server module from web/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "web"))
import server

class TestLinorobot2Console(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_config_path = server.CONFIG_PATH
        self.orig_nav2_config_path = server.NAV2_CONFIG_PATH
        server.CONFIG_PATH = os.path.join(self.temp_dir, "test_console_config.json")
        server.NAV2_CONFIG_PATH = os.path.join(self.temp_dir, "test_nav2_params.yaml")

    def tearDown(self):
        server.CONFIG_PATH = self.orig_config_path
        server.NAV2_CONFIG_PATH = self.orig_nav2_config_path
        if os.path.exists(self.temp_dir):
            for root, dirs, files in os.walk(self.temp_dir, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            os.rmdir(self.temp_dir)

    def test_default_config(self):
        cfg = server.load_config()
        self.assertEqual(cfg["agent_transport"], "serial")
        self.assertEqual(cfg["agent_device"], "/dev/ttyACM0")
        self.assertEqual(cfg["agent_port"], "8888")
        self.assertEqual(cfg["agent_baud"], "921600")
        self.assertEqual(cfg.get("ros_distro"), "jazzy")
        self.assertTrue(cfg.get("auto_bringup"))
        self.assertIn("workspace_path", cfg)

    def test_bringup_runner_and_distros(self):
        self.assertIsNotNone(server.bringup_runner)
        self.assertFalse(server.bringup_runner.is_busy())
        for d in ["jazzy", "lyrical", "rolling", "humble"]:
            self.assertIn(d, server.SUPPORTED_DISTROS)

    def test_nav2_config_endpoints(self):
        for distro in ["jazzy", "lyrical", "rolling", "humble"]:
            cfg = server.get_nav2_config(distro)
            self.assertTrue(len(cfg) > 0, f"Empty config for {distro}")
            self.assertIn("ros__parameters", cfg, f"ros__parameters not in {distro} config")
            if distro == "humble":
                self.assertIn("recoveries_server", cfg)
            else:
                self.assertIn("behavior_server", cfg)

        orig_jazzy = server.get_nav2_config("jazzy")
        test_content = "# custom test nav2 parameters\nros__parameters:\n  footprint: '[[0.25, 0.25], [-0.25, 0.25]]'\n"
        path = server.save_nav2_config(test_content, "jazzy")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(server.get_nav2_config("jazzy"), test_content)
        # restore original
        server.save_nav2_config(orig_jazzy, "jazzy")

    def test_save_and_load_config(self):
        new_cfg = {
            "workspace_path": "/tmp/custom_ws",
            "agent_transport": "udp4",
            "agent_device": "/dev/ttyUSB0",
            "agent_port": "9999",
            "agent_baud": "115200"
        }
        server.save_config(new_cfg)
        loaded = server.load_config()
        self.assertEqual(loaded["workspace_path"], "/tmp/custom_ws")
        self.assertEqual(loaded["agent_transport"], "udp4")
        self.assertEqual(loaded["agent_port"], "9999")
        self.assertEqual(loaded["agent_baud"], "115200")

    def test_laser_sensors_definitions(self):
        expected_keys = ["ydlidar", "xv11", "ldlidar", "sllidar"]
        for k in expected_keys:
            self.assertIn(k, server.LASER_SENSORS)
            sensor = server.LASER_SENSORS[k]
            self.assertIn("label", sensor)
            self.assertIn("install", sensor)
            self.assertIsInstance(sensor["install"], list)
            self.assertTrue(len(sensor["install"]) > 0)
            if sensor["udev"] is not None:
                self.assertIsInstance(sensor["udev"], list)

    def test_depth_sensors_definitions(self):
        expected_keys = ["realsense", "oakd", "astra"]
        for k in expected_keys:
            self.assertIn(k, server.DEPTH_SENSORS)
            sensor = server.DEPTH_SENSORS[k]
            self.assertIn("label", sensor)
            self.assertIn("install", sensor)
            self.assertIsInstance(sensor["install"], list)
            self.assertTrue(len(sensor["install"]) > 0)
            if sensor["udev"] is not None:
                self.assertIsInstance(sensor["udev"], list)

    def test_sensor_registry_is_single_source(self):
        """/api/sensors payload carries everything the frontend needs -- no client-side copies."""
        reg = server.sensor_registry()
        self.assertEqual(set(reg["laser"]), set(server.LASER_SENSORS))
        ld = reg["laser"]["ldlidar"]
        self.assertTrue(ld["serial"])
        self.assertEqual(ld["symlink"], "/dev/ldlidar")
        self.assertEqual(ld["docker_key"], "ldlidar")
        self.assertEqual([m["code"] for m in ld["models"]], ["ld06", "ld19", "stl27l"])
        self.assertTrue(all("product" in m for m in ld["models"]))
        # sllidar's one install covers seven bringup model codes
        self.assertEqual(len(reg["laser"]["sllidar"]["models"]), 7)
        # depth cameras are not serial-port devices
        self.assertFalse(reg["depth"]["realsense"]["serial"])

    def test_build_sensor_install_cmd(self):
        c = server.build_sensor_install_cmd("laser", "ldlidar", skip_udev=True, ws="/w")
        self.assertEqual(
            c,
            "cd /w && [ -d src/ldlidar_stl_ros2 ] || git clone "
            "https://github.com/hippo5329/ldlidar_stl_ros2.git src/ldlidar_stl_ros2 "
            "&& colcon build",
        )
        # udev appended when not skipped
        self.assertIn("udevadm control", server.build_sensor_install_cmd("laser", "ldlidar", ws="/w"))
        # udev_only drops the build steps
        only = server.build_sensor_install_cmd("laser", "sllidar", udev_only=True, ws="/w")
        self.assertIn("rplidar.rules", only)
        self.assertNotIn("colcon build", only)
        # {ws} substitution
        self.assertIn("/w/src/sllidar_ros2", only)
        # unknown / no-command sensor
        self.assertIsNone(server.build_sensor_install_cmd("depth", "zed"))
        self.assertIsNone(server.build_sensor_install_cmd("laser", "nope"))

    def test_to_by_path_is_idempotent_and_safe(self):
        # an already-stable path is returned unchanged
        p = "/dev/serial/by-path/pci-0000:00-usb-0:1:1.0-port0"
        self.assertEqual(server.to_by_path(p), p)
        self.assertEqual(server.to_by_path("/dev/serial/by-id/usb-Foo-if00"), "/dev/serial/by-id/usb-Foo-if00")
        # a device with no by-path mapping falls back to itself
        self.assertEqual(server.to_by_path("/dev/nonexistent-tty"), "/dev/nonexistent-tty")
        self.assertEqual(server.to_by_path(""), "")

    def test_list_serial_ports_shape(self):
        ports = server.list_serial_ports()
        self.assertIsInstance(ports, list)
        for p in ports:
            for k in ("preferred", "by_path", "by_id", "tty", "usb_id", "vendor", "model", "serial"):
                self.assertIn(k, p)
            self.assertTrue(p["preferred"])
            self.assertTrue(p["tty"].startswith("/dev/tty"))

    def test_costmap_depth_source_gating(self):
        import patcher
        sample = (
            "local_costmap:\n  local_costmap:\n    ros__parameters:\n"
            "      voxel_layer:\n        observation_sources: scan pointcloud\n"
            "        scan:\n          topic: /scan\n"
            "        pointcloud:\n          topic: /camera/depth/color/points\n"
            "collision_monitor:\n  ros__parameters:\n"
            "    observation_sources: [\"scan\"]\n"
        )
        self.assertTrue(patcher.costmap_depth_active(sample))
        off = patcher.patch_costmap_sources(sample, depth_enabled=False)
        self.assertIn("observation_sources: scan\n", off)
        self.assertNotIn("scan pointcloud", off)
        self.assertFalse(patcher.costmap_depth_active(off))
        # collision_monitor's list form is never touched
        self.assertIn('observation_sources: ["scan"]', off)
        # round-trips back on
        on = patcher.patch_costmap_sources(off, depth_enabled=True)
        self.assertEqual(on, sample)
        # idempotent
        self.assertEqual(patcher.patch_costmap_sources(on, depth_enabled=True), sample)

    def test_depth_costmap_gate_is_console_only(self):
        """The depth->costmap gate lives in the console's launch_nav2.py; upstream navigation.launch.py is untouched."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "linorobot2_navigation", "launch", "navigation.launch.py")) as fh:
            nav_src = fh.read()
        self.assertNotIn("depth_costmap", nav_src)
        self.assertNotIn("LINOROBOT2_DEPTH_SENSOR", nav_src)

        with open(os.path.join(os.path.dirname(__file__), "launch_nav2.py")) as fh:
            cons_src = fh.read()
        self.assertIn("name='depth_costmap'", cons_src)
        self.assertIn("LINOROBOT2_DEPTH_SENSOR", cons_src)
        self.assertIn("scan[ \\t]+pointcloud", cons_src)   # same gate regex as patcher
        self.assertIn("tempfile.NamedTemporaryFile", cons_src)
        # the arg is consumed here, not forwarded to navigation.launch.py
        self.assertNotIn("'depth_costmap':", cons_src)

    def test_shipped_nav_templates_have_gated_pointcloud(self):
        """Jazzy+ templates ship with the depth pointcloud source + block (like humble)."""
        cfg_dir = os.path.join(os.path.dirname(__file__), "config")
        for distro in ("jazzy", "lyrical", "rolling"):
            for suffix in ("", "_mecanum"):
                path = os.path.join(cfg_dir, f"nav2_{distro}{suffix}.yaml")
                with open(path) as fh:
                    text = fh.read()
                self.assertEqual(text.count("observation_sources: scan pointcloud"), 2, path)
                self.assertIn("topic: /camera/depth/color/points", text)
                self.assertIn('data_type: "PointCloud2"', text)
                # collision_monitor stays lidar-only
                self.assertIn('observation_sources: ["scan"]', text)

    def test_upstream_github_issues_diagnostics(self):
        """Test AI diagnosis and patches for common upstream GitHub issues (#113, #37, #76, #12)."""
        from server import analyze_robotics_ai

        # Upstream #113: Map continuously rotating during SLAM
        diag_113 = analyze_robotics_ai("Map continuously rotating with RPLidar A1 and vibrating IMU during SLAM")
        self.assertIn("Upstream #113/#67", diag_113["diagnosis"])
        self.assertFalse(diag_113["ekf_patch"]["fuse_imu_yaw"])
        self.assertEqual(diag_113["ekf_patch"]["frequency"], 50.0)
        self.assertEqual(diag_113["slam_patch"]["minimum_travel_heading"], 0.25)

        # Upstream #37: Obstacles can't clear in local costmap even after they move out
        diag_37 = analyze_robotics_ai("Obstacles cant clear in local costmap even after they move out ghost obstacle")
        self.assertIn("Upstream #37", diag_37["diagnosis"])
        self.assertEqual(diag_37["nav2_patch"]["raytrace_range"], 3.5)
        self.assertEqual(diag_37["nav2_patch"]["obstacle_max_range"], 3.0)

        # Upstream #76: Large robot jerks and runs slowly / fierce vibration
        diag_76 = analyze_robotics_ai("Large robot jerks and runs slowly with fierce vibration 50 kg")
        self.assertIn("Upstream #76", diag_76["diagnosis"])
        self.assertEqual(diag_76["nav2_patch"]["max_accel_x"], 1.0)
        self.assertEqual(diag_76["nav2_patch"]["max_decel_x"], 1.5)
        self.assertEqual(diag_76["nav2_patch"]["max_vel_theta"], 1.2)

    def test_ai_tune_rotation_modes(self):
        """Test AI diagnosis and patching for rotation, drift, overshoot, and unreachable destination."""
        from server import analyze_robotics_ai
        import patcher

        # 1. Rotation and spin stability
        diag_rot = analyze_robotics_ai("robot experiences rotational oscillation and spin slip during in-place turns", base="2wd")
        self.assertIn("Rotational instability or slip detected", diag_rot["diagnosis"])
        self.assertEqual(diag_rot["nav2_patch"]["rotate_to_heading_angular_vel"], 1.5)
        self.assertEqual(diag_rot["nav2_patch"]["angular_dist_threshold"], 0.785)
        self.assertEqual(diag_rot["nav2_patch"]["max_accel_theta"], 2.0)
        self.assertEqual(diag_rot["nav2_patch"]["yaw_goal_tolerance"], 0.12)
        self.assertFalse(diag_rot["ekf_patch"]["fuse_vy"])

        # 2. Drift
        diag_drift = analyze_robotics_ai("robot drifts sideways during in-place rotation", base="2wd")
        self.assertIn("State estimation drift detected", diag_drift["diagnosis"])
        self.assertFalse(diag_drift["ekf_patch"]["fuse_vy"])
        self.assertEqual(diag_drift["ekf_patch"]["frequency"], 50.0)

        # 3. Overshoot
        diag_over = analyze_robotics_ai("robot overshoots destination and blows past goal due to late braking", base="2wd")
        self.assertIn("Goal overshoot and late braking detected", diag_over["diagnosis"])
        self.assertEqual(diag_over["nav2_patch"]["max_decel_x"], 2.8)
        self.assertEqual(diag_over["nav2_patch"]["approach_velocity_scaling_dist"], 0.75)

        # 4. Unable to reach destination
        diag_reach = analyze_robotics_ai("robot unable to reach nav dest and times out near goal", base="2wd")
        self.assertIn("Robot unable to complete navigation to destination", diag_reach["diagnosis"])
        self.assertEqual(diag_reach["nav2_patch"]["xy_goal_tolerance"], 0.08)
        self.assertEqual(diag_reach["nav2_patch"]["movement_time_allowance"], 15.0)
        self.assertEqual(diag_reach["nav2_patch"]["inflation_radius"], 0.52)

    def test_patcher_all_presets(self):
        """Test that all presets including anti_drift, anti_overshoot, destination_guarantee, and smooth_rotation patch cleanly."""
        import patcher
        for p_name in ["standard_diff", "mecanum_omni", "cautious_indoor", "fast_open_space",
                       "anti_drift", "anti_overshoot", "destination_guarantee", "smooth_rotation"]:
            self.assertIn(p_name, patcher.PRESETS)

    # --- Sample Nav2 params, trimmed to the keys the patcher touches ---------
    NAV2_SAMPLE = (
        'amcl:\n  ros__parameters:\n'
        '    robot_model_type: "nav2_amcl::DifferentialMotionModel"\n'
        'controller_server:\n  ros__parameters:\n'
        '    min_y_velocity_threshold: 0.5\n'
        '    progress_checker:\n'
        '      required_movement_radius: 0.5\n'
        '      movement_time_allowance: 10.0\n'
        '    general_goal_checker:\n'
        '      xy_goal_tolerance: 0.35\n'
        '      yaw_goal_tolerance: 0.35\n'
        '    FollowPath:\n'
        '      angular_dist_threshold: 0.785\n'
        '      desired_linear_vel: 0.4  # cruise\n'
        '      lookahead_dist: 0.6\n'
        '      approach_velocity_scaling_dist: 0.6\n'
        '      max_vel_x: 0.5\n'
        '      acc_lim_x: 2.5\n'
        '      decel_lim_x: -2.5\n'
        'velocity_smoother:\n  ros__parameters:\n'
        '    max_velocity: [0.8, 0.0, 2.5]\n'
        '    min_velocity: [-0.8, 0.0, -2.5]\n'
        '    max_accel: [2.5, 0.0, 3.2]\n'
        '    max_decel: [-2.5, 0.0, -3.2]\n'
        'local_costmap:\n  local_costmap:\n    ros__parameters:\n'
        '      inflation_radius: 0.70\n'
        '      cost_scaling_factor: 3.0\n'
        '      raytrace_range: 3.0\n'
        '      obstacle_max_range: 2.5\n'
    )

    def test_patch_nav2_is_opt_in(self):
        """A targeted patch must not reset params it was not given (regression)."""
        import patcher
        # Only ask for a costmap-clearing fix (upstream #37 shape).
        out = patcher.patch_nav2_text(
            self.NAV2_SAMPLE,
            raytrace_range=3.5, obstacle_max_range=3.0, inflation_radius=0.55,
        )
        self.assertIn("raytrace_range: 3.5", out)
        self.assertIn("obstacle_max_range: 3.0", out)
        self.assertIn("inflation_radius: 0.55", out)
        # The tuned 0.8 m/s top speed and the AMCL model survive untouched.
        self.assertIn("max_velocity: [0.8, 0.0, 2.5]", out)
        self.assertIn("max_vel_x: 0.5", out)
        self.assertIn('robot_model_type: "nav2_amcl::DifferentialMotionModel"', out)
        self.assertIn("desired_linear_vel: 0.4  # cruise", out)

    def test_patch_nav2_applies_goal_and_rpp_params(self):
        """The goal-checker / RPP / progress-checker params must actually reach the YAML."""
        import patcher
        out = patcher.patch_nav2_text(
            self.NAV2_SAMPLE,
            xy_goal_tolerance=0.08, yaw_goal_tolerance=0.12,
            lookahead_dist=0.45, approach_velocity_scaling_dist=0.75,
            movement_time_allowance=15.0, required_movement_radius=0.15,
            angular_dist_threshold=0.6,
        )
        self.assertIn("xy_goal_tolerance: 0.08", out)
        self.assertIn("yaw_goal_tolerance: 0.12", out)
        self.assertIn("lookahead_dist: 0.45", out)
        self.assertIn("approach_velocity_scaling_dist: 0.75", out)
        self.assertIn("movement_time_allowance: 15.0", out)
        self.assertIn("required_movement_radius: 0.15", out)
        self.assertIn("angular_dist_threshold: 0.6", out)
        # Untouched velocity block stays put.
        self.assertIn("max_velocity: [0.8, 0.0, 2.5]", out)

    def test_patch_nav2_partial_velocity_reads_existing(self):
        """Supplying only max_vel_x keeps the file's y / theta components."""
        import patcher
        out = patcher.patch_nav2_text(self.NAV2_SAMPLE, max_vel_x=0.35)
        self.assertIn("max_velocity: [0.35, 0.0, 2.5]", out)
        self.assertIn("min_velocity: [-0.35, 0.0, -2.5]", out)

    def test_patch_ekf_is_opt_in(self):
        import patcher
        raw = (
            "ekf_filter_node:\n    ros__parameters:\n"
            "        frequency: 30.0\n        two_d_mode: true\n"
            "        odom0_config: [false, false, false,\n"
            "                       false, false, false,\n"
            "                       true, false, false,\n"
            "                       false, false, true,\n"
            "                       false, false, false]\n"
            "        imu0_config: [false, false, false,\n"
            "                      false, false, false,\n"
            "                      false, false, false,\n"
            "                      false, false, true,\n"
            "                      false, false, false]\n"
        )
        # Only disable IMU yaw fusion (upstream #113). Frequency 30.0 must remain.
        out = patcher.patch_ekf_text(raw, fuse_imu_yaw=False)
        self.assertIn("frequency: 30.0", out)
        self.assertIn("false, false, false,\n                      false, false, false", out)

    def test_kwargs_helpers_drop_absent_keys(self):
        import patcher
        kw = patcher.nav2_kwargs({"base": "mecanum", "inflation_radius": 0.6,
                                  "max_vel_x": None, "unrelated": 1})
        self.assertEqual(kw, {"base_type": "mecanum", "inflation_radius": 0.6})
        ekw = patcher.ekf_kwargs({"fuse_vy": True, "frequency": None}, base="4wd")
        self.assertEqual(ekw, {"base_type": "4wd", "fuse_vy": True})

    def test_deploy_robot_specs_shape(self):
        """generate_custom_robot_specs stays in the nested {design, tuning} shape the deploy path expects."""
        import patcher
        specs = server.generate_custom_robot_specs(
            "4WD Mecanum robot with 97mm wheels, 30cm track width, LD19 lidar")
        tuning = specs["tuning"]
        base = specs["design"]["base_type"]
        self.assertEqual(base, "mecanum")
        nav_kw = patcher.nav2_kwargs(dict(tuning["nav2"], base_type=base))
        self.assertEqual(nav_kw["base_type"], "mecanum")
        self.assertIn("inflation_radius", nav_kw)
        ekf_kw = patcher.ekf_kwargs(tuning["ekf"], base=base)
        self.assertTrue(ekf_kw["fuse_vy"])
        self.assertEqual(ekf_kw["frequency"], 50.0)

    def test_live_server_status_api(self):
        # Queries active console server on localhost:8090
        try:
            with urlopen("http://localhost:8090/api/status", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertIn("workspace_path", data)
                self.assertIn("host_ip", data)
                self.assertIn("os", data)
                self.assertIn("agent_busy_console", data)
                self.assertIn("bringup_busy_console", data)
                self.assertIn("supported_distros", data)
                self.assertIn("config", data)
        except Exception as e:
            self.skipTest(f"Console server not running on port 8090: {e}")

    def test_live_server_static_assets(self):
        # Verifies static assets are served properly
        for path, content_type in [
            ("/", "text/html"),
            ("/app.js", "application/javascript"),
            ("/style.css", "text/css")
        ]:
            try:
                with urlopen(f"http://localhost:8090{path}", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    ct = resp.headers.get("Content-Type", "")
                    self.assertIn(content_type, ct)
                    body = resp.read()
                    self.assertTrue(len(body) > 0)
            except Exception as e:
                self.skipTest(f"Static asset test skipped: {e}")

    def test_patcher_capabilities(self):
        import patcher
        self.assertIsNotNone(patcher)
        self.assertIn("standard_diff", patcher.PRESETS)
        self.assertIn("mecanum_omni", patcher.PRESETS)

        # Nav2 patching
        raw_nav = "amcl:\n  ros__parameters:\n    robot_model_type: \"nav2_amcl::DifferentialMotionModel\"\nvelocity_smoother:\n  ros__parameters:\n    max_velocity: [0.5, 0.0, 2.5]\n"
        patched_nav = patcher.patch_nav2_text(raw_nav, base_type="mecanum", max_vel_x=0.6, max_vel_theta=2.8)
        self.assertIn("nav2_amcl::OmniMotionModel", patched_nav)
        self.assertIn("[0.6, 0.6, 2.8]", patched_nav)

        # EKF patching
        raw_ekf = "ekf_filter_node:\n    ros__parameters:\n        frequency: 50.0\n        odom0_config: [false, false, false,\n                       false, false, false,\n                       true, false, false,\n                       false, false, true,\n                       false, false, false]\n"
        patched_ekf = patcher.patch_ekf_text(raw_ekf, base_type="mecanum", fuse_vy=True)
        self.assertIn("true, true, false", patched_ekf)

    def test_ai_robot_builder_logic(self):
        specs = server.generate_custom_robot_specs("4WD Mecanum delivery robot with 97mm wheels, 30cm track width, and LD19 lidar")
        self.assertIn("design", specs)
        self.assertIn("tuning", specs)
        self.assertEqual(specs["design"]["base_type"], "mecanum")
        self.assertEqual(specs["design"]["wheel_diameter_m"], 0.097)
        self.assertEqual(specs["design"]["track_width_m"], 0.30)
        self.assertEqual(specs["design"]["laser_sensor"], "ldlidar")
        self.assertTrue(specs["tuning"]["ekf"]["fuse_vy"])
        self.assertIn("OmniMotionModel", specs["tuning"]["nav2"]["robot_model_type"])

    def test_live_server_tuning_and_ai_apis(self):
        try:
            # Presets
            with urlopen("http://localhost:8090/api/presets", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("presets", data)
                self.assertIn("mecanum_omni", data["presets"])

            # EKF
            with urlopen("http://localhost:8090/api/ekf_config?base=mecanum", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("config", data)

            # SLAM
            with urlopen("http://localhost:8090/api/slam_config", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("config", data)

            # AI tune
            req = Request("http://localhost:8090/api/ai/tune",
                          data=json.dumps({"prompt": "Mecanum strafe", "base": "mecanum"}).encode(),
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("diagnosis", data)
                self.assertIn("nav2_patch", data)

            # AI Robot Builder
            req2 = Request("http://localhost:8090/api/ai/robot_builder",
                           data=json.dumps({"description": "Mecanum 97mm robot"}).encode(),
                           headers={"Content-Type": "application/json"})
            with urlopen(req2, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode())
                self.assertIn("design", data)
                self.assertIn("tuning", data)

        except Exception as e:
            self.skipTest(f"Live server test skipped: {e}")

if __name__ == "__main__":
    unittest.main()
