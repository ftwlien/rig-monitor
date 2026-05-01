#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${HOME}/rig-monitor"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="${BIN_DIR}/rig-monitor"

if [ ! -d "$REPO_DIR" ]; then
  echo "Expected repo at $REPO_DIR"
  echo "Clone first with: git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor"
  exit 1
fi

cd "$REPO_DIR"
python3 -m pip install --user -r requirements.txt
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<'LAUNCH'
#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/rig-monitor"
exec python3 app.py "$@"
LAUNCH
chmod +x "$LAUNCHER"

echo "Installed rig-monitor launcher to $LAUNCHER"
echo
if echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  echo "You can now run: rig-monitor"
else
  echo "$BIN_DIR is not on PATH yet."
  echo "Add this to your shell config:"
  echo 'export PATH="$HOME/.local/bin:$PATH"'
  echo "Then restart your shell or run: source ~/.bashrc"
fi
