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
- GPU core / junction / VRAM temperature support via `gputemps`
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
- `git`
- `sudo` access for installing `/usr/local/bin/gputemps`
- `sudo` access for installing `/etc/sudoers.d/rig-monitor-gputemps`
- on apt-based rigs, the installer will attempt to install build/tooling deps automatically, including the package path needed for `nvml.h`

## One-command install

Clone, install dependencies, build/install `gputemps`, and add a `rig-monitor` launcher:

```bash
git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor && bash ~/rig-monitor/scripts/install.sh
```

What the installer now does:
- installs Python requirements for `rig-monitor`
- installs the `rig-monitor` launcher
- clones/updates `gddr6-core-junction-vram-temps`
- builds `gputemps`
- installs `gputemps` to `/usr/local/bin/gputemps`
- installs a sudoers rule so `rig-monitor` can run `gputemps` without prompting
- creates a local wrapper used by `rig-monitor` for clean temp reads
- attempts to install the package path needed for `nvml.h` automatically on apt-based rigs

After install, you can run:

```bash
rig-monitor
```

The installer places a user-local launcher in `~/.local/bin` and also attempts to install a global launcher at `/usr/local/bin/rig-monitor` so the command works immediately after install.

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

- `w` → toggle **wall mode** / **standard mode**
  - wall mode hides the right-side top-process pane by default and prioritizes GPU + core visibility
  - standard mode brings back the more traditional wider layout
- `g` → toggle **compact GPU cards**
  - useful if you want denser GPU rows
- `c` → toggle **CPU core display density / shown cores mode**
  - use this when you want fewer or more visible core rows depending on terminal size
- `f` → toggle **dense CPU-core formatting**
  - packs CPU core info tighter for high-core-count rigs
- `b` → toggle **black mode**
  - optional darker/stripped look
  - default remains the classic boxed monitor chrome
- `p` → toggle **scrollbars**
  - scrollbars are hidden by default
  - press `p` when you want them visible
  - works independently of black mode

## Current layout behavior

- The dashboard is built for GPU rig operators, not as a generic system monitor.
- GPU visibility is the priority, especially in tiled/wall use.
- The top row shows:
  - CPU
  - RAM
  - BANDWIDTH
  - DISK I/O
- The lower area shows:
  - GPU COMMAND CENTER
  - CPU CORES
  - optional TOP PROCESSES pane in standard mode
- Scrolling is supported in:
  - CPU CORES
  - GPU COMMAND CENTER
- In compact/tiny views, labels may shorten to preserve readability.
- In standard/full-width views, the richer top-card layout is preserved.
- The `w` toggle should only affect the lower layout focus, not randomly restyle the top row.

## Notes

- GPU metrics require `pynvml` / NVIDIA management support.
- Extra GPU temperature fields (`junction`, `vram`) come from `gputemps` when available.
- In the GPU cards, junction (`J`) and VRAM (`V`) temps are shown beside the current core temp.
- If NVML is unavailable, the dashboard will still run, but GPU sections will be limited.
- Wall mode is designed for tiled / multi-panel monitoring setups where GPU visibility matters more than a noisy full process table.
- If your shell cannot find `rig-monitor` after install, add `~/.local/bin` to your `PATH`.

Use:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

## If `rig-monitor` doesn't run

Try these in order:

### 1. Update and rerun install

```bash
cd ~/rig-monitor && git pull && bash scripts/install.sh
```

### 2. Check the global launcher

```bash
which rig-monitor
ls -l /usr/local/bin/rig-monitor
```

If the command still isn't found, try running it directly:

```bash
/usr/local/bin/rig-monitor
```

### 3. Check the temp wrapper

```bash
~/.gputemps-wrapper.sh --json --once
```

If that prints JSON, the temp helper path is working.

### 4. If the repo already exists

Don't clone again. Use:

```bash
cd ~/rig-monitor && git pull && bash scripts/install.sh
```

Instead of:

```bash
git clone https://github.com/ftwlien/rig-monitor.git ~/rig-monitor
```

## Uninstall

To remove rig-monitor, its launchers, the gputemps wrapper, the sudoers rule, and the cloned gputemps repo:

```bash
bash ~/rig-monitor/scripts/uninstall.sh
```
