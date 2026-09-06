// Linorobot2 Console frontend. Vanilla JS, no build step, no framework --
// mirrors robot_config_engine/web/app.js: this file builds full shell command
// strings and POSTs them to a generic /api/exec (or /api/agent/exec) SSE
// runner on the server. The server does not know what "bringup" or "teleop"
// mean -- it just runs bash.

const state = {
  config: null,
  status: null,
  mainBusy: false,
  agentBusy: false,
};

const consolePane = document.getElementById("console-pane");
const consoleTitle = document.getElementById("console-title");
const consoleWrap = document.getElementById("console-wrap");

function logLine(text) {
  consolePane.textContent += text + "\n";
  consolePane.scrollTop = consolePane.scrollHeight;
}

function setConsoleTitle(title) {
  consoleTitle.textContent = title;
}

document.getElementById("console-clear").addEventListener("click", () => {
  consolePane.textContent = "";
});
document.getElementById("console-collapse").addEventListener("click", () => {
  consoleWrap.classList.toggle("collapsed");
});

// ---------- tabs ----------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ---------- generic SSE command runner ----------
// slot: "main" -> /api/exec ; "agent" -> /api/agent/exec
function runCommand(command, { slot = "main", title = "Running", onDone, onLine } = {}) {
  const endpoint = slot === "agent" ? "/api/agent/exec" : "/api/exec";
  setConsoleTitle(title);
  logLine(`$ ${title}`);
  return fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  }).then(async (response) => {
    if (response.status === 409) {
      logLine("[console] that slot is already busy -- stop the running action first.");
      if (onDone) onDone(-1);
      return;
    }
    if (!response.ok || !response.body) {
      logLine(`[console] failed to start: HTTP ${response.status}`);
      if (onDone) onDone(-1);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop();
      for (const frame of frames) {
        const evMatch = frame.match(/^event: (.+)$/m);
        const dataMatch = frame.match(/^data: (.+)$/m);
        if (!dataMatch) continue;
        const evType = evMatch ? evMatch[1] : "message";
        let payload;
        try {
          payload = JSON.parse(dataMatch[1]);
        } catch {
          continue;
        }
        if (evType === "output") {
          logLine(payload.line);
          if (onLine) onLine(payload.line);
        } else if (evType === "done") {
          logLine(`[console] exited with code ${payload.exit_code}`);
          if (onDone) onDone(payload.exit_code);
        }
      }
    }
  });
}

function killSlot(slot) {
  const endpoint = slot === "agent" ? "/api/agent/kill" : "/api/kill";
  return fetch(endpoint, { method: "POST" });
}

// pairs up a Start/Stop button with a command builder for long-running actions
function wireStartStop({ startBtn, stopBtn, slot, title, buildCommand, needsAgent }) {
  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    const command = await buildCommand();
    if (needsAgent) {
      await ensureAgentRunning();
    }
    stopBtn.disabled = false;
    runCommand(command, {
      slot,
      title,
      onDone: () => {
        startBtn.disabled = false;
        stopBtn.disabled = true;
      },
    });
  });
  stopBtn.addEventListener("click", () => {
    killSlot(slot);
  });
}

// ---------- workspace / ros-env prefix ----------
function envPrefix() {
  const ws = (state.config && state.config.workspace_path) || "~/linorobot2_ws";
  return `source /opt/ros/$ROS_DISTRO/setup.bash 2>/dev/null || true; ` +
         `[ -f ${ws}/install/setup.bash ] && source ${ws}/install/setup.bash; `;
}

function ws() {
  return (state.config && state.config.workspace_path) || "~/linorobot2_ws";
}

// ---------- status polling ----------
async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const s = await res.json();
    state.status = s;
    state.config = s.config;
    state.mainBusy = s.main_busy;
    state.agentBusy = s.agent_busy_console;

    document.getElementById("hdr-distro").innerHTML = `ROS: <b>${s.ros_distro || "not sourced"}</b>`;
    document.getElementById("hdr-workspace").innerHTML =
      `Workspace: <b>${s.workspace_built ? "built" : "not built"}</b>`;

    const pill = document.getElementById("hdr-agent-pill");
    const alive = s.agent_alive_external || s.agent_busy_console;
    pill.textContent = alive ? "running" : "down";
    pill.className = "pill " + (alive ? "pill-ok" : "pill-off");

    document.getElementById("btn-agent-stop").disabled = !s.agent_busy_console;

    if (!document.getElementById("install-workspace").value) {
      document.getElementById("install-workspace").value = s.workspace_path;
    }
    if (!document.getElementById("cfg-workspace").value) {
      document.getElementById("cfg-workspace").value = s.workspace_path;
    }
    if (s.config) {
      const c = s.config;
      const setIfEmpty = (id, val) => {
        const el = document.getElementById(id);
        if (el && !el.value) el.value = val;
      };
      document.getElementById("cfg-agent-transport").value = c.agent_transport;
      setIfEmpty("cfg-agent-device", c.agent_device);
      setIfEmpty("cfg-agent-port", c.agent_port);
      setIfEmpty("cfg-agent-baud", c.agent_baud);
    }
  } catch (e) {
    // server not reachable yet / transient -- ignore, next poll will retry
  }
}
setInterval(refreshStatus, 4000);
refreshStatus();

// ---------- sensors dropdowns ----------
fetch("/api/sensors").then((r) => r.json()).then((data) => {
  const laserSel = document.getElementById("install-laser");
  Object.entries(data.laser).forEach(([key, label]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = label;
    laserSel.appendChild(opt);
  });
  const depthSel = document.getElementById("install-depth");
  Object.entries(data.depth).forEach(([key, label]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = label;
    depthSel.appendChild(opt);
  });
});

