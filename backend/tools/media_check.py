"""Shows what Kageon sees playing on this PC, once a second for 15 seconds.

  python tools/media_check.py

Start a song in Spotify or a YouTube video, then pause and play it while this runs.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # backend/

from media_watch import MediaWatcher  # noqa: E402


async def main() -> None:
    watcher = MediaWatcher()
    last = None
    for _ in range(15):
        state = await watcher.read()
        if not state.get("available"):
            print("Media state is NOT available. Run setup.bat again to install the Windows media packages.")
            return
        if state != last:
            if not state["active"]:
                print("Nothing is playing (no media app open).")
            else:
                status = "PLAYING" if state["playing"] else "paused "
                song = " - ".join(x for x in (state["title"], state["artist"]) if x) or "(no song name)"
                print(f"{status}  {song}  [{state['app']}]")
            last = state
        await asyncio.sleep(1)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
