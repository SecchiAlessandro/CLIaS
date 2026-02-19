"""Tests for the shell observer."""

import json
from pathlib import Path

from clias.observer.shell import ShellObserver, ShellEvent


class TestShellObserver:
    def test_record_command(self, tmp_path: Path) -> None:
        obs = ShellObserver(tmp_path / "session")
        event = obs.record_command("echo hello")
        assert event.command == "echo hello"
        assert event.exit_code == 0
        assert "hello" in event.stdout

    def test_record_command_failure(self, tmp_path: Path) -> None:
        obs = ShellObserver(tmp_path / "session")
        event = obs.record_command("false")
        assert event.exit_code != 0

    def test_events_persisted(self, tmp_path: Path) -> None:
        obs = ShellObserver(tmp_path / "session")
        obs.record_command("echo one")
        obs.record_command("echo two")

        events = ShellObserver.load_events(obs.events_file)
        assert len(events) == 2
        assert events[0].command == "echo one"
        assert events[1].command == "echo two"

    def test_parse_raw_transcript(self) -> None:
        transcript = """\
user@host:~$ ls -la
total 0
drwxr-xr-x 2 user user 40 Jan 1 00:00 .
user@host:~$ git status
On branch main
nothing to commit
user@host:~$ exit
"""
        events = ShellObserver._parse_raw_transcript(transcript)
        assert len(events) == 2
        assert events[0].command == "ls -la"
        assert events[1].command == "git status"

    def test_get_events(self, tmp_path: Path) -> None:
        obs = ShellObserver(tmp_path / "session")
        assert obs.get_events() == []
        obs.record_command("echo test")
        assert len(obs.get_events()) == 1
