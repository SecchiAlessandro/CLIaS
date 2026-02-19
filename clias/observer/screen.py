"""Screen observer — captures screenshots with change detection."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import mss
from PIL import Image


class ScreenObserver:
    """Captures periodic screenshots, saving only when the screen changes."""

    def __init__(
        self,
        output_dir: Path,
        interval: float = 2.0,
        change_threshold: float = 0.05,
    ) -> None:
        self.output_dir = output_dir / "screenshots"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.change_threshold = change_threshold
        self._last_hash: str | None = None
        self._frame_index = 0
        self._running = False

    def capture_one(self) -> Path | None:
        """Take a single screenshot. Returns the path if saved (i.e. changed)."""
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        img_hash = hashlib.md5(img.tobytes()[:100_000]).hexdigest()
        if img_hash == self._last_hash:
            return None

        self._last_hash = img_hash
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        filename = f"frame_{self._frame_index:05d}_{ts}.png"
        path = self.output_dir / filename
        img.save(path, "PNG")
        self._frame_index += 1
        return path

    def run(self, duration: float | None = None) -> list[Path]:
        """Capture screenshots in a loop.

        Args:
            duration: Max seconds to run. None means run until stop() is called.

        Returns:
            List of saved screenshot paths.
        """
        self._running = True
        saved: list[Path] = []
        start = time.monotonic()

        while self._running:
            path = self.capture_one()
            if path:
                saved.append(path)
            time.sleep(self.interval)
            if duration and (time.monotonic() - start) >= duration:
                break

        return saved

    def stop(self) -> None:
        self._running = False

    def get_saved_frames(self) -> list[Path]:
        return sorted(self.output_dir.glob("frame_*.png"))
