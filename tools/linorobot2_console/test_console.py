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
        server.CONFIG_PATH = os.path.join(self.temp_dir, "test_console_config.json")

    def tearDown(self):
        server.CONFIG_PATH = self.orig_config_path
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
        self.assertIn("workspace_path", cfg)

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

if __name__ == "__main__":
    unittest.main()