// Bringup's LINOROBOT2_LASER_SENSOR/DEPTH_SENSOR select the sensor model by
// name only -- these are the actual `sensor` launch-arg choices declared in
// linorobot2_bringup/launch/lasers.launch.py and the depth_topics dict in
// sensors.launch.py, which is a finer-grained list than the Install tab's
// driver-package groupings above (e.g. one "sllidar" install covers seven
// distinct a1/a2/.../s3 model codes here).
const BRINGUP_LASER_MODELS = ["ydlidar", "xv11", "ld06", "ld19", "stl27l", "a1", "a2", "a3", "c1", "s1", "s2", "s3"];
const BRINGUP_DEPTH_MODELS = ["realsense", "astra", "zed", "zed2", "zed2i", "zedm", "oakd", "oakdlite", "oakdpro"];
(function populateBringupSensorSelects() {
  const laserSel = document.getElementById("bringup-laser-sensor");
  BRINGUP_LASER_MODELS.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    laserSel.appendChild(opt);
  });
  const depthSel = document.getElementById("bringup-depth-sensor");
  BRINGUP_DEPTH_MODELS.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    depthSel.appendChild(opt);
  });
})();

// ---------- import config ----------
document.getElementById("btn-import").addEventListener("click", async () => {
  const path = document.getElementById("import-path").value.trim();
  if (!path) return;
  const res = await fetch("/api/import_config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const data = await res.json();
  const resultEl = document.getElementById("import-result");
  if (data.error) {
    resultEl.textContent = data.error;
    return;
  }
  if (data.base) document.getElementById("install-base").value = data.base;
  if (data.transport) document.getElementById("cfg-agent-transport").value = data.transport;
  if (data.agent_baud) document.getElementById("cfg-agent-baud").value = data.agent_baud;
  if (data.agent_ip) document.getElementById("cfg-agent-device").placeholder = data.agent_ip;
  resultEl.textContent =
    `Imported: base=${data.base || "?"} transport=${data.transport} ` +
    `has_imu=${data.has_imu} has_mag=${data.has_mag}` +
    (data.mag_bias ? ` mag_bias=[${data.mag_bias.join(", ")}]` : "");
});

// ---------- install actions ----------
document.getElementById("btn-install-base").addEventListener("click", () => {
  const workspace = document.getElementById("install-workspace").value.trim() || ws();
  const cmd = [
    `mkdir -p ${workspace}/src`,
    `cd ${workspace}/src`,
    `[ -d linorobot2 ] || git clone -b $ROS_DISTRO https://github.com/linorobot/linorobot2 linorobot2 || git clone https://github.com/linorobot/linorobot2 linorobot2`,
    `touch linorobot2/linorobot2_gazebo/COLCON_IGNORE`,
    `cd ${workspace}`,
    `rosdep update`,
    `rosdep install --from-paths src --ignore-src -y --skip-keys microxrcedds_agent`,
    `colcon build --symlink-install`,
  ].join(" && ");
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_path: workspace }),
  });
  runCommand(envPrefix() + cmd, { title: "Base install" });
});

