import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List

import psutil
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical
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


def color_for_pct(value: float) -> str:
    if value >= 90:
        return "red"
    if value >= 70:
        return "yellow"
    if value >= 40:
        return "cyan"
    return "green"


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
    power_w: float
    mem_util_pct: float


class MetricBox(Static):
    value = reactive("--")

    def __init__(self, title: str, value: str = "--", **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.value = value

    def render(self) -> str:
        return f"[b bright_white]{self.title}[/b bright_white]\n{self.value}"


class RigMonitor(App):
    BINDINGS = [
        Binding("c", "toggle_cores", "Toggle cores"),
        Binding("w", "toggle_wall_mode", "Toggle wall mode"),
        Binding("f", "toggle_core_density", "Toggle core density"),
        Binding("g", "toggle_compact_gpu", "Toggle compact GPU"),
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
        border: heavy #38bdf8;
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
                    self.cpu_cores_box = Static("[b]CPU CORES[/b]", classes="panel", id="cpu_cores_box")
                    self.gpu_box = Static("[b]GPU COMMAND CENTER[/b]", classes="panel", id="gpu_box")
                    yield self.cpu_cores_box
                    yield self.gpu_box
            with Vertical(id="rightpane"):
                self.proc_box = Static("[b]TOP PROCESSES[/b]", classes="panel", id="proc_box")
                yield self.proc_box
        yield Footer()

    def on_mount(self) -> None:
        self.cpu_name = get_cpu_name()
        self.cpu_core_count = psutil.cpu_count(logical=True) or 0
        self.show_all_cores = False
        self.force_wall_mode = False
        self.compact_core_density = False
        self.force_compact_gpu = False
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
        psutil.cpu_percent(interval=None, percpu=True)
        self.set_interval(1.0, self.refresh_stats)

    def is_compact(self) -> bool:
        return self.size.width < 150 or self.size.height < 42

    def is_wall_mode(self) -> bool:
        return self.force_wall_mode or self.size.width < 170 or self.size.height < 48

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

    def get_gpu_rows(self) -> List[GpuRow]:
        rows: List[GpuRow] = []
        if not NVML_OK:
            return rows
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
                mem_util_pct = (mem.used / mem.total * 100.0) if mem.total else 0.0
                rows.append(GpuRow(
                    index=i,
                    name=str(name),
                    util=int(util.gpu),
                    mem_used_gb=mem.used / 1024**3,
                    mem_total_gb=mem.total / 1024**3,
                    temp_c=int(temp),
                    power_w=float(power),
                    mem_util_pct=float(mem_util_pct),
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
        lines.append(f"NET [bright_blue]↓ {format_rate(down_mb)}[/bright_blue] [cyan]↑ {format_rate(up_mb)}[/cyan]")
        lines.append(f"DSK [bright_blue]R {format_rate(read_mb)}[/bright_blue] [cyan]W {format_rate(write_mb)}[/cyan]")
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
            lines.append(f"G{g.index} [{gpu_color}]{g.util:>3}%[/{gpu_color}] [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}] [yellow]{g.temp_c}°[/yellow] [magenta]{g.power_w:.0f}W[/magenta]")
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

        mode_tag = " [WALL]" if wall_mode else ""
        if self.force_compact_gpu:
            mode_tag += " [GPU-C]"
        cpu_title = truncate_middle(self.cpu_name, 28 if compact else 42)
        cpu_bar = bar(cpu, 100, 10 if compact else 16)
        ram_bar = bar(vm.percent, 100, 10 if compact else 16)
        cpu_color = color_for_pct(cpu)
        ram_color = color_for_pct(vm.percent)
        net_peak = max(list(self.net_down_hist) + list(self.net_up_hist) + [1.0])
        if tiny:
            short_cpu = self.cpu_name.replace('AMD ', '').replace('Processor', '').strip()
            self.cpu_box.value = (
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}] [{cpu_color}]{bar(cpu, 100, 8)}[/{cpu_color}]\n"
                f"{truncate_middle(short_cpu, 20)}{mode_tag}"
            )
            self.ram_box.value = (
                f"[{ram_color}]{vm.percent:.0f}%[/{ram_color}] [{ram_color}]{bar(vm.percent, 100, 8)}[/{ram_color}]\n"
                f"free [cyan]{vm.available / 1024**3:.0f}G[/cyan]"
            )
            self.net_box.value = (
                f"[bright_blue]↓ {format_rate(down_mb)}[/bright_blue]\n"
                f"[cyan]↑ {format_rate(up_mb)}[/cyan]"
            )
            self.disk_box.value = (
                f"[bright_blue]R {format_rate(read_mb)}[/bright_blue]\n"
                f"[cyan]W {format_rate(write_mb)}[/cyan]"
            )
        elif wall_mode:
            self.cpu_box.value = (
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}]  [{cpu_color}]{bar(cpu, 100, 12)}[/{cpu_color}]\n"
                f"[yellow]ld {load[0]:.1f}[/yellow]  {truncate_middle(cpu_title, 20)}{mode_tag}"
            )
            self.ram_box.value = (
                f"[{ram_color}]{vm.percent:.0f}%[/{ram_color}]  [{ram_color}]{bar(vm.percent, 100, 12)}[/{ram_color}]\n"
                f"[green]{vm.used / 1024**3:.1f}/{vm.total / 1024**3:.1f}G[/green] free [cyan]{vm.available / 1024**3:.1f}G[/cyan]"
            )
            self.net_box.value = (
                f"[bright_blue]↓ {format_rate(down_mb)}[/bright_blue]\n"
                f"[cyan]↑ {format_rate(up_mb)}[/cyan]"
            )
            self.disk_box.value = (
                f"[bright_blue]R {format_rate(read_mb)}[/bright_blue]\n"
                f"[cyan]W {format_rate(write_mb)}[/cyan]"
            )
        elif compact:
            self.cpu_box.value = (
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}] [{cpu_color}]{cpu_bar}[/{cpu_color}]\n"
                f"[yellow]ld {load[0]:.1f}[/yellow]  {truncate_middle(cpu_title, 16)}{mode_tag}"
            )
            self.ram_box.value = (
                f"[{ram_color}]{vm.percent:.0f}%[/{ram_color}] [{ram_color}]{ram_bar}[/{ram_color}]\n"
                f"[green]{vm.used / 1024**3:.1f}/{vm.total / 1024**3:.1f}G[/green] free [cyan]{vm.available / 1024**3:.1f}G[/cyan]"
            )
            self.net_box.value = (
                f"[bright_blue]↓ {format_rate(down_mb)}[/bright_blue]\n"
                f"[cyan]↑ {format_rate(up_mb)}[/cyan]"
            )
            self.disk_box.value = (
                f"[bright_blue]R {format_rate(read_mb)}[/bright_blue]\n"
                f"[cyan]W {format_rate(write_mb)}[/cyan]"
            )
        else:
            self.cpu_box.value = (
                f"{cpu_title}{mode_tag}\n"
                f"[{cpu_color}]{cpu:.0f}%[/{cpu_color}]  [{cpu_color}]{cpu_bar}[/{cpu_color}]\n"
                f"[yellow]load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}[/yellow]\n"
                f"{heat_sparkline(list(self.cpu_hist), width=24)}"
            )
            self.ram_box.value = (
                f"[green]{vm.used / 1024**3:.1f}[/green] / [cyan]{vm.total / 1024**3:.1f} GB[/cyan]\n"
                f"[{ram_color}]{vm.percent:.0f}%[/{ram_color}]  [{ram_color}]{ram_bar}[/{ram_color}]\n"
                f"avail [cyan]{vm.available / 1024**3:.1f} GB[/cyan]"
            )
            self.net_box.value = (
                f"[bright_blue]↓ {format_rate(down_mb)}[/bright_blue]\n"
                f"[cyan]↑ {format_rate(up_mb)}[/cyan]\n"
                f"[bright_blue]{sparkline(list(self.net_down_hist), max_value=net_peak, width=24)}[/bright_blue]\n"
                f"[cyan]{sparkline(list(self.net_up_hist), max_value=net_peak, width=24)}[/cyan]"
            )
            self.disk_box.value = (
                f"[bright_blue]R {format_rate(read_mb)}[/bright_blue]\n"
                f"[cyan]W {format_rate(write_mb)}[/cyan]\n"
                f"[bright_blue]{sparkline(list(self.disk_read_hist), width=24)}[/bright_blue]\n"
                f"[cyan]{sparkline(list(self.disk_write_hist), width=24)}[/cyan]"
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
                gpu_name = g.name if compact else truncate_middle(g.name, 40)
                if wall_mode and not self.force_compact_gpu:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{truncate_middle(gpu_name, 22)}[/bright_white]")
                    gpu_lines.append(f"UTIL [{gpu_color}]{g.util:>3}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 20)}[/{gpu_color}]")
                    gpu_lines.append(f"VRAM [{mem_color}]{g.mem_util_pct:>3.0f}%[/{mem_color}] [{mem_color}]{bar(g.mem_util_pct, 100, 20)}[/{mem_color}]")
                    gpu_lines.append(f"TEMP [yellow]{g.temp_c}°C[/yellow]  [magenta]{g.power_w:.0f}W[/magenta]  [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f}G[/green]")
                elif tiny or (wall_mode and self.force_compact_gpu):
                    gpu_lines.append(
                        f"[b cyan]G{g.index}[/b cyan] {truncate_middle(gpu_name, 20)}  [{gpu_color}]{g.util:>3}%[/{gpu_color}]  [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}]  [yellow]{g.temp_c}°[/yellow]  [magenta]{g.power_w:.0f}W[/magenta]"
                    )
                elif compact:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{gpu_name}[/bright_white]")
                    gpu_lines.append(f"[{gpu_color}]{g.util:>3}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 12)}[/{gpu_color}] [{mem_color}]{g.mem_util_pct:>3.0f}% mem[/{mem_color}]")
                    gpu_lines.append(f"[yellow]{g.temp_c}°C[/yellow] [magenta]{g.power_w:.0f}W[/magenta] {temp_flag} [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f}G[/green]")
                else:
                    gpu_lines.append(f"[b cyan]GPU {g.index}[/b cyan] [bright_white]{gpu_name}[/bright_white]")
                    gpu_lines.append(f"UTIL [{gpu_color}]{g.util:>3}%[/{gpu_color}] [{gpu_color}]{bar(g.util, 100, 24)}[/{gpu_color}]")
                    gpu_lines.append(f"VRAM [{mem_color}]{g.mem_util_pct:>3.0f}%[/{mem_color}] [{mem_color}]{bar(g.mem_util_pct, 100, 24)}[/{mem_color}]  [green]{g.mem_used_gb:.1f}/{g.mem_total_gb:.1f} GB[/green]")
                    gpu_lines.append(f"TEMP [yellow]{g.temp_c}°C[/yellow]  [magenta]{g.power_w:.0f}W[/magenta]  {temp_flag}")
                if not tiny:
                    gpu_lines.append("")
            if len(gpu_rows) > len(visible_gpu_rows):
                gpu_lines.append(f"... showing {len(visible_gpu_rows)}/{len(gpu_rows)} gpus")
        else:
            gpu_lines.append("NVML unavailable")
            gpu_lines.append("")

        self.cpu_cores_box.update("\n".join(core_lines))

        gpu_body = []
        gpu_body.extend(gpu_lines)
        gpu_body.append("")
        gpu_body.append("[b bright_white]GPU PROCESSES[/b bright_white]")
        if gpu_proc_rows:
            if wall_mode:
                wall_gpu_proc_rows = gpu_proc_rows[:3]
                gpu_body.append("TOP GPU PROCS")
                for row in wall_gpu_proc_rows:
                    cmd = truncate_middle(row.cmd, 24)
                    gpu_body.append(
                        f"G{row.gpu} [yellow]{row.mem_mib:>4.0f}M[/yellow] [cyan]{row.cpu_pct:>3.0f}%[/cyan] {cmd}"
                    )
                if len(gpu_proc_rows) > len(wall_gpu_proc_rows):
                    gpu_body.append(f"... {len(gpu_proc_rows) - len(wall_gpu_proc_rows)} more")
            elif compact:
                compact_gpu_proc_rows = gpu_proc_rows[:3]
                gpu_body.append("GPU PROCS")
                for row in compact_gpu_proc_rows:
                    name = truncate_middle(row.name, 12)
                    gpu_body.append(
                        f"[magenta]{row.gpu}[/magenta] [yellow]{row.mem_mib:>4.0f}M[/yellow] [cyan]{row.cpu_pct:>3.0f}%[/cyan] {name}"
                    )
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
            gpu_body.append("none")
        self.gpu_box.update("\n".join(gpu_body))

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
