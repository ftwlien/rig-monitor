# Rig Monitor

A clean terminal dashboard for GPU rigs with live GPU, CPU, RAM, bandwidth, disk I/O, and process monitoring.

## Why this exists

Most rig monitoring tools only show part of the picture.

Some are good at CPU and system load.
Some are good at GPU stats.
But when you're actually operating GPU rigs, that split gets annoying fast — you end up jumping between multiple tools just to understand what one machine is doing.

`rig-monitor` exists to fix that.

The goal is simple:
- one terminal dashboard
- one glanceable view
- the important rig signals in one place

That means tracking:
- GPU utilization
- VRAM usage
- temperatures
- power draw
- CPU load
- per-core CPU activity
- RAM usage
- bandwidth up/down
- disk I/O
- active processes
- GPU-bound process activity

## Features

- Textual-based terminal UI
- Live GPU stats via NVML
- CPU + per-core monitoring
- RAM monitoring
- Bandwidth monitoring
- Disk read/write monitoring
- Top process view
- GPU process view
- Wall-mode friendly layout for tiled terminal setups

## Requirements

- Linux
- Python 3
- NVIDIA GPU drivers for GPU stats

## One-command install

Clone, install dependencies, and add a `rig-monitor` launcher:

```bash
git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor && bash ~/rig-monitor/scripts/install.sh
```

After install, you can run:

```bash
rig-monitor
```

If `~/.local/bin` is not already on your `PATH`, the installer will tell you what to add.

## Update

If `rig-monitor` is already installed:

```bash
cd ~/rig-monitor && git pull && bash scripts/install.sh
```

## Manual run

```bash
cd ~/rig-monitor && python3 app.py
```

## Controls

- `w` → toggle wall mode
- `g` → toggle compact GPU mode
- `c` → toggle shown CPU cores
- `f` → toggle denser CPU-core display

## Notes

- GPU metrics require `pynvml` / NVIDIA management support.
- If NVML is unavailable, the dashboard will still run, but GPU sections will be limited.
- Wall mode is designed for tiled / multi-panel monitoring setups where GPU visibility matters more than a noisy full process table.
