"""
Pre-flight check for the PC: run this BEFORE starting the server (server must be stopped,
because this script uses the microphone and speakers itself).

  python tools/check_setup.py            full check incl. microphone + speech recognition + voice output
  python tools/check_setup.py --quick    skip the slow/interactive voice tests

It also downloads the wake-word and Whisper models, so the first real start is fast.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.platform == "win32":
    import os
    os.system("")

G, R, Y, C, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m"
results: list[tuple[str, str]] = []


def report(name: str, status: str, detail: str = "") -> None:
    color = {"PASS": G, "FAIL": R, "WARN": Y, "SKIP": D}[status]
    results.append((name, status))
    print(f"  [{color}{status}{X}] {name}  {D}{detail}{X}")


def section(title: str) -> None:
    print(f"\n{C}== {title} =={X}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip microphone / STT / TTS tests")
    ap.add_argument("--no-sound", action="store_true", help="don't play the TTS test through the speakers")
    args = ap.parse_args()

    from config import get_settings
    s = get_settings()

    section("Python & packages")
    v = sys.version_info
    report(f"Python {v.major}.{v.minor}.{v.micro}", "PASS" if v >= (3, 11) else "FAIL",
           "" if v >= (3, 11) else "need Python 3.11 or newer")
    for mod, pip_name in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("httpx", "httpx"),
                          ("websockets", "websockets"), ("psutil", "psutil"), ("pynvml", "nvidia-ml-py"),
                          ("numpy", "numpy"), ("sounddevice", "sounddevice"), ("miniaudio", "miniaudio"),
                          ("openwakeword", "openwakeword"), ("faster_whisper", "faster-whisper"),
                          ("edge_tts", "edge-tts"), ("pystray", "pystray")]:
        try:
            importlib.import_module(mod)
            report(f"import {mod}", "PASS")
        except Exception as exc:
            report(f"import {mod}", "FAIL", f"pip install {pip_name}  ({exc})")

    section("Hardware telemetry")
    from telemetry import TelemetryCollector
    t = TelemetryCollector()
    snap = t.snapshot()
    report("CPU / RAM", "PASS", f"CPU {snap['cpu_percent']}%  RAM {snap['ram_percent']}% of {snap['ram_total_gb']} GB")
    if t.gpu_available:
        g = snap["gpu"]
        report("NVIDIA GPU", "PASS", f"{g['name']}  {g['util_percent']}% util  VRAM {g['vram_used_gb']}/{g['vram_total_gb']} GB")
    else:
        report("NVIDIA GPU", "FAIL", t.gpu_error or "not found")

    section("Local AI (Ollama)")
    from llm import OllamaClient
    llm = OllamaClient(s.ollama_url, s.model_normal, s.ollama_timeout)
    h = asyncio.run(llm.health())
    if not h["reachable"]:
        report("Ollama running", "FAIL", "install from https://ollama.com and start it")
    else:
        report("Ollama running", "PASS", s.ollama_url)
        installed = set(h["models"])
        full = lambda m: m if ":" in m else f"{m}:latest"
        for role, model in (("Normal mode model", s.model_normal), ("Gaming mode model", s.model_gaming),
                            ("Fallback model", s.model_fallback)):
            if full(model) in installed:
                report(f"{role} {model}", "PASS")
            else:
                report(f"{role} {model}", "FAIL" if role != "Fallback model" else "WARN", f"run:  ollama pull {model}")
        from assistant import INTENT_SCHEMA, SYSTEM_PROMPT
        for model in (s.model_gaming, s.model_normal):
            if full(model) not in installed:
                continue
            llm.model = model
            t0 = time.time()
            try:
                asyncio.run(llm.warm(model))
                load_s = time.time() - t0
                t1 = time.time()
                out = asyncio.run(llm.chat([{"role": "system", "content": SYSTEM_PROMPT},
                                            {"role": "user", "content": "open notepad"}],
                                           schema=INTENT_SCHEMA, think=False))
                report(f"{model} answers (thinking off)", "PASS" if '"open_app"' in out.replace(" ", "") else "WARN",
                       f"load {load_s:.1f}s, reply {time.time() - t1:.1f}s: {out[:70]}")
            except Exception as exc:
                report(f"{model} answers", "FAIL", str(exc))
            finally:
                asyncio.run(llm.unload(model))     # leave VRAM free; Kageon loads what it needs
        if t.gpu_available:
            free, total = t.vram_info()
            free_gb = free / 1024 ** 3
            report("Free VRAM right now", "PASS",
                   f"{free_gb:.1f} of {total / 1024 ** 3:.1f} GB (Kageon switches to gaming mode when a game "
                   f"leaves less room than the normal model needs + {s.vram_headroom_gb} GB)")

    section("Windows app discovery")
    from executor import IS_WINDOWS, AppIndex
    if IS_WINDOWS:
        idx = AppIndex()
        n = idx.refresh()
        report("Start Menu scan", "PASS" if n > 10 else "WARN", f"{n} apps  {'; '.join(idx.errors)}")
        m = idx.match("notepad")
        report("Match 'notepad'", "PASS" if m.status == "match" else "WARN", m.best.name if m.best else m.status)
        sample = ", ".join(a["name"] for a in idx.search("")[:8])
        print(f"  {D}e.g. {sample} ...{X}")
    else:
        report("Start Menu scan", "SKIP", "not Windows")

    section("Voice")
    if args.quick:
        report("Voice tests", "SKIP", "--quick")
    else:
        voice_checks(s, args.no_sound)

    passed = sum(1 for _, st in results if st == "PASS")
    failed = [n for n, st in results if st == "FAIL"]
    print(f"\n{G if not failed else R}{passed} passed, {len(failed)} failed{X}")
    for n in failed:
        print(f"   {R}- {n}{X}")
    return 1 if failed else 0


def voice_checks(s, no_sound: bool) -> None:
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as exc:
        report("Audio system", "FAIL", str(exc))
        return

    # microphones
    try:
        default_in = sd.query_devices(kind="input")
        report("Default microphone", "PASS", default_in["name"])
        ins = [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        print(f"  {D}Input devices (use the number in MIC_DEVICE=... in .env to pick one):{X}")
        for line in ins[:15]:
            print(f"     {D}{line}{X}")
    except Exception as exc:
        report("Default microphone", "FAIL", str(exc))
        return

    # wake word
    try:
        from openwakeword.model import Model
        from openwakeword.utils import download_models
        from config import resolve_wake_model
        model, phrase, custom = resolve_wake_model(s.wake_word_model)
        if not custom:
            download_models([model])
        Model(wakeword_models=[model], inference_framework="onnx")
        if custom:
            report(f"Wake word '{phrase}'", "PASS", model)
        else:
            report(f"Wake word '{phrase}'", "WARN", "temporary -- train 'Hey Kageon' (see models/README.md)")
    except Exception as exc:
        report("Wake word model", "FAIL", str(exc))
        phrase = "Hey Kageon"

    # Whisper
    from voice import STT, TTS
    stt = STT(s.whisper_model, s.whisper_device, s.speech_language)
    t0 = time.time()
    print(f"  {D}Loading Whisper '{s.whisper_model}' (first time downloads the model, can take a few minutes)...{X}")
    try:
        stt.load()
        report("Speech-to-text (Whisper)", "PASS", f"{s.whisper_model} on {stt.device.upper()} ({time.time() - t0:.0f}s)")
    except Exception as exc:
        report("Speech-to-text (Whisper)", "FAIL", str(exc))
        stt = None

    # mic + STT live test
    if stt:
        input(f"\n  {C}Press Enter, then say something like \"{phrase}, open Notepad\" (5 seconds)...{X}")
        try:
            audio = sd.rec(int(5 * 16000), samplerate=16000, channels=1, dtype="int16",
                           device=int(s.mic_device) if s.mic_device.isdigit() else (s.mic_device or None))
            sd.wait()
            level = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
            report("Microphone level", "PASS" if level > 150 else "WARN",
                   f"RMS {level:.0f}" + ("" if level > 150 else " (very quiet -- check mic / Windows input volume)"))
            t1 = time.time()
            text, lang = stt.transcribe(audio[:, 0].astype(np.float32) / 32768.0)
            report("Transcription", "PASS" if text else "WARN", f"[{lang}] \"{text}\" ({time.time() - t1:.1f}s)")
        except Exception as exc:
            report("Microphone recording", "FAIL", str(exc))

    # TTS
    try:
        tts = TTS(s.tts_voice, s.tts_voice_arabic)
        mp3 = asyncio.run(tts.synthesize("All systems online. Kageon voice check complete."))
        report("Text-to-speech (edge-tts)", "PASS", f"{len(mp3) // 1024} KB, voice {s.tts_voice}")
        if not no_sound:
            tts.play_mp3(mp3)
            ans = input(f"  {C}Did you hear Kageon speak? [y/n] {X}").strip().lower()
            report("Speaker playback", "PASS" if ans.startswith("y") else "FAIL",
                   "" if ans.startswith("y") else "check Windows default output device")
    except Exception as exc:
        report("Text-to-speech (edge-tts)", "FAIL", f"{exc} (edge-tts needs internet)")


if __name__ == "__main__":
    sys.exit(main())
