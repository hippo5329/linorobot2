# Transport Layer & Micro-ROS Agent Setup

Linorobot2 communicates with ROS 2 via the **micro-ROS client-agent** protocol. This chapter explains how to configure serial and Wi-Fi transports, launch the micro-ROS agent, and monitor firmware diagnostics.

---

## 1. Transport Comparison

| Transport Mode | Medium | Agent Launch Command | Advantages |
| :--- | :---: | :--- | :--- |
| **Serial CDC / UART** | USB Cable | `ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyACM0 -b 115200` | Lowest latency (<1ms), zero packet drop, rock-solid stability |
| **Wi-Fi UDP** | 2.4 GHz 802.11 | `ros2 run micro_ros_agent micro_ros_agent udp4 --port 8888` | Completely wire-free, ideal for headless robots without an on-board computer |

---

## 2. Serial Transport Configuration

### Microcontroller Setup:
Serial transport is the default mode for `pico`, `pico2`, `esp32`, and `esp32s3` environments.
```cpp
// Serial transport is enabled by default when MICRO_ROS_TRANSPORT_ARDUINO_WIFI is NOT defined
#define BAUDRATE 115200
```

### Launching the Serial Agent:
On the host or robot computer:
```bash
ros2 run micro_ros_agent micro_ros_agent serial --dev /dev/ttyACM0 -b 115200
```

---

## 3. Wi-Fi Transport Configuration

### Step 1: Create Wi-Fi Configuration
Copy the template header to `config/custom/wifi_config.h`:
```bash
cp config/custom/wifi_config.h.template config/custom/wifi_config.h
```

### Step 2: Configure Credentials & Agent Endpoint
Edit `config/custom/wifi_config.h`:
```cpp
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// IP address of the workstation/host running micro_ros_agent
#define AGENT_IP IPAddress(192, 168, 1, 50)
#define AGENT_PORT 8888

// Optional Remote Syslog logging
#define SYSLOG_SERVER IPAddress(192, 168, 1, 50)
#define SYSLOG_PORT 514
#define DEVICE_HOSTNAME "linorobot2-esp32"
```

### Step 3: Launch UDP Agent on Host:
```bash
ros2 run micro_ros_agent micro_ros_agent udp4 --port 8888
```

---

## 4. Remote OTA Firmware Flashing

When using Wi-Fi transport on ESP32 / ESP32-S3, you can update firmware over the air without connecting USB cables:

```bash
# Upload over Wi-Fi via PlatformIO
pio run -e esp32_wifi -t upload --upload-port 192.168.1.105
```
