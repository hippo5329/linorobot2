# 🌐 Robot Configuration Engine — Web UI User Guide & Tutorial

The **Linorobot2 Robot Configuration Engine Web UI** is an interactive, zero-dependency, 100% client-side visual design studio. It enables robot builders to configure kinematics, select microcontrollers, assign conflict-free GPIO pins, visually verify electrical safety limits, and generate all firmware headers and ROS 2 URDF descriptions directly in their web browser.

---

## 1. Accessing & Launching the Web UI

The Web UI is self-contained in `tools/robot_config_engine/web/`. It requires no installation, no node.js server, and no cloud backend.

### Method 1: Local HTTP Server (Recommended)
From your `linorobot2_hardware` workspace:
```bash
cd tools/robot_config_engine/web
python3 -m http.server 8000
```
Then navigate to **`http://localhost:8000`** in your browser.

### Method 2: Direct File Open
You can directly double-click or open `tools/robot_config_engine/web/index.html` in Google Chrome, Firefox, Safari, or Edge.

---

## 2. Web UI Layout & Visual Overview

![Linorobot2 Robot Configuration Engine Web UI Overview](images/webui_overview.png)

The Web UI is organized into two synchronized panes:
* **Left Configurator Pane**: Interactive tabs for Robot Base/MCU, Drive & Motors, Sensors, and Pinout Matrix.
* **Right Dashboard Pane**: Real-time Kinematics HUD, Electrical Safety Inspector, and Multi-Artifact Code Generator.

---

## 3. Step-by-Step Configuration Tutorial

### Step 1: Select a Reference Build Preset (Optional)
Use the **⚡ Reference Build** dropdown in the top header to quickly pre-fill all parameters:
* **Raspberry Pi Pico 2**: 2WD Differential Drive, BTS7960 high-power motor driver, BNO085 IMU, Sonar range finder, and ADC battery divider.
* **ESP32 (4WD Mecanum)**: 4WD Mecanum Drive, WiFi UDP transport, BNO085 IMU, and I2C INA219 current/voltage monitor.
* **ESP32-S3 (4WD Skid Steer)**: 4WD Skid Steer, Native USB CDC Serial, MPU6050 IMU, HC-SR04 ultrasonic range sensor.
* **Waveshare General Driver Board**: ESP32 with onboard drivers, QMI8658 6-DOF IMU, and AK09918 magnetometer.

---

### Step 2: Configure Base & Microcontroller (Tab 1)
1. **Robot Name**: Enter a lowercase identifier (e.g. `scout_pico2`, `rover_bot`). This name prefixes the generated C++ headers and URDF files.
2. **Kinematics Base Type**:
   - **2WD Differential Drive**: 2 driving wheels + passive casters.
   - **4WD Skid Steer**: 4 fixed wheels turning by differential wheel slip.
   - **4WD Mecanum Drive**: 4 omnidirectional Mecanum roller wheels.
3. **Microcontroller Unit (MCU)**:
   - `PICO2` (RP2350) or `PICO` (RP2040) — Uses native USB CDC (`/dev/ttyACM0`).
   - `ESP32` — Standard dual-core with WiFi/Bluetooth.
   - `ESP32S3` — SuperMini with native USB CDC.
   - `GENDRV` — Waveshare ESP32 Robot Driver Board.
4. **micro-ROS Transport**:
   - `SERIAL`: USB CDC Serial connected directly to onboard SBC (Raspberry Pi / Jetson).
   - `WIFI_UDP`: Standalone wireless connection; reveals fields to input WiFi SSID, Password, and host micro-ROS Agent IP & Port.

---

### Step 3: Set Chassis Geometry & Motors (Tab 2)

![Chassis Geometry, Kinematics & Motor Driver Configuration](images/webui_drive_tab.png)

1. **Wheel Diameter**: Measure in meters (e.g., $0.080\text{ m} = 80\text{ mm}$).
2. **Track Width**: Center-to-center lateral distance between left and right wheels in meters.
3. **Wheelbase** *(4WD/Mecanum only)*: Center-to-center longitudinal distance between front and rear axles.
4. **Motor Driver Type**:
   - **BTS7960**: 43A dual H-bridge (uses `PWM_R`, `PWM_L`, and optional `EN`).
   - **Generic 2-IN** (L298N / TB6612): Uses `PWM` (speed), `IN_A`, and `IN_B` (direction).
   - **Generic 1-IN** (Cytron MD10C): Uses `PWM` (speed) and `DIR` (direction).
   - **ESC**: RC Electronic Speed Controller / continuous rotation servo PWM.
5. **Motor Max RPM & CPR**:
   - Rated RPM under operating voltage (e.g., `330` or `400` RPM).
   - Encoder Counts Per Revolution (CPR) (e.g., $11\text{ PPR} \times 4\text{ (quadrature)} \times 30\text{ (gearbox)} = 1320\text{ CPR}$).
6. **Inversion Toggles**: Check the boxes to invert individual motors or encoders (e.g., Motor 2 on the right side is typically inverted).

---

### Step 4: Configure Sensors & Peripherals (Tab 3)

![IMU, Magnetometer, Battery & Sonar Sensor Settings](images/webui_sensors_tab.png)

1. **IMU**: Select your 6-DOF or 9-DOF motion sensor (`BNO085`, `MPU6050`, `QMI8658`, `MPU9250`).
2. **Magnetometer**: Select your digital compass (`QMC5883L`, `AK09918`, `HMC5883L`) or choose `Fake Magnetometer` if navigating without a compass.
3. **Battery Monitoring**:
   - `ADC Resistor Voltage Divider`: Automatically applies the $30\text{k}\Omega / 7.5\text{k}\Omega$ voltage calculation formula.
   - `INA219`: I2C high-side voltage and current monitoring IC.
