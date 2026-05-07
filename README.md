# Rig Monitor

A clean terminal dashboard for NVIDIA GPU rigs.

Built for people running mining, Vast.ai, AI, render, or other GPU-heavy hosts where you need to know what the machine is doing **at a glance**.

`rig-monitor` shows GPU load, VRAM, temperatures, fan speed, power draw, CPU, RAM, bandwidth, disk I/O, and GPU-bound processes in one terminal UI.

---

## Why this exists

Most monitoring tools split the useful info across multiple commands:

- `nvidia-smi` for GPU stats
- `htop` for CPU/processes
- `iftop`/`nload` for bandwidth
- `iotop`/`dstat` for disk
- custom scripts for junction/VRAM temps

That gets annoying fast when you operate multiple GPU rigs.

`rig-monitor` is meant to be the one clean screen you can SSH into and leave open.

---

## What it shows

### GPU Command Center

- GPU utilization
- VRAM usage
- core temperature
- junction temperature
- VRAM temperature
- live fan speed
- power draw with load coloring
- used/total GPU memory
- active GPU processes

The wall-mode GPU card is tuned for readability:

```text
UTIL 100% ███████████████████████████████████████████
VRAM  61% ████████████████████████░░░░░░░░░░░░░░░░░░░
TEMP 74°C            Junc 101°C      Vram 62°C
FAN 100%             PWR 450W        MEM 14.7/24.0G
```

### System overview

- CPU usage and load average
- RAM usage with pressure coloring
- bandwidth up/down with load coloring
- disk read/write with separate disk-oriented thresholds
- per-core CPU activity
- top processes

---

## Features

- Textual-based terminal UI
- NVIDIA GPU stats via NVML
- optional core/junction/VRAM temperatures via `gputemps`
- clean fan display: `FAN 0% A` for auto idle, `FAN 100%` under load
- colored power draw: low/medium/high load is easy to spot
- separate network and disk color thresholds
- wall-mode layout for tiled SSH terminals
- compact GPU mode
- dense CPU-core mode
- hidden scrollbars by default for a cleaner look
- quit with `Ctrl+C` or `Ctrl+Q`

---

## Requirements

- Linux
- Python 3
- NVIDIA GPU drivers
- `git`
- `sudo` access for installing helper binaries/rules

On apt-based systems, the installer attempts to install the build/tooling dependencies needed for `gputemps`, including the package path for `nvml.h`.

---

## Install

```bash
git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor && bash ~/rig-monitor/scripts/install.sh
```

Then run:

```bash
rig-monitor
```

The installer:

- installs Python requirements
- installs a user launcher in `~/.local/bin`
- installs a global launcher at `/usr/local/bin/rig-monitor` when possible
- clones/updates `gddr6-core-junction-vram-temps`
- builds and installs `/usr/local/bin/gputemps`
- creates `~/.gputemps-wrapper.sh`
- installs a sudoers rule for clean temp reads

---

## Update

```bash
cd ~/rig-monitor && git pull && bash scripts/install.sh
```

---

## Manual run

```bash
cd ~/rig-monitor && python3 app.py
```

---

## Controls

- `w` — toggle wall mode / standard mode
- `g` — toggle compact GPU cards
- `c` — toggle shown CPU cores
- `f` — toggle dense CPU-core formatting
- `b` — toggle black mode
- `p` — toggle scrollbars
- `Ctrl+C` — quit
- `Ctrl+Q` — quit

---

## Layout behavior

`rig-monitor` is optimized for GPU rig operators, not as a generic system monitor.

The top row shows:

- CPU
- RAM
- bandwidth
- disk I/O

The main area shows:

- GPU Command Center
- CPU cores
- GPU workload/process table
- optional top-process pane in standard mode

Wall mode prioritizes GPU visibility and high-core-count CPU readability. Standard mode keeps a more traditional broader layout.

---

## Notes

- GPU metrics require NVML / NVIDIA management support.
- Junction and VRAM temperatures come from `gputemps` when available.
- If extra temperature probing is unavailable, the dashboard still runs with core GPU temperature.
- Fan speed uses NVML live fan speed.
- Idle auto fan mode is displayed as `FAN 0% A`.
- Power draw colors are tuned for large NVIDIA GPUs:
  - low = green
  - medium = cyan/yellow
  - high = red
- Network and disk colors use different thresholds because disk I/O normally scales much higher than bandwidth.

---


### Burn-test cleanup helper

If a local stress test gets suspended or leaves orphaned workers behind, run:

```bash
sudo rig-burn-cleanup
```

It lists matching `full_burn`, `ram_burn`, `stressapptest`, `gpu_burn`, `stress-ng`, and old `memtester` processes, asks you to type `KILL BURNS`, then terminates leftovers with TERM → KILL.

Use this only when you intentionally want to stop local stress tests.

## Troubleshooting

### Command not found

```bash
which rig-monitor
ls -l /usr/local/bin/rig-monitor
```

If needed, run directly:

```bash
/usr/local/bin/rig-monitor
```

Or add user-local bin to PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

### Temp helper check

```bash
~/.gputemps-wrapper.sh --json --once
```

If that prints JSON, the extra temperature helper is working.

### Update an existing install

```bash
cd ~/rig-monitor && git pull && bash scripts/install.sh
```

Do not clone again if `~/rig-monitor` already exists.

---

## Uninstall

```bash
bash ~/rig-monitor/scripts/uninstall.sh
```

This removes the launchers, temp wrapper, sudoers rule, and cloned gputemps repo.

---

## License

This project is **not MIT licensed**.

It is source-available for personal, educational, hobby, research, and other non-commercial use under the **FTWLIEN Non-Commercial License v1.0** in [`LICENSE`](LICENSE).

Commercial use is prohibited without prior written permission from the copyright holder. That includes hosting, resale, paid services, integration into commercial products or workflows, internal business use, or use by companies to support commercial GPU, AI, cloud, hosting, compute, or Vast.ai infrastructure.

Businesses and commercial users need a separate written commercial license. See [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).
