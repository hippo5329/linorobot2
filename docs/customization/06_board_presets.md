# Board Presets & Custom Robot Configuration

Linorobot2 includes tested preset headers for popular development boards and integrated all-in-one robot controllers. This chapter describes available presets and the step-by-step procedure for creating a custom robot configuration.

---

## 1. Available Hardware Presets

All board configuration headers reside in `config/custom/`:

| Preset Header | Target Board | Transport | Integrated Peripherals |
| :--- | :--- | :---: | :--- |
| **`pico_config.h`** | Raspberry Pi Pico (RP2040) | Serial CDC (`/dev/ttyACM0`) | 2WD / 4WD / Mecanum, TB6612 / BTS7960, MPU6050 |
| **`pico2_config.h`** | Raspberry Pi Pico 2 (RP2350) | Serial CDC (`/dev/ttyACM0`) | High-speed FPU, MPU6050 / BNO085 |
| **`esp32_config.h`** | NodeMCU-32S / ESP32 DevKit | Serial UART (`/dev/ttyUSBx`) | Dual H-bridge, ADC battery monitoring |
| **`esp32_wifi_config.h`** | NodeMCU-32S / ESP32 DevKit | Wi-Fi UDP | Headless remote agent, ArduinoOTA, Syslog |
| **`esp32s3_config.h`** | ESP32-S3 DevKitC-1 | Serial CDC (`/dev/ttyACM0`) | Native USB CDC, WS2812 status LED (GPIO 48) |
| **`esp32s3_wifi_config.h`**| ESP32-S3 DevKitC-1 | Wi-Fi UDP | High flash Wi-Fi headless setup |
| **`gendrv_config.h`** | Waveshare General Driver for Robots | Serial UART (`/dev/ttyUSBx`) | Onboard dual motor driver, QMI8658 IMU, INA219 |
| **`gendrv_wifi_config.h`** | Waveshare General Driver for Robots | Wi-Fi UDP | Integrated all-in-one Wi-Fi robot platform |

---

## 2. Waveshare General Driver for Robots Preset Spotlight

The **Waveshare General Driver for Robots** is a popular all-in-one commercial board containing:
- Built-in ESP32 microcontroller module
- Dual TB6612 H-bridge motor driver with current sensing
- Onboard 6-DOF QMI8658 IMU (I2C address `0x6B`)
- Onboard INA219 precision voltage/current monitor (I2C address `0x40`)
- Built-in 3S Li-ion battery management circuit

```cpp
// Excerpt from config/custom/gendrv_config.h:
#define USE_GENDRV_CONFIG
#define USE_GENERIC_2_IN_MOTOR_DRIVER
#define USE_QMI8658_IMU
#define USE_INA219

#define MOTOR1_PWM 26
#define MOTOR1_IN_A 25
#define MOTOR1_IN_B 33
#define MOTOR2_PWM 14
#define MOTOR2_IN_A 12
#define MOTOR2_IN_B 13
```

---

## 3. Creating a Custom Robot Configuration

To add your own custom robot without creating merge conflicts with upstream updates:

### Step 1: Create Your Custom Header
Copy an existing template to `config/custom/myrobot_config.h`:
```bash
cp config/custom/pico_config.h config/custom/myrobot_config.h
```
Edit your pin definitions, wheel diameter, track width, and encoder CPR in `myrobot_config.h`.

### Step 2: Register in `config/config.h`
Add your configuration entry between the user configuration barriers near the end of `config/config.h`:
```cpp
// add user configurations below this line
#ifdef USE_MYROBOT_CONFIG
    #include "custom/myrobot_config.h"
#endif
```

### Step 3: Add Target in `firmware/platformio.ini`
Append your custom target at the end of `firmware/platformio.ini`:
```ini
[env:myrobot]
platform = https://github.com/maxgerhardt/platform-raspberrypi.git
board = rpipico2
board_build.core = earlephilhower
build_flags =
    -I ../config
    -D PICO
    -D USE_MYROBOT_CONFIG
```
