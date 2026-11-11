from telemetry import TelemetryCollector, _fmt_duration


def test_snapshot_shape_and_ranges():
    t = TelemetryCollector()
    s = t.snapshot()
    for key in ("cpu_percent", "ram_percent", "gpu_percent", "vram_percent", "clock", "date",
                "system_uptime_seconds", "server_uptime_seconds", "gpu"):
        assert key in s
    assert 0 <= s["cpu_percent"] <= 100
    assert 0 < s["ram_percent"] <= 100
    assert s["ram_total_gb"] > 0
    assert s["system_uptime_seconds"] > 0
    assert len(s["clock"]) == 8 and s["clock"][2] == ":"


def test_gpu_missing_is_graceful():
    t = TelemetryCollector()
    s = t.snapshot()
    if not t.gpu_available:
        assert s["gpu"]["available"] is False
        assert s["gpu_percent"] is None and s["vram_percent"] is None
    else:  # on the real PC with the RTX card
        assert 0 <= s["gpu_percent"] <= 100
        assert 0 <= s["vram_percent"] <= 100
        assert s["gpu"]["vram_total_gb"] > 1


def test_spoken_summary():
    assert "CPU is at" in TelemetryCollector().spoken_summary()


def test_duration_format():
    assert _fmt_duration(59) == "00:00:59"
    assert _fmt_duration(3 * 86400 + 3661) == "3d 01:01:01"