4. **Ultrasonic Range Sensor**: Enable to publish `sensor_msgs/msg/Range` on `/sonar` via HC-SR04 trigger and echo pins.

---

### Step 5: Allocate MCU Pins with Smart Auto-Assign (Tab 4)

![Microcontroller Pin Allocation & Smart Auto-Assign Matrix](images/webui_pinout_matrix.png)

Instead of manually checking datasheets for pin conflicts:
1. Click the **⚡ Smart Auto-Assign** button.
2. The engine instantly calculates a verified, conflict-free pin layout customized to your selected microcontroller:
   - Allocates dedicated hardware timer channels for motor PWM.
   - Places encoder lines on high-speed hardware interrupt GPIOs.
   - Connects I2C SDA/SCL to the primary hardware bus.
   - Reserves analog pins exclusively for battery monitoring (`GP26-28` on Pico).
   - Avoids ESP32 boot strapping pins (`GPIO 0, 2, 12, 15`) and internal SPI Flash (`GPIO 6-11`).

---

## 4. Understanding Live Metrics & Safety Feedback

### Kinematics & Performance HUD
* **Max Linear Speed**: Computed with Linorobot2's standard 85% PID headroom rule:
  $$v_{\text{max}} = \left(\frac{\pi \times \text{Wheel Diameter} \times \text{Max RPM}}{60}\right) \times 0.85$$
* **Max Angular Velocity**:
  $$\omega_{\text{max}} = \frac{2 \times v_{\text{max}}}{\text{Track Width}}$$
* **Odometry Resolution**: Encoder resolution in ticks per meter traveled:
  $$\text{Ticks/m} = \frac{\text{CPR}}{\pi \times \text{Wheel Diameter}}$$

### Hardware Safety Inspector
The safety inspector updates in real time on every change:
* 🟢 **Green (PASSED)**: Zero errors and zero warnings. Safe to flash and power up.
* 🔴 **Red (ERROR)**:
  - *Duplicate Pin*: The same GPIO is mapped to two peripherals (e.g. `Pin 14 assigned to LED and Motor 1 PWM`).
  - *ESP32 Input-Only Pin*: `GPIO 34-39` assigned as an output (these lack output transistors).
  - *SPI Flash Pin*: `GPIO 6-11` assigned (will crash microcontroller firmware).
  - *RP2040 ADC Range*: Battery pin assigned outside `GP26-GP28`.
* ⚠️ **Yellow (WARNING)**:
  - *Strapping Pin*: Encoder wired to `GPIO 0, 2, 12, 15` on ESP32 or `0, 3, 45, 46` on S3 (may prevent booting if pulled LOW at power-on).

---

## 5. Exporting & Deploying Generated Code

### Artifact Preview Tabs
The code generator tab in the lower-right provides real-time previews:
1. **`C++ Header`**: Complete C++ configuration (`<robot_name>_config.h`) ready for `config/custom/`.
2. **`PlatformIO`**: Ready-to-use build environment block for `firmware/platformio.ini`.
3. **`ROS 2 URDF`**: Precise geometry xacro properties file for ROS 2 robot state publisher and Nav2 footprint.
4. **`Wiring Chart`**: Formatted markdown table mapping each physical wire from your MCU to the motor driver, encoder, IMU, and battery divider.
5. **`Spec JSON`**: The complete, portable JSON specification.

### One-Click Actions
- **📋 Copy**: Copies the active artifact code to your clipboard with a confirmation toast.
- **💾 Download**: Downloads the active file with the proper extension (`.h`, `.ini`, `.xacro`, `.md`, `.json`).
- **📥 Export Spec**: Exports the full specification as `<robot_name>_spec.json`.
- **📤 Import JSON**: Drag or select any existing `spec.json` to instantly reload and resume editing.

---

## 6. Advanced: AI-Assisted CLI & LLM Prompting

While the **Interactive Web UI** is the recommended visual tool for beginners and everyday robot building, advanced users and automated CI/CD pipelines can also use the backend Python CLI engine and LLM prompt templates:

* **Command-Line Validator & Generator**:
  ```bash
  python3 tools/robot_config_engine/generate_config.py --spec examples/scout_pico2.json
  ```
* **Automated Batch Processing**:
  You can pass any custom JSON specification to automatically validate safety rules, write C++ headers to `config/custom/`, inject PlatformIO environments into `firmware/platformio.ini`, and generate ROS 2 URDF xacros.
* **LLM Prompts**:
  You can ask an AI Assistant (such as Gemini or ChatGPT) to design a robot specification JSON from natural language hardware descriptions.

For complete CLI documentation and LLM prompt templates, see the [[CLI Configuration Engine Reference|Robot-Config-Engine-Tutorial]].

---

## 7. Navigation

* [[← Back to Linorobot2 Wiki Home|Home]]
* [[Recommended MCU|Home#recommended-mcu-for-beginners--pico2-pico]]
* [[Motor Drivers|Home#motor-driver-configuration--use_bts7960_motor_driver---recommended]]
* [[Supported Sensors|Home#supported-sensors]]
* [[I/O Pin Assignments|Home#io-pins-assignment]]
* [[Troubleshooting Guide|Home#troubleshooting-guide]]
* [[CLI Engine Reference|Robot-Config-Engine-Tutorial]]
