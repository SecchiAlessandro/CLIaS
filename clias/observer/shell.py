"""Shell session observer — records terminal commands and their output."""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import sys
import re
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ShellEvent:
    timestamp: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    cwd: str


class ShellObserver:
    """Records a shell session by wrapping the user's shell in a PTY."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.output_dir / "shell_events.jsonl"
        self.raw_log = self.output_dir / "raw_session.log"
        self._events: list[ShellEvent] = []

    def record_command(self, command: str, shell: str = "/bin/bash") -> ShellEvent:
        """Execute a single command and record its output."""
        cwd = os.getcwd()
        start = datetime.now(timezone.utc)
        result = subprocess.run(
            [shell, "-c", command],
            capture_output=True,
            text=True,
            timeout=300,
        )
        event = ShellEvent(
            timestamp=start.isoformat(),
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout[:10_000],
            stderr=result.stderr[:5_000],
            cwd=cwd,
        )
        self._events.append(event)
        self._append_event(event)
        return event

    def record_interactive_session(self, shell: str | None = None) -> list[ShellEvent]:
        """Start an interactive shell session and record everything.

        This spawns a PTY-wrapped shell. The user interacts normally.
        When the session ends (exit or Ctrl-D), the raw transcript is parsed
        into ShellEvent records.
        """
        shell = shell or os.environ.get("SHELL", "/bin/bash")
        raw_output = bytearray()

        def _read(fd: int) -> bytes:
            data = os.read(fd, 1024)
            raw_output.extend(data)
            return data

        print(f"[CLIaS] Recording shell session. Type 'exit' or Ctrl-D to stop.")
        pty.spawn([shell], _read)
        print(f"\n[CLIaS] Session ended. Parsing transcript...")

        self.raw_log.write_bytes(bytes(raw_output))
        events = self._parse_raw_transcript(raw_output.decode("utf-8", errors="replace"))
        self._events.extend(events)
        for ev in events:
            self._append_event(ev)
        return events

    def load_from_script_output(self, script_file: Path) -> list[ShellEvent]:
        """Parse a file produced by the `script` command."""
        text = script_file.read_text(errors="replace")
        events = self._parse_raw_transcript(text)
        self._events.extend(events)
        for ev in events:
            self._append_event(ev)
        return events

    def get_events(self) -> list[ShellEvent]:
        return list(self._events)

    def _append_event(self, event: ShellEvent) -> None:
        with open(self.events_file, "a") as f:
            f.write(json.dumps(asdict(event)) + "\n")

    @staticmethod
    def _parse_raw_transcript(text: str) -> list[ShellEvent]:
        """Best-effort extraction of commands from a raw terminal transcript.

        Looks for common prompt patterns ($ or >) followed by a command.
        This is heuristic — real sessions vary widely.
        """
        events: list[ShellEvent] = []
        prompt_pattern = re.compile(r"^.*?[\$#>]\s+(.+)$", re.MULTILINE)
        matches = list(prompt_pattern.finditer(text))

        for i, match in enumerate(matches):
            cmd = match.group(1).strip()
            if not cmd or cmd in ("exit", "logout"):
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            output = text[start:end].strip()
            events.append(
                ShellEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    command=cmd,
                    exit_code=0,
                    stdout=output[:10_000],
                    stderr="",
                    cwd="",
                )
            )
        return events

    @staticmethod
    def load_events(events_file: Path) -> list[ShellEvent]:
        """Load previously recorded events from a JSONL file."""
        events = []
        with open(events_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    events.append(ShellEvent(**data))
        return events
