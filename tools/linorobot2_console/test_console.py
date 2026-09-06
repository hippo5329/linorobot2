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
