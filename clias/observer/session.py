"""Unified session manager coordinating shell and screen observers."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from clias.observer.shell import ShellObserver, ShellEvent
from clias.observer.screen import ScreenObserver


@dataclass
class SessionManifest:
    session_id: str
    started_at: str
    ended_at: str | None = None
    shell_events_file: str = ""
    screenshot_dir: str = ""
    screenshot_count: int = 0
    shell_event_count: int = 0
    metadata: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> SessionManifest:
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


class Session:
    """Manages a combined shell + screen observation session."""

    def __init__(
        self,
        output_dir: Path,
        enable_screen: bool = False,
        screenshot_interval: float = 2.0,
    ) -> None:
        self.session_id = uuid.uuid4().hex[:12]
        self.session_dir = output_dir / f"session_{self.session_id}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.shell_observer = ShellObserver(self.session_dir)
        self.screen_observer: ScreenObserver | None = None
        self._screen_thread: threading.Thread | None = None
        self._screen_paths: list[Path] = []

        if enable_screen:
            self.screen_observer = ScreenObserver(
                self.session_dir, interval=screenshot_interval
            )

        self.manifest = SessionManifest(
            session_id=self.session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            shell_events_file=str(self.shell_observer.events_file),
        )
        if self.screen_observer:
            self.manifest.screenshot_dir = str(self.screen_observer.output_dir)

    def start_screen_capture(self) -> None:
        if not self.screen_observer:
            return

        def _capture() -> None:
            self._screen_paths = self.screen_observer.run()  # type: ignore[union-attr]

        self._screen_thread = threading.Thread(target=_capture, daemon=True)
        self._screen_thread.start()

    def stop_screen_capture(self) -> None:
        if self.screen_observer:
            self.screen_observer.stop()
        if self._screen_thread:
            self._screen_thread.join(timeout=5)

    def record_command(self, command: str) -> ShellEvent:
        return self.shell_observer.record_command(command)

    def record_interactive(self) -> list[ShellEvent]:
        self.start_screen_capture()
        try:
            events = self.shell_observer.record_interactive_session()
        finally:
            self.stop_screen_capture()
        return events

    def finalize(self) -> SessionManifest:
        self.manifest.ended_at = datetime.now(timezone.utc).isoformat()
        self.manifest.shell_event_count = len(self.shell_observer.get_events())
        if self.screen_observer:
            self.manifest.screenshot_count = len(self.screen_observer.get_saved_frames())
        manifest_path = self.session_dir / "manifest.json"
        self.manifest.save(manifest_path)
        return self.manifest
