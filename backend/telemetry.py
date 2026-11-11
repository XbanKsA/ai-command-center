"""
Live hardware telemetry: CPU, RAM (psutil) + NVIDIA GPU usage / VRAM (pynvml / nvidia-ml-py).

If no NVIDIA driver/GPU is found, GPU fields are reported as None and
`gpu.available` is False -- the rest keeps working.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import psutil

log = logging.getLogger("telemetry")


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h:02d}:{m:02d}:{s:02d}" if d else f"{h:02d}:{m:02d}:{s:02d}"


class TelemetryCollector:
    def __init__(self):
        self.server_start = time.time()
        self._nvml = None
        self._gpu_handle = None
        self.gpu_name: str | None = None
        self.gpu_error: str | None = None
        self._init_gpu()
        psutil.cpu_percent(interval=None)  # prime: first call always returns 0.0

    def _init_gpu(self) -> None:
        try:
            import pynvml  # provided by the `nvidia-ml-py` package
            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() < 1:
                raise RuntimeError("no NVIDIA GPU found")
            self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(self._gpu_handle)
            self.gpu_name = name.decode() if isinstance(name, bytes) else name
            self._nvml = pynvml
            log.info("GPU telemetry enabled: %s", self.gpu_name)
        except Exception as exc:
            self.gpu_error = str(exc) or exc.__class__.__name__
            log.warning("GPU telemetry unavailable (%s) -- CPU/RAM still reported", self.gpu_error)

    @property
    def gpu_available(self) -> bool:
        return self._gpu_handle is not None

    def _gpu_snapshot(self) -> dict:
        empty = {"available": False, "name": None, "util_percent": None, "vram_percent": None,
                 "vram_used_gb": None, "vram_total_gb": None, "temperature_c": None}
        if not self._gpu_handle:
            return empty
        nv = self._nvml
        try:
            util = nv.nvmlDeviceGetUtilizationRates(self._gpu_handle)
            mem = nv.nvmlDeviceGetMemoryInfo(self._gpu_handle)
            try:
                temp = nv.nvmlDeviceGetTemperature(self._gpu_handle, nv.NVML_TEMPERATURE_GPU)
            except Exception:
                temp = None
            return {
                "available": True,
                "name": self.gpu_name,
                "util_percent": float(util.gpu),
                "vram_percent": round(mem.used / mem.total * 100, 1) if mem.total else None,
                "vram_used_gb": round(mem.used / 1024**3, 2),
                "vram_total_gb": round(mem.total / 1024**3, 2),
                "temperature_c": temp,
            }
        except Exception as exc:
            log.debug("GPU read failed: %s", exc)
            return empty

    def snapshot(self) -> dict:
        now = time.time()
        vm = psutil.virtual_memory()
        gpu = self._gpu_snapshot()
        local = datetime.now()
        system_uptime = now - psutil.boot_time()
        server_uptime = now - self.server_start
        return {
            # flat headline numbers (what the dashboard / AOD screen shows)
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": vm.percent,
            "gpu_percent": gpu["util_percent"],
            "vram_percent": gpu["vram_percent"],
            # details
            "ram_used_gb": round(vm.used / 1024**3, 2),
            "ram_total_gb": round(vm.total / 1024**3, 2),
            "gpu": gpu,
            "clock": local.strftime("%H:%M:%S"),
            "date": local.strftime("%Y-%m-%d"),
            "weekday": local.strftime("%A"),
            "timestamp": now,
            "system_uptime_seconds": int(system_uptime),
            "system_uptime": _fmt_duration(system_uptime),
            "server_uptime_seconds": int(server_uptime),
            "server_uptime": _fmt_duration(server_uptime),
        }

    def spoken_summary(self) -> str:
        t = self.snapshot()
        parts = [f"CPU is at {t['cpu_percent']:.0f} percent", f"memory at {t['ram_percent']:.0f} percent"]
        if t["gpu_percent"] is not None:
            parts.append(f"GPU at {t['gpu_percent']:.0f} percent with {t['vram_percent']:.0f} percent VRAM in use")
        return ", ".join(parts) + f". System uptime is {t['system_uptime']}."

    def close(self) -> None:
        if self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
