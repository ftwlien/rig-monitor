#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${HOME}/rig-monitor"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/rig-monitor"
GLOBAL_LAUNCHER="/usr/local/bin/rig-monitor"
GPU_TEMP_REPO="${HOME}/gddr6-core-junction-vram-temps"
GPU_TEMP_REPO_URL="https://github.com/ThomasBaruzier/gddr6-core-junction-vram-temps.git"

if [ ! -d "$REPO_DIR" ]; then
  echo "Expected repo at $REPO_DIR"
  echo "Clone first with: git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required"
  exit 1
fi

ensure_apt_prereqs() {
  if ! command -v apt-get >/dev/null 2>&1; then
    return 0
  fi

  local need=0
  command -v gcc >/dev/null 2>&1 || need=1
  [ -f /usr/include/pci/pci.h ] || need=1
  python3 -m pip --version >/dev/null 2>&1 || need=1
  if [ "$need" -eq 0 ]; then
    return 0
  fi

  echo "Installing rig-monitor/gputemps base prerequisites via apt..."
  sudo apt-get update
  sudo apt-get install -y build-essential pciutils libpci-dev python3-pip
}

ensure_nvml_header() {
  if [ -f /usr/include/nvml.h ] || [ -f /usr/local/cuda/include/nvml.h ]; then
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Missing nvml.h and no apt-based installer available. Install NVIDIA headers/toolkit manually."
    return 1
  fi

  echo "Installing package path for nvml.h via apt..."
  sudo apt-get update
  sudo apt-get install -y nvidia-cuda-toolkit || true

  if [ -f /usr/include/nvml.h ] || [ -f /usr/local/cuda/include/nvml.h ]; then
    return 0
  fi

  echo "nvml.h still missing after package install attempt."
  echo "Install the NVIDIA development headers/toolkit manually on this rig, then rerun the installer."
  return 1
}

ensure_apt_prereqs
ensure_nvml_header

if ! command -v gcc >/dev/null 2>&1; then
  echo "gcc is required for gputemps build"
  exit 1
fi

cd "$REPO_DIR"
python3 -m pip install --user -r requirements.txt
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
set -euo pipefail
cd "$REPO_DIR"
exec python3 app.py "$@"
LAUNCH
chmod +x "$LAUNCHER"

GLOBAL_TMP="$(mktemp)"
cat > "$GLOBAL_TMP" <<LAUNCH
#!/usr/bin/env bash
set -euo pipefail
cd "$REPO_DIR"
exec python3 app.py "$@"
LAUNCH
if [ -w /usr/local/bin ]; then
  install -m 0755 "$GLOBAL_TMP" "$GLOBAL_LAUNCHER"
else
  sudo install -m 0755 "$GLOBAL_TMP" "$GLOBAL_LAUNCHER"
fi
rm -f "$GLOBAL_TMP"

if [ ! -d "$GPU_TEMP_REPO/.git" ]; then
  git clone "$GPU_TEMP_REPO_URL" "$GPU_TEMP_REPO"
else
  git -C "$GPU_TEMP_REPO" pull --ff-only
fi

if [ ! -f "$GPU_TEMP_REPO/gputemps.c" ]; then
  echo "gputemps source missing at $GPU_TEMP_REPO"
  exit 1
fi

(
  cd "$GPU_TEMP_REPO"
  gcc -O2 -I/usr/include -I/usr/local/cuda/include -o gputemps gputemps.c -lnvidia-ml -lpci -ludev -ldl -lpthread -lm -lrt -lz
)

if [ -w /usr/local/bin ]; then
  install -m 0755 "$GPU_TEMP_REPO/gputemps" /usr/local/bin/gputemps
else
  echo "Installing /usr/local/bin/gputemps with sudo..."
  sudo install -m 0755 "$GPU_TEMP_REPO/gputemps" /usr/local/bin/gputemps
fi

RIG_USER="$(id -un)"
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
${RIG_USER} ALL=(root) NOPASSWD: /usr/local/bin/gputemps
EOF
if [ -w /etc/sudoers.d ]; then
  install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/rig-monitor-gputemps
else
  echo "Installing sudoers rule for gputemps with sudo..."
  sudo install -m 0440 "$SUDOERS_TMP" /etc/sudoers.d/rig-monitor-gputemps
fi
rm -f "$SUDOERS_TMP"

cat > "${HOME}/.gputemps-wrapper.sh" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
exec sudo /usr/local/bin/gputemps "$@"
WRAP
chmod +x "${HOME}/.gputemps-wrapper.sh"

echo "Installed rig-monitor launcher to $LAUNCHER"
echo "Installed global rig-monitor launcher to $GLOBAL_LAUNCHER"
echo "Installed gputemps to /usr/local/bin/gputemps"
echo "Installed sudoers rule: /etc/sudoers.d/rig-monitor-gputemps"
echo
if "${HOME}/.gputemps-wrapper.sh" --json --once >/dev/null 2>&1; then
  echo "gputemps probe check: OK"
else
  echo "gputemps probe check: installed, but runtime probe did not return cleanly right now"
fi

echo
echo "You can now run: rig-monitor"
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  echo "User-local launcher also installed at: $LAUNCHER"
fi
