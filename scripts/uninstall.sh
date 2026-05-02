#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${HOME}/rig-monitor"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/rig-monitor"
GLOBAL_LAUNCHER="/usr/local/bin/rig-monitor"
GPU_TEMP_REPO="${HOME}/gddr6-core-junction-vram-temps"
GPU_TEMP_BIN="/usr/local/bin/gputemps"
GPU_TEMP_WRAPPER="${HOME}/.gputemps-wrapper.sh"
SUDOERS_RULE="/etc/sudoers.d/rig-monitor-gputemps"

remove_file() {
  local path="$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    rm -f "$path"
    echo "Removed $path"
  fi
}

remove_dir() {
  local path="$1"
  if [ -d "$path" ]; then
    rm -rf "$path"
    echo "Removed $path"
  fi
}

remove_file "$LAUNCHER"
remove_file "$GPU_TEMP_WRAPPER"
remove_dir "$GPU_TEMP_REPO"

if [ -e "$GPU_TEMP_BIN" ] || [ -L "$GPU_TEMP_BIN" ]; then
  if [ -w /usr/local/bin ]; then
    rm -f "$GPU_TEMP_BIN"
  else
    sudo rm -f "$GPU_TEMP_BIN"
  fi
  echo "Removed $GPU_TEMP_BIN"
fi

if [ -e "$GLOBAL_LAUNCHER" ] || [ -L "$GLOBAL_LAUNCHER" ]; then
  if [ -w /usr/local/bin ]; then
    rm -f "$GLOBAL_LAUNCHER"
  else
    sudo rm -f "$GLOBAL_LAUNCHER"
  fi
  echo "Removed $GLOBAL_LAUNCHER"
fi

if [ -e "$SUDOERS_RULE" ] || [ -L "$SUDOERS_RULE" ]; then
  if [ -w /etc/sudoers.d ]; then
    rm -f "$SUDOERS_RULE"
  else
    sudo rm -f "$SUDOERS_RULE"
  fi
  echo "Removed $SUDOERS_RULE"
fi

echo
echo "rig-monitor uninstall complete."
echo "If you also want to remove the main repo itself, run: rm -rf $REPO_DIR"
