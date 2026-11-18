"""Checks whether Kageon can read this PC's notifications, for 30 seconds.

  python tools/notify_check.py

Windows may ask "Let Python access your notifications?" -- answer Yes.
While it runs, get a notification (send yourself a Discord message, or finish a download in Steam).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/

from notify_watch import NotificationWatcher  # noqa: E402


async def main() -> None:
    w = NotificationWatcher()
    await w.poll()
    if w.status == "unavailable":
        print("NOT AVAILABLE: the Windows packages are missing or this Windows can't share notifications.")
        print("Run setup.bat again, then try once more. If it still fails, send Claude this output.")
        return
    if w.status == "denied":
        print("DENIED: Windows said no. Open Settings > Privacy & security > Notifications,")
        print("turn on access for apps, then try again. If there's no switch for it, send Claude this output.")
        return
    print("OK: Kageon can read notifications.")
    if w.apps:
        print("Apps already in your notification center:", ", ".join(w.apps))
    print("Waiting 30 seconds for a new notification...")
    for _ in range(30):
        for n in await w.poll():
            print(f"  NEW  [{n['app']}]  {n['title']}  {n['text'][:60]}")
        await asyncio.sleep(1)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
