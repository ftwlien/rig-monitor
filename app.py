import json
import os
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List

import psutil
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static
from textual.binding import Binding

try:
    import pynvml  # type: ignore
    pynvml.nvmlInit()
    NVML_OK = True
except Exception:
    NVML_OK = False

SPARKS = "▁▂▃▄▅▆▇█"


def sparkline(values: List[float], max_value: float | None = None, width: int | None = None) -> str:
    if not values:
        return ""
    seq = values[-width:] if width else values
    peak = max_value if max_value is not None else max(seq) or 1.0
    peak = max(peak, 1e-9)
    out = []
    for v in seq:
        idx = int((v / peak) * (len(SPARKS) - 1))
        idx = max(0, min(idx, len(SPARKS) - 1))
        out.append(SPARKS[idx])
    return "".join(out)


def bar(value: float, total: float, width: int = 22) -> str:
    if total <= 0:
        total = 1
    frac = max(0.0, min(1.0, value / total))
    fill = int(width * frac)
    return "█" * fill + "░" * (width - fill)


def truncate_middle(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    keep = max_len - 3
    left = keep // 2
    right = keep - left
    return f"{text[:left]}...{text[-right:]}"


def strip_rich_markup(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", text)


def pad_rich_right(text: str, width: int) -> str:
    visible_len = len(strip_rich_markup(text))
    return text + (" " * max(0, width - visible_len))


def format_rate(mbps: float) -> str:
    if mbps >= 1024:
        return f"{mbps / 1024:.2f} GB/s"
    if mbps >= 1:
        return f"{mbps:.2f} MB/s"
    kbps = mbps * 1024
    if kbps >= 1:
        return f"{kbps:.1f} KB/s"
    return f"{kbps * 1024:.0f} B/s"


def get_cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(["lscpu"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if line.startswith("Model name:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return os.uname().machine


def short_cpu_label(name: str) -> str:
    upper = name.upper()
    for token in ["9950X", "7950X", "5955WX", "EPYC", "3990X", "3960X", "3970X"]:
        if token in upper:
            return token
    cleaned = name.replace("AMD", "").replace("Ryzen", "").replace("Threadripper", "").replace("Processor", "").strip()
    return truncate_middle(cleaned or name, 12)


def color_for_pct(value: float) -> str:
    if value >= 90:
        return "red"
    if value >= 70:
        return "yellow"
    if value >= 40:
        return "cyan"
    return "green"


def color_for_temp(value: int | float | None, warm: int = 65, hot: int = 80) -> str:
    if value is None:
        return "white"
    if value >= hot:
        return "red"
    if value >= warm:
        return "yellow"
    return "green"


def color_for_fan(value: int | float | None) -> str:
    if value is None:
        return "white"
    if value >= 90:
        return "red"
    if value >= 70:
        return "yellow"
    if value >= 40:
        return "cyan"
    return "green"


def color_for_net_rate(mbps: float) -> str:
    if mbps >= 500:
        return "red"
    if mbps >= 100:
        return "yellow"
    if mbps >= 10:
        return "cyan"
    return "green"


def color_for_disk_rate(mbps: float) -> str:
    if mbps >= 1500:
        return "red"
    if mbps >= 500:
        return "yellow"
    if mbps >= 100:
        return "cyan"
    return "green"


def color_for_power_watts(watts: float) -> str:
    if watts >= 400:
        return "red"
    if watts >= 250:
        return "yellow"
    if watts >= 100:
        return "cyan"
    return "green"


def color_for_load(load_value: float, cpu_count: int) -> str:
    if cpu_count <= 0:
        cpu_count = 1
    pct = (load_value / cpu_count) * 100.0
    return color_for_pct(pct)




def get_gpu_average_fan_pct(handle) -> int | None:
    try:
        return int(pynvml.nvmlDeviceGetFanSpeed(handle))
    except Exception:
        return None

def heat_sparkline(values: List[float], width: int | None = None) -> str:
    if not values:
        return ""
    seq = values[-width:] if width else values
    out = []
    for v in seq:
        ch = sparkline([v], 100, 1) or "▁"
        color = color_for_pct(v)
        out.append(f"[{color}]{ch}[/{color}]")
    return "".join(out)


@dataclass
class GpuProcRow:
    gpu: int
    pid: int
    name: str
    cmd: str
    mem_mib: float
    mem_pct: float
    cpu_pct: float
    ram_pct: float


@dataclass
class GpuRow:
    index: int
    name: str
    util: int
    mem_used_gb: float
    mem_total_gb: float
    temp_c: int
    junction_c: int | None
    vram_c: int | None
    power_w: float
    mem_util_pct: float
    fan_pct: int | None
    fan_control: int | None
    fan_target_pct: int | None


class MetricBox(Static):
    value = reactive("--")

    def __init__(self, title: str, value: str = "--", **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.value = value

    def render(self) -> str:
        return f"[b bright_white]{self.title}[/b bright_white]\n{self.value}"


class RigMonitor(App):
    CSS_PATH = None
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False),
        Binding("c", "toggle_cores", "Toggle cores"),
        Binding("w", "toggle_wall_mode", "Toggle wall mode"),
        Binding("f", "toggle_core_density", "Toggle core density"),
        Binding("g", "toggle_compact_gpu", "Toggle compact GPU"),
        Binding("b", "toggle_black_mode", "Toggle black mode"),
        Binding("p", "toggle_scrollbars", "Toggle scrollbars"),
    ]

    CSS = """
    Screen {
        layout: vertical;
        background: #050816;
        color: #f8fafc;
    }

    #topbar {
        height: 7;
        grid-size: 4 1;
        grid-columns: 1fr 1fr 1fr 1fr;
        grid-rows: 1fr;
        grid-gutter: 1;
        margin: 0 1 1 0;
    }

    .metric {
        border: heavy #475569;
        padding: 0 1;
        background: #0b1222;
        height: 1fr;
    }

    #main {
        height: 1fr;
        layout: horizontal;
    }

    #leftpane {
        width: 7fr;
        height: 1fr;
        layout: vertical;
    }

    #body_split {
        height: 1fr;
        layout: horizontal;
    }

    #cpu_cores_box {
        width: 2fr;
        height: 1fr;
    }

    #gpu_box {
        width: 5fr;
        height: 1fr;
    }

    #rightpane {
        width: 3fr;
        height: 1fr;
    }

    .panel {
        border: heavy #475569;
        padding: 1 2;
        margin: 0 1 1 0;
        background: #0b1020;
    }

    #gpu_box {
        height: 1fr;
    }

    #proc_box {
        height: 1fr;
        margin: 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Grid(id="topbar"):
            self.cpu_box = MetricBox("CPU", classes="metric")
            self.ram_box = MetricBox("RAM", classes="metric")
            self.net_box = MetricBox("BANDWIDTH", classes="metric")
            self.disk_box = MetricBox("DISK I/O", classes="metric")
            yield self.cpu_box
            yield self.ram_box
            yield self.net_box
            yield self.disk_box
        with Horizontal(id="main"):
            with Vertical(id="leftpane"):
                with Horizontal(id="body_split"):
                    with VerticalScroll(classes="panel", id="cpu_cores_box"):
                        self.cpu_cores_content = Static("[b]CPU CORES[/b]")
                        yield self.cpu_cores_content
                    with VerticalScroll(classes="panel", id="gpu_box"):
                        self.gpu_content = Static("[b]GPU COMMAND CENTER[/b]")
                        yield self.gpu_content
            with Vertical(id="rightpane"):
                self.proc_box = Static("[b]TOP PROCESSES[/b]", classes="panel", id="proc_box")
                yield self.proc_box
        yield Footer()

    def on_mount(self) -> None:
        self.cpu_name = get_cpu_name()
        self.cpu_core_count = psutil.cpu_count(logical=True) or 0
        self.show_all_cores = True
        self.force_wall_mode = True
        self.compact_core_density = True
        self.force_compact_gpu = False
        self.black_mode = False
        self.scrollbars_visible = False
        self.theme = 'ansi-dark'
        self.last_net = psutil.net_io_counters()
        self.last_disk = psutil.disk_io_counters()
        self.last_ts = time.time()
        self.net_down_hist: Deque[float] = deque(maxlen=120)
        self.net_up_hist: Deque[float] = deque(maxlen=120)
        self.disk_read_hist: Deque[float] = deque(maxlen=120)
        self.disk_write_hist: Deque[float] = deque(maxlen=120)
        self.cpu_hist: Deque[float] = deque(maxlen=120)
        self.gpu_util_hist: Deque[float] = deque(maxlen=120)
        self.gpu_mem_hist: Deque[float] = deque(maxlen=120)
        self.cached_gpu_proc_rows: List[GpuProcRow] = []
        self.cached_top_procs: List[tuple] = []
        self.last_proc_refresh = 0.0
        self.cached_gpu_fan_control: dict[int, int | None] = {}
        self.cached_fan_target_pct: int | None = None
        self.last_fan_refresh = 0.0
        self._apply_scrollbar_style()
        psutil.cpu_percent(interval=None, percpu=True)
        self.set_interval(1.0, self.refresh_stats)

    def is_compact(self) -> bool:
        return self.size.width < 150 or self.size.height < 42

    def is_wall_mode(self) -> bool:
        return self.force_wall_mode

    def is_compact_wall_gpu(self) -> bool:
        return self.force_compact_gpu

    def is_medium_wall_gpu(self) -> bool:
        return False

    def is_tiny(self) -> bool:
        return self.size.width < 125 or self.size.height < 34

    def action_toggle_cores(self) -> None:
        self.show_all_cores = not self.show_all_cores
        self.refresh_stats()

    def action_toggle_wall_mode(self) -> None:
        self.force_wall_mode = not self.force_wall_mode
        self.refresh_stats()

    def action_toggle_core_density(self) -> None:
        self.compact_core_density = not self.compact_core_density
        self.refresh_stats()

    def action_toggle_compact_gpu(self) -> None:
        self.force_compact_gpu = not self.force_compact_gpu
        self.refresh_stats()

    def _apply_scrollbar_style(self) -> None:
        for w in self.query(VerticalScroll):
            if self.scrollbars_visible:
                w.styles.scrollbar_size_vertical = 1
                w.styles.scrollbar_size_horizontal = 1
                if self.black_mode:
                    w.styles.scrollbar_background = '#06080d'
                    w.styles.scrollbar_color = '#0a0d12'
                    w.styles.scrollbar_color_hover = '#11151c'
                    w.styles.scrollbar_color_active = '#1a1f28'
                    w.styles.scrollbar_corner_color = '#06080d'
                else:
                    w.styles.scrollbar_background = '#0b1020'
                    w.styles.scrollbar_color = '#1d4ed8'
                    w.styles.scrollbar_color_hover = '#2563eb'
                    w.styles.scrollbar_color_active = '#3b82f6'
                    w.styles.scrollbar_corner_color = '#0b1020'
            else:
                w.styles.scrollbar_size_vertical = 0
                w.styles.scrollbar_size_horizontal = 0
                if self.black_mode:
                    w.styles.scrollbar_background = '#06080d'
                    w.styles.scrollbar_color = '#06080d'
                    w.styles.scrollbar_color_hover = '#06080d'
                    w.styles.scrollbar_color_active = '#06080d'
                    w.styles.scrollbar_corner_color = '#06080d'
                else:
                    w.styles.scrollbar_background = '#0b1020'
                    w.styles.scrollbar_color = '#0b1020'
                    w.styles.scrollbar_color_hover = '#0b1020'
                    w.styles.scrollbar_color_active = '#0b1020'
                    w.styles.scrollbar_corner_color = '#0b1020'

    def action_toggle_scrollbars(self) -> None:
        self.scrollbars_visible = not self.scrollbars_visible
        self._apply_scrollbar_style()
        self.refresh_stats()

    def action_toggle_black_mode(self) -> None:
        self.black_mode = not self.black_mode
        if self.black_mode:
            self.screen.styles.background = '#05070c'
            for w in self.query('.metric'):
                w.styles.background = '#06080d'
                w.styles.border = ('heavy', '#181c24')
            for w in self.query('.panel'):
                w.styles.background = '#06080d'
                w.styles.border = ('heavy', '#181c24')
        else:
            self.screen.styles.background = '#050816'
            for w in self.query('.metric'):
                w.styles.background = '#0b1222'
                w.styles.border = ('heavy', '#475569')
            for w in self.query('.panel'):
                w.styles.background = '#0b1020'
                w.styles.border = ('heavy', '#475569')
        self._apply_scrollbar_style()
        self.refresh_stats()

    def get_gpu_extra_temps(self) -> dict[int, dict]:
        candidates = [
            os.path.expanduser('~/.gputemps-wrapper.sh'),
            '/usr/local/bin/gputemps',
            os.path.expanduser('~/gputemps'),
            os.path.expanduser('~/gddr6-core-junction-vram-temps/gputemps'),
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                out = subprocess.check_output([path, '--json', '--once'], text=True, stderr=subprocess.DEVNULL, timeout=2.5)
                payload = json.loads(out)
                result = {}
                for gpu in payload.get('gpus', []):
                    idx = int(gpu.get('index'))
                    result[idx] = {
                        'core': gpu.get('core'),
                        'junction': gpu.get('junction'),
                        'vram': gpu.get('vram'),
                    }
                return result
            except Exception:
                continue
        return {}

    def get_gpu_fan_settings(self) -> tuple[dict[int, int | None], int | None]:
        """Return nvidia-settings fan mode per GPU and the current configured target.

        NVIDIA exposes current fan speed cleanly through NVML per GPU. The manual/auto
        control state is GPU-scoped, while target fan speed is fan-scoped; on multi-fan
        cards there is no simple portable fan→GPU map here. Since this monitor's fan
        controller intentionally applies one fleet-safe target to every fan, showing the
        highest configured target is both accurate and tidy.
        """
        now = time.time()
        if (now - self.last_fan_refresh) < 2.0:
            return self.cached_gpu_fan_control, self.cached_fan_target_pct

        control: dict[int, int | None] = {}
        target: int | None = None
        try:
            out = subprocess.check_output(
                ["nvidia-settings", "--ctrl-display=:0", "-q", "GPUFanControlState", "-q", "GPUTargetFanSpeed"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
                env={**os.environ, "DISPLAY": ":0", "XAUTHORITY": "/root/.Xauthority"},
            )
            for line in out.splitlines():
                m = re.search(r"\[gpu:(\d+)\].*?:\s*(\d+)\.", line)
                if m and "GPUFanControlState" in line:
                    control[int(m.group(1))] = int(m.group(2))
                    continue
                m = re.search(r"GPUTargetFanSpeed.*?:\s*(\d+)\.", line)
                if m:
                    val = int(m.group(1))
                    target = val if target is None else max(target, val)
        except Exception:
            pass

        self.cached_gpu_fan_control = control
        self.cached_fan_target_pct = target
        self.last_fan_refresh = now
        return control, target


    def format_wall_fan_value(self, g: GpuRow) -> str:
        if g.fan_pct is None:
            return "[white]--%[/white]"
        fan_color = color_for_fan(g.fan_pct)
        value = f"[{fan_color}]{g.fan_pct}%[/{fan_color}]"
        if g.fan_control == 0 or (g.fan_pct == 0 and g.temp_c < 50):
            value += " [green]A[/green]"
        return value

    def format_fan_label(self, g: GpuRow, compact: bool = False) -> str:
        if g.fan_pct is None:
            return "FAN [white]--[/white]"
        fan_color = color_for_fan(g.fan_pct)
        label = f"FAN [{fan_color}]{g.fan_pct:>3}%[/{fan_color}]"
        if g.fan_control == 1 and g.fan_target_pct is not None:
            label += f"→[{fan_color}]{g.fan_target_pct}%[/{fan_color}]"
        elif g.fan_control == 0:
            label += " [green]A[/green]"
        elif not compact and g.fan_target_pct is not None:
            label += f" T{g.fan_target_pct}%"
        return label

    def get_gpu_rows(self) -> List[GpuRow]:
        rows: List[GpuRow] = []
        if not NVML_OK:
            return rows
        extra_temps = self.get_gpu_extra_temps()
        fan_control, fan_target = self.get_gpu_fan_settings()
        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode()
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
                except Exception:
                    power = 0.0
                fan_pct = get_gpu_average_fan_pct(h)
                mem_util_pct = (mem.used / mem.total * 100.0) if mem.total else 0.0
                extra = extra_temps.get(i, {})
                rows.append(GpuRow(
                    index=i,
                    name=str(name),
                    util=int(util.gpu),
                    mem_used_gb=mem.used / 1024**3,
                    mem_total_gb=mem.total / 1024**3,
                    temp_c=int(extra.get('core') if extra.get('core') is not None else temp),
                    junction_c=int(extra['junction']) if extra.get('junction') is not None else None,
                    vram_c=int(extra['vram']) if extra.get('vram') is not None else None,
                    power_w=float(power),
                    mem_util_pct=float(mem_util_pct),
                    fan_pct=fan_pct,
                    fan_control=fan_control.get(i),
                    fan_target_pct=fan_target,
                ))
        except Exception:
            return []
        return rows

    def get_gpu_process_rows(self, compact: bool) -> List[GpuProcRow]:
        rows: List[GpuProcRow] = []
        if not NVML_OK:
            return rows
        try:
            count = pynvml.nvmlDeviceGetCount()
            limit = 6 if compact else 12
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem_total = 0
                try:
                    mem_total = pynvml.nvmlDeviceGetMemoryInfo(h).total
                except Exception:
                    mem_total = 0
                try:
                    compute = pynvml.nvmlDeviceGetComputeRunningProcesses(h)
                except Exception:
                    compute = []
                try:
                    graphics = pynvml.nvmlDeviceGetGraphicsRunningProcesses(h)
                except Exception:
                    graphics = []
                seen = set()
                for p in list(compute) + list(graphics):
                    pid = int(getattr(p, 'pid', 0) or 0)
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    used_mem = float(getattr(p, 'usedGpuMemory', 0) or 0)
                    mem_pct = (used_mem / mem_total * 100.0) if mem_total else 0.0
                    try:
                        proc = psutil.Process(pid)
                        name = proc.name()
                        try:
                            cmd = ' '.join(proc.cmdline()) or name
                        except Exception:
                            cmd = name
                        cpu_pct = proc.cpu_percent(interval=None)
                        ram_pct = proc.memory_percent()
                    except Exception:
                        name = '?'
                        cmd = name
                        cpu_pct = 0.0
                        ram_pct = 0.0
                    rows.append(GpuProcRow(
                        gpu=i,
                        pid=pid,
                        name=name,
                        cmd=cmd,
                        mem_mib=used_mem / 1024**2,
                        mem_pct=mem_pct,
                        cpu_pct=cpu_pct,
                        ram_pct=ram_pct,
                    ))
            rows.sort(key=lambda r: (r.mem_mib, r.cpu_pct), reverse=True)
            return rows[:limit]
        except Exception:
            return []

    def get_top_procs(self, compact: bool) -> List[tuple]:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                procs.append((
                    info.get("pid", 0),
                    str(info.get("name", "?")),
                    float(info.get("cpu_percent", 0.0)),
                    float(info.get("memory_percent", 0.0)),
                ))
            except Exception:
                continue
        procs.sort(key=lambda x: (x[2], x[3]), reverse=True)
        limit = 20
        trimmed = []
        for pid, name, cpu_p, mem_p in procs[:limit]:
            trimmed.append((pid, truncate_middle(name, 14 if compact else 20), cpu_p, mem_p))
        return trimmed

    def build_tiny_layout(self, cpu, cpu_title, vm, down_mb, up_mb, read_mb, write_mb, cpu_per_core, gpu_rows, gpu_proc_rows):
        cpu_color = color_for_pct(cpu)
        ram_color = color_for_pct(vm.percent)
        short_cpu = cpu_title.replace('AMD ', '').replace('Processor', '').strip()
        lines = ["[b bright_white]TINY MODE[/b bright_white]", ""]
        lines.append(f"CPU [{cpu_color}]{cpu:.0f}%[/{cpu_color}] [{cpu_color}]{bar(cpu, 100, 10)}[/{cpu_color}] {truncate_middle(short_cpu, 18)}")
        lines.append(f"RAM [{ram_color}]{vm.percent:.0f}%[/{ram_color}] [{ram_color}]{bar(vm.percent, 100, 10)}[/{ram_color}] free [cyan]{vm.available / 1024**3:.0f}G[/cyan]")
        lines.append(f"NET [{color_for_net_rate(down_mb)}]↓ {format_rate(down_mb)}[/{color_for_net_rate(down_mb)}] [{color_for_net_rate(up_mb)}]↑ {format_rate(up_mb)}[/{color_for_net_rate(up_mb)}]")
        lines.append(f"DSK [{color_for_disk_rate(read_mb)}]R {format_rate(read_mb)}[/{color_for_disk_rate(read_mb)}] [{color_for_disk_rate(write_mb)}]W {format_rate(write_mb)}[/{color_for_disk_rate(write_mb)}]")
        lines.append("")
        lines.append("[b bright_white]CPU CORES[/b bright_white]")
        shown_cores = cpu_per_core[:(len(cpu_per_core) if self.show_all_cores else 4)]
        for start in range(0, len(shown_cores), 2):
            chunk = shown_cores[start:start + 2]
            row = []
            for idx, val in enumerate(chunk, start=start):
                c = color_for_pct(val)
                row.append(f"C{idx:02d} [{c}]{val:>3.0f}%[/{c}] [{c}]{bar(val, 100, 5)}[/{c}]")
            lines.append("   ".join(row))
        if len(cpu_per_core) > len(shown_cores):
            lines.append(f"press c → {len(shown_cores)}/{len(cpu_per_core)} cores")
        lines.append("")
        lines.append("[b bright_white]GPUS[/b bright_white]")
        visible_gpu_rows = gpu_rows[:6]
        for g in visible_gpu_rows:
            gpu_color = color_for_pct(g.util)
            mem_color = color_for_pct(g.mem_util_pct)
            lines.append(f"G{g.index} [{gpu_color}]{g.util:>3}%[/{gpu_color}] [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}] [yellow]{g.temp_c}°[/yellow] {self.format_fan_label(g, compact=True)} [magenta]{g.power_w:.0f}W[/magenta]")
            lines.append(f"   {truncate_middle(g.name, 28)}")
        if len(gpu_rows) > len(visible_gpu_rows):
            lines.append(f"... showing {len(visible_gpu_rows)}/{len(gpu_rows)} gpus")
        lines.append("")
        lines.append("[b bright_white]TOP GPU PROCS[/b bright_white]")
        if gpu_proc_rows:
            for row in gpu_proc_rows[:4]:
                lines.append(f"G{row.gpu} [yellow]{row.mem_mib:>4.0f}M[/yellow] {truncate_middle(row.cmd, 24)}")
            if len(gpu_proc_rows) > 4:
                lines.append(f"... {len(gpu_proc_rows) - 4} more")
        else:
            lines.append("none")
        return "\n".join(lines)

    def refresh_stats(self) -> None:
        compact = self.is_compact()
        wall_mode = self.is_wall_mode()
        compact_wall_gpu = self.is_compact_wall_gpu()
        medium_wall_gpu = self.is_medium_wall_gpu()
        tiny = self.is_tiny()
        now = time.time()
        dt = max(now - self.last_ts, 0.0001)

        cpu = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        load = psutil.getloadavg()
        vm = psutil.virtual_memory()
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()

        down_mb = (net.bytes_recv - self.last_net.bytes_recv) / dt / 1024 / 1024
        up_mb = (net.bytes_sent - self.last_net.bytes_sent) / dt / 1024 / 1024
        read_mb = (disk.read_bytes - self.last_disk.read_bytes) / dt / 1024 / 1024 if disk and self.last_disk else 0
        write_mb = (disk.write_bytes - self.last_disk.write_bytes) / dt / 1024 / 1024 if disk and self.last_disk else 0

        self.net_down_hist.append(down_mb)
        self.net_up_hist.append(up_mb)
        self.disk_read_hist.append(read_mb)
        self.disk_write_hist.append(write_mb)
        self.cpu_hist.append(cpu)

        mode_tag = " [WALL]" if wall_mode else " [STD]"
        if self.force_compact_gpu:
            mode_tag += " [GPU-C]"
        cpu_title = truncate_middle(self.cpu_name, 28 if compact else 42)
        cpu_short = short_cpu_label(self.cpu_name)
        cpu_bar = bar(cpu, 100, 10 if compact else 16)
        ram_bar = bar(vm.percent, 100, 10 if compact else 16)
        cpu_color = color_for_pct(cpu)
        ram_color = color_for_pct(vm.percent)
        avail_color = color_for_pct(100 - (vm.available / vm.total * 100.0 if vm.total else 0.0))
        load1_color = color_for_load(load[0], self.cpu_core_count)
        load5_color = color_for_load(load[1], self.cpu_core_count)
        load15_color = color_for_load(load[2], self.cpu_core_count)
        net_peak = max(list(self.net_down_hist) + list(self.net_up_hist) + [0.05])
        down_color = color_for_net_rate(down_mb)
        up_color = color_for_net_rate(up_mb)
        read_color = color_for_disk_rate(read_mb)
        write_color = color_for_disk_rate(write_mb)
        if tiny:
            short_cpu = self.cpu_name.replace('AMD ', '').replace('Processor', '').strip()
            self.cpu_box.value = (
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}] [{cpu_color}]{bar(cpu, 100, 8)}[/{cpu_color}]\n"
                f"{cpu_short}{mode_tag}"
            )
            self.ram_box.value = (
                f"[{ram_color}]{vm.percent:.0f}%[/{ram_color}] [{ram_color}]{bar(vm.percent, 100, 8)}[/{ram_color}]\n"
                f"free [{avail_color}]{vm.available / 1024**3:.0f}G[/{avail_color}]"
            )
            self.net_box.value = (
                f"[{down_color}]↓ {format_rate(down_mb)}[/{down_color}]\n"
                f"[{up_color}]↑ {format_rate(up_mb)}[/{up_color}]"
            )
            self.disk_box.value = (
                f"[{read_color}]R {format_rate(read_mb)}[/{read_color}]\n"
                f"[{write_color}]W {format_rate(write_mb)}[/{write_color}]"
            )
        else:
            full_cpu_label = truncate_middle(self.cpu_name, 42)
            self.cpu_box.value = (
                f"{full_cpu_label}\n"
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}]  [{cpu_color}]{bar(cpu, 100, 16)}[/{cpu_color}]\n"
                f"load [{load1_color}]{load[0]:.1f}[/{load1_color}] [{load5_color}]{load[1]:.1f}[/{load5_color}] [{load15_color}]{load[2]:.1f}[/{load15_color}]"
            )
            self.ram_box.value = (
                f"used [{ram_color}]{vm.used / 1024**3:.1f}G[/{ram_color}] / [bright_white]{vm.total / 1024**3:.1f}G[/bright_white]\n"
                f"[{ram_color}]{vm.percent:>3.0f}%[/{ram_color}]  [{ram_color}]{bar(vm.percent, 100, 18)}[/{ram_color}]\n"
                f"free [{avail_color}]{vm.available / 1024**3:.1f}G[/{avail_color}]"
            )
            self.net_box.value = (
                f"[{down_color}]↓ {format_rate(down_mb)}[/{down_color}]\n"
                f"[{up_color}]↑ {format_rate(up_mb)}[/{up_color}]\n"
                f"[{down_color}]{sparkline(list(self.net_down_hist), max_value=net_peak, width=24)}[/{down_color}]\n"
                f"[{up_color}]{sparkline(list(self.net_up_hist), max_value=net_peak, width=24)}[/{up_color}]"
            )
            self.disk_box.value = (
                f"[{read_color}]R {format_rate(read_mb)}[/{read_color}]\n"
                f"[{write_color}]W {format_rate(write_mb)}[/{write_color}]\n"
                f"[{read_color}]{sparkline(list(self.disk_read_hist), width=24)}[/{read_color}]\n"
                f"[{write_color}]{sparkline(list(self.disk_write_hist), width=24)}[/{write_color}]"
            )

        gpu_rows = self.get_gpu_rows()
        proc_refresh_interval = 4.0 if (compact or wall_mode) else 2.0
        if (now - self.last_proc_refresh) >= proc_refresh_interval or not self.cached_gpu_proc_rows:
            self.cached_gpu_proc_rows = self.get_gpu_process_rows(compact)
            self.cached_top_procs = self.get_top_procs(compact)
            self.last_proc_refresh = now
        gpu_proc_rows = self.cached_gpu_proc_rows

        gpu_lines = ["[b bright_white]GPU COMMAND CENTER[/b bright_white]", ""]

        if gpu_rows:
            primary = gpu_rows[0]
            self.gpu_util_hist.append(primary.util)
            self.gpu_mem_hist.append(primary.mem_util_pct)
        else:
            self.gpu_util_hist.append(0)
            self.gpu_mem_hist.append(0)

        core_lines = ["[b bright_white]CPU CORES[/b bright_white]"]
        if cpu_per_core:
            default_limit = 4 if wall_mode else (8 if compact else 16)
            max_cores = len(cpu_per_core) if self.show_all_cores else min(len(cpu_per_core), default_limit)
            shown = cpu_per_core[:max_cores]
            cols = 4 if self.compact_core_density else (2 if wall_mode else (2 if compact else 4))
            for start in range(0, len(shown), cols):
                chunk = shown[start:start + cols]
                row = []
                for idx, val in enumerate(chunk, start=start):
                    c = color_for_pct(val)
                    if self.compact_core_density:
                        row.append(f"C{idx:02d} [{c}]{val:>3.0f}%[/{c}]")
                    else:
                        row.append(f"C{idx:02d} [{c}]{val:>3.0f}%[/{c}] [{c}]{bar(val, 100, 6 if (compact or wall_mode) else 8)}[/{c}]")
                core_lines.append("   ".join(row))
            if len(cpu_per_core) > default_limit:
                mode = "all" if self.show_all_cores else f"{default_limit}"
                density = 'dense' if self.compact_core_density else 'normal'
                core_lines.append(f"c:{mode}/{len(cpu_per_core)}  f:{density}")
        else:
            core_lines.append("no per-core data")

        if gpu_rows:
            gpu_row_limit = 4 if wall_mode else (4 if compact else len(gpu_rows))
            visible_gpu_rows = gpu_rows[:gpu_row_limit]
            for g in visible_gpu_rows:
                gpu_color = color_for_pct(g.util)
                mem_color = color_for_pct(g.mem_util_pct)
                temp_flag = "[red]HOT[/red]" if g.temp_c >= 80 else ("[yellow]WARM[/yellow]" if g.temp_c >= 65 else "[green]OK[/green]")
                core_temp_color = color_for_temp(g.temp_c, warm=65, hot=80)
                junction_temp_color = color_for_temp(g.junction_c, warm=90, hot=100)
                vram_temp_color = color_for_temp(g.vram_c, warm=80, hot=95)
                gpu_name = g.name if compact else truncate_middle(g.name, 40)
                if wall_mode and not self.force_compact_gpu:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{truncate_middle(gpu_name, 32)}[/bright_white]")
                    gpu_lines.append(f"UTIL [{gpu_color}]{g.util}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 43)}[/{gpu_color}]")
                    gpu_lines.append(f"VRAM [{mem_color}]{g.mem_util_pct:.0f}%[/{mem_color}] [{mem_color}]{bar(g.mem_util_pct, 100, 43)}[/{mem_color}]")
                    temp_field = pad_rich_right(f"TEMP [{core_temp_color}]{g.temp_c}°C[/{core_temp_color}]", 21)
                    junc_field = pad_rich_right(f"Junc [{junction_temp_color}]{g.junction_c}°C[/{junction_temp_color}]" if g.junction_c is not None else "", 16)
                    vram_field = f"Vram [{vram_temp_color}]{g.vram_c}°C[/{vram_temp_color}]" if g.vram_c is not None else ""
                    gpu_lines.append(f"{temp_field}{junc_field}{vram_field}")
                    pwr_color = color_for_power_watts(g.power_w)
                    fan_field = pad_rich_right(f"FAN {self.format_wall_fan_value(g)}", 22)
                    pwr_field = pad_rich_right(f"PWR [{pwr_color}]{g.power_w:.0f}W[/{pwr_color}]", 15)
                    mem_field = f"MEM [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f}G[/green]"
                    gpu_lines.append(f"{fan_field}{pwr_field}{mem_field}")
                elif tiny or (wall_mode and self.force_compact_gpu):
                    tiny_temp = f"[{core_temp_color}]{g.temp_c}°[/{core_temp_color}]"
                    if g.junction_c is not None:
                        tiny_temp += f" [{junction_temp_color}]J{g.junction_c}°[/{junction_temp_color}]"
                    if g.vram_c is not None:
                        tiny_temp += f" [{vram_temp_color}]V{g.vram_c}°[/{vram_temp_color}]"
                    gpu_lines.append(
                        f"[b cyan]G{g.index}[/b cyan] {truncate_middle(gpu_name, 24)}  [{gpu_color}]{g.util:>3}%[/{gpu_color}]  [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}]  {tiny_temp}  {self.format_fan_label(g, compact=True)}  [magenta]{g.power_w:.0f}W[/magenta]"
                    )
                elif compact:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{gpu_name}[/bright_white]")
                    gpu_lines.append(f"[{gpu_color}]{g.util:>3}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 12)}[/{gpu_color}] [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}]")
                    compact_temp = f"[{core_temp_color}]{g.temp_c}°C[/{core_temp_color}]"
                    if g.junction_c is not None:
                        compact_temp += f" J[{junction_temp_color}]{g.junction_c}°C[/{junction_temp_color}]"
                    if g.vram_c is not None:
                        compact_temp += f" V[{vram_temp_color}]{g.vram_c}°C[/{vram_temp_color}]"
                    gpu_lines.append(f"{compact_temp} {self.format_fan_label(g, compact=True)} [magenta]{g.power_w:.0f}W[/magenta] {temp_flag} [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f}G[/green]")
                else:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{gpu_name}[/bright_white]")
                    gpu_lines.append(f"UTIL [{gpu_color}]{g.util:>3}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 24)}[/{gpu_color}]")
                    gpu_lines.append(f"VRAM [{mem_color}]{g.mem_util_pct:>3.0f}%[/{mem_color}] [{mem_color}]{bar(g.mem_util_pct, 100, 24)}[/{mem_color}]  [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f} GB[/green]")
                    temp_line = f"TEMP [{core_temp_color}]{g.temp_c}°C[/{core_temp_color}]"
                    if g.junction_c is not None:
                        temp_line += f"  J [{junction_temp_color}]{g.junction_c}°C[/{junction_temp_color}]"
                    if g.vram_c is not None:
                        temp_line += f"  V [{vram_temp_color}]{g.vram_c}°C[/{vram_temp_color}]"
                    gpu_lines.append(f"{temp_line}  {self.format_fan_label(g)}  [magenta]{g.power_w:.0f}W[/magenta]  {temp_flag}")
                if not tiny:
                    gpu_lines.append("")
            if len(gpu_rows) > len(visible_gpu_rows):
                gpu_lines.append(f"... showing {len(visible_gpu_rows)}/{len(gpu_rows)} gpus")
        else:
            gpu_lines.append("NVML unavailable")
            gpu_lines.append("")

        self.cpu_cores_content.update("\n".join(core_lines))

        gpu_body = []
        gpu_body.extend(gpu_lines)
        gpu_body.append("")
        gpu_body.append("─" * 34)
        gpu_body.append("[b bright_white]GPU WORKLOAD[/b bright_white]")
        if gpu_proc_rows:
            if wall_mode:
                gpu_body.append("GPU PID      GPU-MEM  MEM%  CPU%  RAM%  COMMAND")
                for row in gpu_proc_rows:
                    cmd = truncate_middle(row.cmd, 28)
                    gpu_body.append(
                        f"[magenta]{row.gpu}[/magenta]   {row.pid:<8} [yellow]{row.mem_mib:>4.0f}M[/yellow]   {row.mem_pct:>4.1f}  [cyan]{row.cpu_pct:>4.1f}[/cyan]  [green]{row.ram_pct:>4.1f}[/green]  {cmd}"
                    )
            elif compact:
                compact_gpu_proc_rows = gpu_proc_rows[:2]
                for row in compact_gpu_proc_rows:
                    gpu_body.append(
                        f"GPU{row.gpu}  [yellow]{row.mem_mib:>4.0f} MiB[/yellow]  [cyan]{row.cpu_pct:>3.0f}%[/cyan]"
                    )
                    gpu_body.append(f"{truncate_middle(row.cmd, 30)}")
                    gpu_body.append("")
                if len(gpu_proc_rows) > len(compact_gpu_proc_rows):
                    gpu_body.append(f"... {len(gpu_proc_rows) - len(compact_gpu_proc_rows)} more")
            else:
                gpu_body.append("GPU PID      GPU-MEM   MEM%   CPU%   RAM%   COMMAND")
                for row in gpu_proc_rows:
                    cmd = truncate_middle(row.cmd, 42)
                    gpu_body.append(
                        f"[magenta]{row.gpu}[/magenta]   {row.pid:<8} [yellow]{row.mem_mib:>6.0f}M[/yellow]  {row.mem_pct:>5.1f}  [cyan]{row.cpu_pct:>5.1f}[/cyan]  [green]{row.ram_pct:>5.1f}[/green]  {cmd}"
                    )
        else:
            gpu_body.append("idle")
        self.gpu_content.update("\n".join(gpu_body))

        self.query_one('#leftpane').styles.width = '7fr'
        if wall_mode:
            self.query_one('#rightpane').styles.display = 'none'
            self.proc_box.update('[b bright_white]TOP PROCESSES[/b bright_white]\n\nhidden in wall mode')
        else:
            self.query_one('#rightpane').styles.display = 'block'
            self.query_one('#rightpane').styles.width = '3fr'
            procs = self.cached_top_procs
            proc_lines = ["[b bright_white]TOP PROCESSES[/b bright_white]", "", "PID      NAME           CPU%  MEM%" if compact else "PID      NAME                 CPU%   MEM%"]
            display_procs = procs[:8] if compact else procs
            for pid, name, cpu_p, mem_p in display_procs:
                if compact:
                    proc_lines.append(f"{pid:<8} {name:<14} [cyan]{cpu_p:>4.1f}[/cyan] [green]{mem_p:>5.1f}[/green]")
                else:
                    proc_lines.append(f"{pid:<8} {name:<20} [cyan]{cpu_p:>5.1f}[/cyan] [green]{mem_p:>6.1f}[/green]")
            self.proc_box.update("\n".join(proc_lines))

        self.last_net = net
        self.last_disk = disk
        self.last_ts = now


if __name__ == "__main__":
    RigMonitor().run()
