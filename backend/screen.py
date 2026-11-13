"""
Screenshot for "what's on my screen?" -- taken only when asked, kept in memory, never saved to disk.
The image is downscaled (default: longest side 1280 px) so the vision model reads it quickly.
"""
from __future__ import annotations

import base64
import io
import logging
import re

log = logging.getLogger("screen")

SCREEN_PHRASES = [
    "my screen", "the screen", "on screen", "what am i looking at", "what's this on", "what is this on",
    "this error", "this message", "this window", "this page", "what does this say", "read this", "read it for me",
    "can you see", "do you see", "look at this", "what's in front of me",
]
_NOT_SCREEN = re.compile(r"^(open|close|launch|start|play|search|lock|turn|take a screenshot and save)\b")


def is_screen_question(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()
    if _NOT_SCREEN.match(t):
        return False
    return any(p in t for p in SCREEN_PHRASES)


class ScreenError(Exception):
    pass


def capture_screen(max_side: int = 1280, quality: int = 80) -> str:
    """Primary monitor as a base64 JPEG. Raises ScreenError with a helpful message on failure."""
    try:
        from PIL import Image, ImageGrab
    except ImportError as exc:
        raise ScreenError("Screen reading needs the Pillow package. Run setup.bat once to install it.") from exc
    try:
        img = ImageGrab.grab()
    except Exception as exc:
        raise ScreenError(f"I couldn't take a screenshot: {exc}") from exc
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    log.info("Screenshot taken (%dx%d, %d KB)", img.width, img.height, buf.tell() // 1024)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def clean_for_speech(text: str, max_chars: int = 900) -> str:
    """Strip markdown so TTS doesn't read out asterisks and hashes."""
    t = re.sub(r"[*_#`>]+", "", text or "")
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    if len(t) > max_chars:
        cut = t[:max_chars].rsplit(".", 1)[0]
        t = (cut or t[:max_chars]) + "."
    return t