// Sensor command tables mirrored from server.py's LASER_SENSORS/DEPTH_SENSORS
// data (kept here too so the client can build the exact command string, same
// division of responsibility as config-engine: client builds commands).
const LASER_CMDS = {
  ydlidar: {
    install: [
      "cd /tmp", "rm -rf YDLidar-SDK",
      "git clone https://github.com/YDLIDAR/YDLidar-SDK.git",
      "mkdir -p YDLidar-SDK/build && cd YDLidar-SDK/build",
      "cmake .. && make", "sudo make install",
      "cd {ws}",
      "[ -d src/ydlidar_ros2_driver ] || git clone https://github.com/YDLIDAR/ydlidar_ros2_driver src/ydlidar_ros2_driver",
      "chmod 0777 src/ydlidar_ros2_driver/startup/*",
      "colcon build --symlink-install",
    ],
    udev: [
      `echo 'KERNEL=="ttyUSB*", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE:="0666", GROUP:="dialout", SYMLINK+="ydlidar"' | sudo tee /etc/udev/rules.d/ydlidar.rules`,
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
  xv11: {
    install: ["cd {ws}", "[ -d src/xv_11_driver ] || git clone https://github.com/mjstn/xv_11_driver src/xv_11_driver", "colcon build"],
    udev: null,
  },
  ldlidar: {
    install: ["cd {ws}", "[ -d src/ldlidar_stl_ros2 ] || git clone https://github.com/hippo5329/ldlidar_stl_ros2.git src/ldlidar_stl_ros2", "colcon build"],
    udev: [
      "cd /tmp && wget -q https://raw.githubusercontent.com/linorobot/ldlidar/ros2/ldlidar.rules",
      "sudo cp ldlidar.rules /etc/udev/rules.d",
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
  sllidar: {
    install: ["cd {ws}", "[ -d src/sllidar_ros2 ] || git clone https://github.com/Slamtec/sllidar_ros2.git src/sllidar_ros2", "colcon build"],
    udev: [
      "sudo cp {ws}/src/sllidar_ros2/scripts/rplidar.rules /etc/udev/rules.d",
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
};

const DEPTH_CMDS = {
  realsense: {
    install: ["sudo apt-get install -y ros-$ROS_DISTRO-realsense2-camera"],
    udev: [
      "cd /tmp && wget -q https://raw.githubusercontent.com/IntelRealSense/librealsense/master/config/99-realsense-libusb.rules",
      "sudo cp 99-realsense-libusb.rules /etc/udev/rules.d",
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
  oakd: {
    install: ["sudo apt-get install -y ros-$ROS_DISTRO-depthai-ros"],
    udev: [
      `echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | sudo tee /etc/udev/rules.d/80-movidius.rules`,
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
  astra: {
    install: [
      "sudo apt-get install -y libuvc-dev libopenni2-dev", "cd {ws}",
      "[ -d src/ros_astra_camera ] || git clone https://github.com/linorobot/ros_astra_camera src/ros_astra_camera",
      "colcon build",
    ],
    udev: [
      "sudo cp {ws}/src/ros_astra_camera/56-orbbec-usb.rules /etc/udev/rules.d/",
      "sudo udevadm control --reload-rules && sudo udevadm trigger",
    ],
  },
};

function buildSensorCommand(table, key, skipUdev) {
  const entry = table[key];
  if (!entry) return null;
  let steps = entry.install.slice();
  if (!skipUdev && entry.udev) steps = steps.concat(entry.udev);
  return steps.map((s) => s.replaceAll("{ws}", ws())).join(" && ");
}

function buildUdevOnlyCommand(table, key) {
  const entry = table[key];
  if (!entry || !entry.udev) return null;
  return entry.udev.map((s) => s.replaceAll("{ws}", ws())).join(" && ");
}

document.getElementById("btn-install-laser").addEventListener("click", () => {
  const key = document.getElementById("install-laser").value;
  if (!key) return;
  const skip = document.getElementById("laser-skip-udev").checked;
  const cmd = buildSensorCommand(LASER_CMDS, key, skip);
  runCommand(envPrefix() + `cd ${ws()} && ` + cmd, { title: `Install laser: ${key}` });
});

document.getElementById("btn-install-depth").addEventListener("click", () => {
  const key = document.getElementById("install-depth").value;
  if (!key) return;
  const skip = document.getElementById("depth-skip-udev").checked;
  const cmd = buildSensorCommand(DEPTH_CMDS, key, skip);
  runCommand(envPrefix() + `cd ${ws()} && ` + cmd, { title: `Install depth camera: ${key}` });
});

// ---------- Docker / Podman install mode ----------
// linorobot2 ships its own docker/docker-compose.yaml + Dockerfile that need
// no ROS install on this host at all -- sensor drivers install *inside* the
// image via the Dockerfile's own `bash install.bash ...` step (that's
// linorobot2's documented build process, not something Console runs on the
// host, so it doesn't conflict with the "no install.bash on the host" rule
// the native install path follows).
const installModeSel = document.getElementById("install-mode");
installModeSel.addEventListener("change", () => {
  const isNative = installModeSel.value === "native";
  document.getElementById("install-native-cards").style.display = isNative ? "block" : "none";
  document.getElementById("install-docker-card").style.display = isNative ? "none" : "block";
});

function dockerDir() {
  return `${ws()}/src/linorobot2/docker`;
}

// Resolved at command-run time (not build time) since we can't be sure which
// of `podman compose` (the compose plugin) or the standalone `podman-compose`
// tool is actually installed -- docker itself only has one real option.
function composeResolveSnippet() {
  if (installModeSel.value === "podman") {
    return `if command -v podman-compose >/dev/null 2>&1; then COMPOSE="podman-compose"; else COMPOSE="podman compose"; fi; `;
  }
  return `COMPOSE="docker compose"; `;
}

// Docker/Podman's own LASER_SENSOR/DEPTH_SENSOR values (docker/.env.example)
// are a coarser set than lasers.launch.py's `sensor` choices, and use
// slightly different names for the same hardware (e.g. "rplidar" instead of
// per-model a1/a2/.../s3) -- this maps each to the matching key in this
// file's own LASER_CMDS/DEPTH_CMDS tables, for the *udev-rules-only* step
// below (driver install itself happens inside the image, not on the host).
const DOCKER_LASER_TO_NATIVE_KEY = { ldlidar: "ldlidar", rplidar: "sllidar", ydlidar: "ydlidar", xv11: "xv11" };
const DOCKER_DEPTH_TO_NATIVE_KEY = { realsense: "realsense" }; // zed/zedm/zed2/zed2i: no native udev entry (ZED SDK-managed)

function cloneLinorobot2Command() {
  const workspace = document.getElementById("install-workspace").value.trim() || ws();
  return [
    `mkdir -p ${workspace}/src`,
    `cd ${workspace}/src`,
    `[ -d linorobot2 ] || git clone -b $ROS_DISTRO https://github.com/linorobot/linorobot2 linorobot2 || git clone https://github.com/linorobot/linorobot2 linorobot2`,
  ].join(" && ");
}

document.getElementById("btn-docker-build").addEventListener("click", () => {
  const baseImage = document.getElementById("docker-base-image").value;
  const robotBase = document.getElementById("install-base").value;
  const laser = document.getElementById("docker-laser-sensor").value;
  const depth = document.getElementById("docker-depth-sensor").value;
  const serialPort = document.getElementById("docker-base-serial-port").value.trim() || "/dev/ttyACM0";
  const domainId = document.getElementById("docker-ros-domain-id").value.trim() || "0";
  const gpuId = document.getElementById("docker-gpu-id").value.trim() || "0";
  const distro = (state.status && state.status.ros_distro) || "jazzy";

  const envBody =
    `DOCKER_ROS_DISTRO=${distro}\n` +
    `BASE_IMAGE=${baseImage}\n` +
    `ROBOT_BASE=${robotBase}\n` +
    `LASER_SENSOR=${laser}\n` +
    `DEPTH_SENSOR=${depth}\n` +
    `BASE_SERIAL_PORT=${serialPort}\n` +
    `ODOM_TOPIC=/odom\n` +
    `ROS_DOMAIN_ID=${domainId}\n` +
    `CUSTOM_ROBOT=false\n` +
    `LAUNCH_EXTRA=false\n` +
    `LAUNCH_JOYSTICK=false\n` +
    `GPU_ID=${gpuId}\n` +
    `VIRTUALGL_VER=3.1.4\n`;

  // Only the two device mappings docs/docker.md itself documents as a
  // required manual step for the `bringup` service -- an override file
  // (docker compose auto-merges *.override.yaml) so the vendored
  // docker-compose.yaml is never edited in place.
  const laserDevice = { ldlidar: "/dev/ldlidar", rplidar: "/dev/rplidar", ydlidar: "/dev/ydlidar" }[laser];
  const deviceLines = [`      - ${serialPort}:${serialPort}`];
  if (laserDevice) deviceLines.push(`      - ${laserDevice}:${laserDevice}`);
  const overrideBody =
    `services:\n  bringup:\n    devices:\n${deviceLines.join("\n")}\n`;

  const dir = dockerDir();
  // Steps are newline-joined, not `&&`-joined: a heredoc's closing delimiter
  // must be alone on its own line, so anything appended right after it on
  // the SAME line (like " && next-command") is never recognized as the
  // terminator -- bash just keeps reading everything that follows as more
  // heredoc body, silently swallowing every later step. `set -e` keeps the
  // fail-fast behavior `&&` would have given.
  const cmd = "set -e\n" + [
    cloneLinorobot2Command(),
    `mkdir -p ${dir}`,
    `cat > ${dir}/.env << 'CONSOLE_DOCKER_ENV_EOF'\n${envBody}CONSOLE_DOCKER_ENV_EOF`,
    `cat > ${dir}/docker-compose.override.yaml << 'CONSOLE_DOCKER_OVERRIDE_EOF'\n${overrideBody}CONSOLE_DOCKER_OVERRIDE_EOF`,
    `cd ${dir}`,
    `${composeResolveSnippet()}HOST_UID=$(id -u) HOST_GID=$(id -g) $COMPOSE build`,
  ].join("\n");
  runCommand(cmd, { title: `Docker/Podman build (${baseImage})` });
});

document.getElementById("btn-docker-udev").addEventListener("click", () => {
  const laser = document.getElementById("docker-laser-sensor").value;
  const depth = document.getElementById("docker-depth-sensor").value;
  const cmds = [];
  const laserKey = DOCKER_LASER_TO_NATIVE_KEY[laser];
  if (laserKey) {
    const c = buildUdevOnlyCommand(LASER_CMDS, laserKey);
    if (c) cmds.push(c);
    else logLine(`[console] "${laser}" has no persistent udev symlink available -- it'll enumerate as a plain /dev/ttyUSBx or /dev/ttyACMx.`);
  } else if (laser) {
    logLine(`[console] no native udev rule available for laser sensor "${laser}" -- check its own driver docs.`);
  }
  const depthKey = DOCKER_DEPTH_TO_NATIVE_KEY[depth];
  if (depthKey) {
    const c = buildUdevOnlyCommand(DEPTH_CMDS, depthKey);
    if (c) cmds.push(c);
    else logLine(`[console] "${depth}" has no udev rule to install.`);
  } else if (depth) {
    logLine(`[console] no native udev rule available for depth sensor "${depth}" -- check its own driver docs (e.g. ZED SDK).`);
  }
  if (!cmds.length) return;
  runCommand(envPrefix() + cmds.join(" && "), { title: "Install udev rules (host)" });
});

const btnDockerServiceStart = document.getElementById("btn-docker-service-start");
const btnDockerServiceStop = document.getElementById("btn-docker-service-stop");
btnDockerServiceStart.addEventListener("click", () => {
  const service = document.getElementById("docker-service").value;
  // linorobot2's own Tmuxinator profiles (docker/profiles/*.yml) always
  // `export DISPLAY=:200` before `docker compose up` -- GUI services
  // (gazebo, rviz, rviz-nav, slam/navigate with rviz:=true) render into that
  // virtual display, which the kasmvnc service then streams to a browser.
  // Skipping it isn't just "no picture" -- gz sim's GUI process crashes
  // outright trying to open an unset/invalid display.
  const cmd = `${composeResolveSnippet()}cd ${dockerDir()} && DISPLAY=:200 $COMPOSE up ${service}`;
  btnDockerServiceStart.disabled = true;
  btnDockerServiceStop.disabled = false;
  runCommand(cmd, {
    title: `Docker/Podman service: ${service}`,
    onDone: () => {
      btnDockerServiceStart.disabled = false;
      btnDockerServiceStop.disabled = true;
    },
  });
});
btnDockerServiceStop.addEventListener("click", () => killSlot("main"));

const vncBtn = document.getElementById("btn-open-vnc");
if (vncBtn) {
  const host = window.location.hostname || "localhost";
  vncBtn.href = `http://${host}:3000/`;
}

document.getElementById("btn-docker-down").addEventListener("click", () => {
  const cmd = `${composeResolveSnippet()}cd ${dockerDir()} && $COMPOSE down`;
  runCommand(cmd, { title: "Docker/Podman: stop + remove all containers" });
});

// ---------- micro-ROS agent: find-or-build, then launch ----------
function findOrBuildAgentCommand() {
  const isDocker = document.getElementById("cfg-agent-use-docker") ? document.getElementById("cfg-agent-use-docker").checked : (installModeSel?.value !== "native");
  if (isDocker) {
    const engine = (installModeSel?.value === "podman") ? "podman" : "docker";
    return `echo ">>> micro-ROS agent: using ${engine} container image (skipping build from source)"; ` +
      `if ! command -v ${engine} >/dev/null 2>&1; then echo "ERROR: ${engine} is not installed" >&2; exit 1; fi; ` +
      `IMG="microros/micro-ros-agent:${state.status?.ros_distro || "jazzy"}"; ` +
      `echo ">>> Pulling $IMG..."; ` +
      `${engine} pull "$IMG" 2>/dev/null || { echo ">>> no '$IMG' tag on Docker Hub, trying ':rolling'"; IMG="microros/micro-ros-agent:rolling"; ${engine} pull "$IMG" 2>/dev/null || true; }; ` +
      `echo AGENT_DOCKER_READY`;
  }
  return envPrefix() + [
    `[ -f ~/uros_ws/install/setup.bash ] && source ~/uros_ws/install/setup.bash`,
    `if ros2 pkg prefix micro_ros_agent >/dev/null 2>&1; then echo AGENT_FOUND; ` +
      `else ` +
        `sudo apt-get install -y ros-$ROS_DISTRO-micro-ros-agent >/dev/null 2>&1; ` +
        `source /opt/ros/$ROS_DISTRO/setup.bash 2>/dev/null; ` +
        `if ros2 pkg prefix micro_ros_agent >/dev/null 2>&1; then echo AGENT_APT_OK; ` +
        `else ` +
          `mkdir -p ~/uros_ws/src && cd ~/uros_ws/src && ` +
          `{ [ -d micro_ros_agent ] || git clone -b $ROS_DISTRO https://github.com/micro-ROS/micro-ROS-Agent.git micro_ros_agent || git clone -b rolling https://github.com/micro-ROS/micro-ROS-Agent.git micro_ros_agent; } && ` +
          `{ [ -d micro_ros_msgs ] || git clone -b $ROS_DISTRO https://github.com/micro-ROS/micro_ros_msgs.git micro_ros_msgs || git clone -b rolling https://github.com/micro-ROS/micro_ros_msgs.git micro_ros_msgs; } && ` +
          `cd ~/uros_ws && colcon build && echo AGENT_BUILT; ` +
        `fi; ` +
      `fi`,
  ].join("; ");
}

function agentLaunchCommand() {
  const c = state.config || {};
  const transport = document.getElementById("cfg-agent-transport").value || c.agent_transport || "serial";
  const device = document.getElementById("cfg-agent-device").value || c.agent_device || "/dev/ttyUSB0";
  const port = document.getElementById("cfg-agent-port").value || c.agent_port || "8888";
  const baud = document.getElementById("cfg-agent-baud").value || c.agent_baud || "921600";
  const isDocker = document.getElementById("cfg-agent-use-docker") ? document.getElementById("cfg-agent-use-docker").checked : (installModeSel?.value !== "native");

  if (isDocker) {
    const engine = (installModeSel?.value === "podman") ? "podman" : "docker";
    const devFlags = transport === "udp4" ? "" : `--device ${device}`;
    const agentArgs = transport === "udp4"
      ? `udp4 --port ${port}`
      : `serial --dev ${device} -b ${baud}`;
    return `${engine} run --rm --net=host --privileged -v /dev:/dev ${devFlags} -e ROS_DOMAIN_ID=0 microros/micro-ros-agent:${state.status?.ros_distro || "jazzy"} ${agentArgs}`;
  }
  const runLine = transport === "udp4"
    ? `ros2 run micro_ros_agent micro_ros_agent udp4 -p ${port}`
    : `ros2 run micro_ros_agent micro_ros_agent serial --dev ${device} -b ${baud}`;
  return envPrefix() + `[ -f ~/uros_ws/install/setup.bash ] && source ~/uros_ws/install/setup.bash; ` + runLine;
}

function ensureAgentRunning() {
  if (state.status && (state.status.agent_alive_external || state.status.agent_busy_console)) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    runCommand(findOrBuildAgentCommand(), {
      title: "Preparing micro-ROS agent",
      onDone: (code) => {
        if (code !== 0) {
          resolve();
          return;
        }
        document.getElementById("btn-agent-stop").disabled = false;
        runCommand(agentLaunchCommand(), { slot: "agent", title: "micro-ROS agent" });
        setTimeout(resolve, 2500); // give the agent a moment to bind before the caller launches
      },
    });
  });
}

document.getElementById("btn-agent-ensure").addEventListener("click", () => ensureAgentRunning());
document.getElementById("btn-agent-stop").addEventListener("click", () => killSlot("agent"));

// ---------- bringup ----------
// bringup.launch.py -> default_robot.launch.py already starts its own
// micro_ros_agent Node internally (when custom_robot is left at its default
// "false"), using exactly these base_serial_port/micro_ros_transport/
// micro_ros_port args -- so Bringup must NOT also go through
// ensureAgentRunning()/the separate agent slot, or two agents would fight
// over the same serial device or UDP port.
wireStartStop({
  startBtn: document.getElementById("btn-bringup-start"),
  stopBtn: document.getElementById("btn-bringup-stop"),
  slot: "main",
  title: "Bringup",
  buildCommand: async () => {
    const c = state.config || {};
    const laser = document.getElementById("bringup-laser-sensor").value;
    const depth = document.getElementById("bringup-depth-sensor").value;
    const envs = `export LINOROBOT2_LASER_SENSOR="${laser}"; export LINOROBOT2_DEPTH_SENSOR="${depth}"; `;
    const transportArgs = c.agent_transport === "udp4"
      ? `micro_ros_transport:=udp4 micro_ros_port:=${c.agent_port}`
      : `micro_ros_transport:=serial base_serial_port:=${c.agent_device}`;
    return envPrefix() + envs + `ros2 launch linorobot2_bringup bringup.launch.py ${transportArgs}`;
  },
});

// ---------- teleop ----------
// Teleop/SLAM/Navigation all assume Bringup (with its own agent) is already
// running in another Console tab/session -- same two-terminal convention
// linorobot2 itself uses. They don't launch or need a standalone agent.
wireStartStop({
  startBtn: document.getElementById("btn-teleop-start"),
  stopBtn: document.getElementById("btn-teleop-stop"),
  slot: "main",
  title: "Gamepad teleop",
  buildCommand: async () => {
    const axisLinear = document.getElementById("joy-axis-linear").value || 1;
    const scaleLinear = document.getElementById("joy-scale-linear").value || 0.5;
    const axisAngular = document.getElementById("joy-axis-angular").value || 0;
    const scaleAngular = document.getElementById("joy-scale-angular").value || 1.0;
    const yamlBody =
      `teleop_twist_joy_node:\n  ros__parameters:\n` +
      `    axis_linear:\n      x: ${axisLinear}\n` +
      `    scale_linear:\n      x: ${scaleLinear}\n` +
      `    axis_angular:\n      yaw: ${axisAngular}\n` +
      `    scale_angular:\n      yaw: ${scaleAngular}\n`;
    const tmpFile = "/tmp/linorobot2_console_joy.yaml";
    // The heredoc terminator must be alone on its own line -- appending
    // " && (...)" right after it on the same line means bash never
    // recognizes it as the terminator and keeps consuming everything after
    // it (including the ros2 run commands) as more heredoc body instead of
    // running them. A real newline before the next statement fixes it.
    const writeYaml = `cat > ${tmpFile} << 'CONSOLE_JOY_EOF'\n${yamlBody}CONSOLE_JOY_EOF`;
    return envPrefix() + writeYaml + "\n" +
      `(ros2 run joy_linux joy_linux_node & ` +
      `ros2 run teleop_twist_joy teleop_node --ros-args --params-file ${tmpFile}; wait)`;
  },
});

// ---------- SLAM / navigation ----------
wireStartStop({
  startBtn: document.getElementById("btn-slam-start"),
  stopBtn: document.getElementById("btn-slam-stop"),
  slot: "main",
  title: "SLAM",
  buildCommand: async () => envPrefix() + "ros2 launch linorobot2_navigation slam.launch.py",
});

document.getElementById("btn-map-save").addEventListener("click", () => {
  const name = document.getElementById("map-save-name").value.trim();
  if (!name) return;
  const mapsDir = `${ws()}/src/linorobot2/linorobot2_navigation/maps`;
  runCommand(
    envPrefix() + `mkdir -p ${mapsDir} && ros2 run nav2_map_server map_saver_cli -f ${mapsDir}/${name}`,
    { title: `Save map: ${name}`, onDone: refreshMaps }
  );
});

function refreshMaps() {
  fetch("/api/maps").then((r) => r.json()).then((data) => {
    const sel = document.getElementById("nav-map-select");
    sel.innerHTML = "";
    data.maps.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = `${data.maps_dir}/${m}.yaml`;
      opt.textContent = m;
      sel.appendChild(opt);
    });
  });
}
document.getElementById("btn-refresh-maps").addEventListener("click", refreshMaps);
refreshMaps();

wireStartStop({
  startBtn: document.getElementById("btn-nav-start"),
  stopBtn: document.getElementById("btn-nav-stop"),
  slot: "main",
  title: "Navigation",
  buildCommand: async () => {
    const mapPath = document.getElementById("nav-map-select").value;
    const mapArg = mapPath ? ` map:=${mapPath}` : "";
    const paramsFile = document.getElementById("nav-params-file").value.trim();
    if (paramsFile) {
      // linorobot2_navigation's own launch file hardcodes params_file to its
      // bundled config/navigation.yaml (not a LaunchConfiguration -- there's
      // no argument that would override it), so a custom/newer params file
      // means going straight to nav2_bringup instead of through that wrapper.
      return envPrefix() +
        `ros2 launch nav2_bringup bringup_launch.py${mapArg} params_file:=${paramsFile} use_sim_time:=false`;
    }
    return envPrefix() + `ros2 launch linorobot2_navigation navigation.launch.py${mapArg}`;
  },
});

// ---------- RViz via noVNC (headless-friendly) ----------
// Native equivalent of the `kasmvnc` service in linorobot2's own
// docker/docker-compose.yaml: Xvfb gives rviz2 a virtual display to open,
// x11vnc exposes that display over VNC, and websockify (from the `novnc`
// package) fronts it as a plain browser page -- no native VNC client needed,
// and it works the same whether the browser is on the robot computer itself
// or a separate laptop.
const btnVncStart = document.getElementById("btn-vnc-start");
const btnVncStop = document.getElementById("btn-vnc-stop");
btnVncStart.addEventListener("click", () => {
  const display = document.getElementById("vnc-display").value.trim() || ":99";
  const novncPort = document.getElementById("vnc-novnc-port").value.trim() || "6080";
  const cmd = envPrefix() + [
    "command -v Xvfb >/dev/null 2>&1 || sudo apt-get install -y xvfb",
    "command -v x11vnc >/dev/null 2>&1 || sudo apt-get install -y x11vnc",
    "command -v websockify >/dev/null 2>&1 || sudo apt-get install -y novnc websockify",
    `pkill -f "Xvfb ${display}" 2>/dev/null; sleep 0.3`,
    `(Xvfb ${display} -screen 0 1280x800x24 &) && sleep 1`,
    `(DISPLAY=${display} rviz2 &) && sleep 1`,
    `(x11vnc -display ${display} -forever -shared -nopw -quiet -rfbport 5900 &) && sleep 1`,
    `websockify --web=/usr/share/novnc ${novncPort} localhost:5900`,
  ].join(" && ");
  btnVncStart.disabled = true;
  btnVncStop.disabled = false;
  const link = document.getElementById("vnc-link");
  link.href = `http://${location.hostname}:${novncPort}/vnc.html`;
  link.style.display = "inline";
  runCommand(cmd, {
    title: "RViz via noVNC",
    onDone: () => {
      btnVncStart.disabled = false;
      btnVncStop.disabled = true;
      link.style.display = "none";
    },
  });
});
btnVncStop.addEventListener("click", () => killSlot("main"));

// ---------- Firmware: launch config-engine (via Docker), don't reimplement it ----------
// linorobot2_hardware's own robot_config_engine already does board detection,
// header generation, PlatformIO build, and flashing -- none of that belongs
// here a second time. This just gets config-engine's own server running
// (in a plain python:3.11-slim container so PlatformIO/board toolchains
// don't need to be installed on this machine either) with the hardware repo
// mounted in and the board's USB device passed through, then links to its
// real web UI -- everything past that point happens in config-engine's own
// interface, same as running it natively.
const btnFwStart = document.getElementById("btn-fw-start");
const btnFwStop = document.getElementById("btn-fw-stop");
btnFwStart.addEventListener("click", () => {
  const hwPath = document.getElementById("fw-hardware-path").value.trim() || "~/linorobot2_hardware";
  const port = document.getElementById("fw-port").value.trim() || "8085";
  const device = document.getElementById("fw-upload-port").value.trim() || "/dev/ttyUSB0";
  const remoteHost = document.getElementById("fw-remote-host").value.trim();
  const useDocker = document.getElementById("fw-use-docker") ? document.getElementById("fw-use-docker").checked : true;

  let inner;
  if (useDocker) {
    inner = "set -e\n" + [
      `[ -d ${hwPath} ] || git clone https://github.com/linorobot/linorobot2_hardware ${hwPath}`,
      `if command -v docker >/dev/null 2>&1; then`,
      `  echo ">>> Launching robot_config_engine in Docker container on port ${port}..."`,
      `  docker run --rm -p ${port}:${port} -v ${hwPath}:/workspace -w /workspace/tools/robot_config_engine/web ` +
        `--device=${device} python:3.11-slim bash -c "apt-get update -qq && apt-get install -y -qq git build-essential cmake >/dev/null && pip install -q platformio && python3 server.py ${port}"`,
      `else`,
      `  echo ">>> Docker not found, falling back to native host Python execution on port ${port}..."`,
      `  cd ${hwPath}/tools/robot_config_engine/web && python3 server.py ${port}`,
      `fi`,
    ].join("\n");
  } else {
    inner = "set -e\n" + [
      `[ -d ${hwPath} ] || git clone https://github.com/linorobot/linorobot2_hardware ${hwPath}`,
      `echo ">>> Launching robot_config_engine natively (host/remote Python) on port ${port}..."`,
      `cd ${hwPath}/tools/robot_config_engine/web && python3 server.py ${port}`,
    ].join("\n");
  }

  // The board has to be physically attached wherever the container actually
  // runs -- `-tt` forces a pseudo-terminal so stopping this (killSlot, which
  // sends SIGTERM to the local ssh client) actually propagates to the
  // remote `docker run` instead of leaving it orphaned.
  const cmd = remoteHost ? `ssh -tt ${remoteHost} ${JSON.stringify(inner)}` : inner;

  btnFwStart.disabled = true;
  btnFwStop.disabled = false;
  const link = document.getElementById("fw-link");
  const linkHost = remoteHost ? remoteHost.split("@").pop() : location.hostname;
  link.href = `http://${linkHost}:${port}/`;
  link.style.display = "inline";
  runCommand(cmd, {
    title: remoteHost ? `config-engine (Docker, on ${remoteHost})` : "config-engine (Docker)",
    onDone: () => {
      btnFwStart.disabled = false;
      btnFwStop.disabled = true;
      link.style.display = "none";
    },
  });
});
btnFwStop.addEventListener("click", () => killSlot("main"));

// ---------- magnetometer calibration ----------
// Needs Bringup already running elsewhere (cmd_vel to spin the base, IMU/mag
// topics to read) -- a bare standalone agent wouldn't be enough, same
// reasoning as teleop/SLAM/navigation above, so this doesn't call
// ensureAgentRunning() either.
document.getElementById("btn-mag-cal").addEventListener("click", async () => {
  if (!confirm("The robot will spin in place for about a minute. Clear the area, then continue?")) return;
  const resultEl = document.getElementById("mag-cal-result");
  resultEl.textContent = "";
  const cmd = envPrefix() +
    `dpkg -s ros-$ROS_DISTRO-robot-calibration >/dev/null 2>&1 || sudo apt-get install -y ros-$ROS_DISTRO-robot-calibration; ` +
    `ros2 run robot_calibration magnetometer_calibration`;
  runCommand(cmd, {
    title: "Magnetometer calibration",
    onLine: (line) => {
      if (/mag_bias|bias_x|bias_y|bias_z/i.test(line)) {
        resultEl.textContent += line + "\n";
      }
    },
  });
});

// ---------- laser driver (standalone, independent of Bringup/agent) ----------
// Two families, per linorobot2_bringup/launch/lasers.launch.py:
// - "launch" kind: go through that file's own sensor=<model> Node, which
//   already hardcodes a persistent /dev symlink for ydlidar/rplidar (only
//   xv11 is stuck on a non-persistent /dev/ttyACM0, since that Node's
//   parameters are plain literals with no LaunchConfiguration to override).
// - "ld" kind (ld06/ld19/stl27l, the ldlidar_stl_ros2 package): that file
//   also hardcodes port_name/port_baudrate as plain literals, so getting a
//   configurable serial path/baud/UDP transport means running the node
//   directly via `ros2 run` + `--ros-args -p`, bypassing the wrapper launch
//   file entirely -- same reasoning as the Teleop tab's joy.yaml override.
const LASER_MODELS = {
  ydlidar: { kind: "launch", note: "persistent /dev/ydlidar symlink, fixed baud 128000 (from lasers.launch.py)" },
  xv11: { kind: "launch", note: "/dev/ttyACM0 -- NOT persistent, fixed baud 115200 (not overridable here)" },
  a1: { kind: "launch", note: "RPLIDAR A1 -- persistent /dev/rplidar symlink" },
  a2: { kind: "launch", note: "RPLIDAR A2 -- persistent /dev/rplidar symlink" },
  a3: { kind: "launch", note: "RPLIDAR A3 -- persistent /dev/rplidar symlink" },
  c1: { kind: "launch", note: "RPLIDAR C1 -- persistent /dev/rplidar symlink" },
  s1: { kind: "launch", note: "RPLIDAR S1 -- persistent /dev/rplidar symlink" },
  s2: { kind: "launch", note: "RPLIDAR S2 -- persistent /dev/rplidar symlink" },
  s3: { kind: "launch", note: "RPLIDAR S3 -- persistent /dev/rplidar symlink" },
  ld06: { kind: "ld", product: "LDLiDAR_LD06", bins: 456, defaultBaud: "230400" },
  ld19: { kind: "ld", product: "LDLiDAR_LD19", bins: 456, defaultBaud: "230400" },
  stl27l: { kind: "ld", product: "LDLiDAR_STL27L", bins: 2160, defaultBaud: "921600" },
};

const laserModelSel = document.getElementById("laser-driver-model");
Object.keys(LASER_MODELS).forEach((key) => {
  const opt = document.createElement("option");
  opt.value = key;
  opt.textContent = key;
  laserModelSel.appendChild(opt);
});

function updateLaserDriverFieldsVisibility() {
  const model = LASER_MODELS[laserModelSel.value];
  const isLd = model.kind === "ld";
  document.getElementById("laser-driver-ld-fields").style.display = isLd ? "block" : "none";
  document.getElementById("laser-driver-simple-hint").textContent = isLd ? "" : model.note;
  if (isLd) {
    document.getElementById("laser-driver-baud").value = model.defaultBaud;
    updateLaserDriverModeVisibility();
  }
}

function updateLaserDriverModeVisibility() {
  const mode = document.getElementById("laser-driver-mode").value;
  document.getElementById("laser-driver-serial-row").style.display = mode === "serial" ? "flex" : "none";
  document.getElementById("laser-driver-udpbridge-row").style.display = mode === "udp_bridge" ? "flex" : "none";
  document.getElementById("laser-driver-netaddr-row").style.display =
    (mode === "udp_server" || mode === "udp_client") ? "flex" : "none";
}

laserModelSel.addEventListener("change", updateLaserDriverFieldsVisibility);
document.getElementById("laser-driver-mode").addEventListener("change", updateLaserDriverModeVisibility);
updateLaserDriverFieldsVisibility();

function ldNodeParams(model, overrides) {
  const base = {
    product_name: model.product,
    topic_name: "scan",
    frame_id: "laser",
    laser_scan_dir: "true",
    bins: String(model.bins),
    enable_angle_crop_func: "false",
    angle_crop_min: "135.0",
    angle_crop_max: "225.0",
  };
  Object.assign(base, overrides);
  return Object.entries(base).map(([k, v]) => `-p ${k}:=${v}`).join(" ");
}

function buildLaserDriverCommand() {
  const modelKey = laserModelSel.value;
  const model = LASER_MODELS[modelKey];
  if (model.kind === "launch") {
    return { command: envPrefix() + `ros2 launch linorobot2_bringup lasers.launch.py sensor:=${modelKey}` };
  }

  const mode = document.getElementById("laser-driver-mode").value;
  const baud = document.getElementById("laser-driver-baud").value.trim() || model.defaultBaud;
  const nodeCmd = "ros2 run ldlidar_stl_ros2 ldlidar_stl_ros2_node";

  if (mode === "serial") {
    const port = document.getElementById("laser-driver-serial-port").value.trim();
    const params = ldNodeParams(model, { comm_mode: "serial", port_name: port, port_baudrate: baud });
    return { command: envPrefix() + `${nodeCmd} --ros-args ${params}` };
  }

  if (mode === "udp_bridge") {
    // The MCU relays raw LiDAR UART bytes as UDP datagrams to this port (the
    // firmware's own "LiDAR over WiFi UDP" feature -- see LIDAR_SERVER/
    // LIDAR_PORT in config-engine). There is no ROS2-side consumer for a raw
    // byte stream like that, so socat turns it into a normal-looking local
    // serial device (a pty) that ldlidar_stl_ros2_node can just open with
    // comm_mode=serial like any USB-attached unit.
    const udpPort = document.getElementById("laser-driver-udp-port").value.trim() || "8889";
    const bridgePath = document.getElementById("laser-driver-bridge-path").value.trim() || "/dev/lidar_udp_bridge";
    const params = ldNodeParams(model, { comm_mode: "serial", port_name: bridgePath, port_baudrate: baud });
    const bridgeCmd =
      `command -v socat >/dev/null 2>&1 || sudo apt-get install -y socat; ` +
      `sudo pkill -f "socat.*${bridgePath}" 2>/dev/null; sleep 0.3; ` +
      `(socat -d -d UDP-LISTEN:${udpPort},reuseaddr PTY,link=${bridgePath},raw,echo=0,mode=666 &) && sleep 1.5`;
    return { command: envPrefix() + `${bridgeCmd} && ${nodeCmd} --ros-args ${params}` };
  }

  // udp_server / udp_client: the ldlidar_stl_ros2 driver's own native network
  // modes (talking to a network-attached LiDAR directly) -- unrelated to the
  // firmware's raw-relay feature above, offered for completeness.
  const serverIp = document.getElementById("laser-driver-server-ip").value.trim() || "0.0.0.0";
  const serverPort = document.getElementById("laser-driver-server-port").value.trim() || "8889";
  const params = ldNodeParams(model, {
    comm_mode: mode, server_ip: serverIp, server_port: serverPort, port_baudrate: baud,
  });
  return { command: envPrefix() + `${nodeCmd} --ros-args ${params}` };
}

const btnLaserStart = document.getElementById("btn-laser-driver-start");
const btnLaserStop = document.getElementById("btn-laser-driver-stop");
btnLaserStart.addEventListener("click", () => {
  const { command } = buildLaserDriverCommand();
  btnLaserStart.disabled = true;
  btnLaserStop.disabled = false;
  runCommand(command, {
    title: `Laser driver: ${laserModelSel.value}`,
    onDone: () => {
      btnLaserStart.disabled = false;
      btnLaserStop.disabled = true;
    },
  });
});
btnLaserStop.addEventListener("click", () => killSlot("main"));

// ---------- LiDAR viewer ----------
let lidarSource = null;
const lidarCanvas = document.getElementById("lidar-canvas");
const lidarCtx = lidarCanvas.getContext("2d");

function drawScan(scan) {
  const w = lidarCanvas.width, h = lidarCanvas.height;
  lidarCtx.clearRect(0, 0, w, h);
  lidarCtx.strokeStyle = "#232b3d";
  lidarCtx.beginPath();
  lidarCtx.arc(w / 2, h / 2, Math.min(w, h) / 2 - 4, 0, Math.PI * 2);
  lidarCtx.stroke();

  const ranges = scan.ranges || [];
  if (!ranges.length) return;
  const maxRange = Math.max(...ranges.filter((r) => isFinite(r) && r > 0), 1);
  const scale = (Math.min(w, h) / 2 - 8) / maxRange;

  lidarCtx.fillStyle = "#6366f1";
  ranges.forEach((r, i) => {
    if (!isFinite(r) || r <= 0) return;
    const angle = scan.angle_min + i * scan.angle_increment;
    const x = w / 2 + r * Math.cos(angle) * scale;
    const y = h / 2 - r * Math.sin(angle) * scale;
    lidarCtx.fillRect(x - 1.5, y - 1.5, 3, 3);
  });
}

document.getElementById("btn-lidar-start").addEventListener("click", () => {
  if (lidarSource) lidarSource.close();
  lidarSource = new EventSource("/api/lidar_stream");
  lidarSource.addEventListener("scan", (ev) => {
    try {
      drawScan(JSON.parse(ev.data));
    } catch {}
  });
  document.getElementById("btn-lidar-start").disabled = true;
  document.getElementById("btn-lidar-stop").disabled = false;
});
document.getElementById("btn-lidar-stop").addEventListener("click", () => {
  if (lidarSource) {
    lidarSource.close();
    lidarSource = null;
  }
  document.getElementById("btn-lidar-start").disabled = false;
  document.getElementById("btn-lidar-stop").disabled = true;
});

// ---------- settings ----------
document.getElementById("btn-save-workspace").addEventListener("click", () => {
  const workspace_path = document.getElementById("cfg-workspace").value.trim();
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_path }),
  }).then(refreshStatus);
});

document.getElementById("btn-save-agent").addEventListener("click", () => {
  const body = {
    agent_transport: document.getElementById("cfg-agent-transport").value,
    agent_device: document.getElementById("cfg-agent-device").value,
    agent_port: document.getElementById("cfg-agent-port").value,
    agent_baud: document.getElementById("cfg-agent-baud").value,
  };
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(refreshStatus);
});
