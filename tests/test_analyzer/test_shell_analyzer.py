"""Tests for the shell analyzer (with mocked LLM)."""

import json
from unittest.mock import MagicMock

from clias.analyzer.shell import ShellAnalyzer, ShellPattern
from clias.observer.shell import ShellEvent


def _make_event(command: str = "git status", stdout: str = "On branch main") -> ShellEvent:
    return ShellEvent(
        timestamp="2025-01-01T00:00:00+00:00",
        command=command,
        exit_code=0,
        stdout=stdout,
        stderr="",
        cwd="/home/user/project",
    )


def _mock_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.ask.return_value = response
    return llm


class TestShellAnalyzer:
    def test_classify_event(self) -> None:
        llm = _mock_llm(
            json.dumps(
                {
                    "tool": "git",
                    "operation": "check-status",
                    "description": "Shows the working tree status",
                    "flags_used": [],
                    "is_destructive": False,
                }
            )
        )
        analyzer = ShellAnalyzer(llm)
        event = _make_event()
        pattern = analyzer.classify_event(event)
        assert pattern.tool == "git"
        assert pattern.operation == "check-status"
        assert not pattern.is_destructive
        assert pattern.command == "git status"

    def test_classify_batch(self) -> None:
        responses = [
            json.dumps({"tool": "git", "operation": "check-status", "description": "status", "flags_used": [], "is_destructive": False}),
            json.dumps({"tool": "docker", "operation": "list-containers", "description": "list", "flags_used": ["-a"], "is_destructive": False}),
        ]
        llm = MagicMock()
        llm.ask.side_effect = responses
        analyzer = ShellAnalyzer(llm)
        events = [_make_event("git status"), _make_event("docker ps -a")]
        patterns = analyzer.classify_batch(events)
        assert len(patterns) == 2
        assert patterns[0].tool == "git"
        assert patterns[1].tool == "docker"

    def test_group_by_tool(self) -> None:
        analyzer = ShellAnalyzer(MagicMock())
        patterns = [
            ShellPattern(tool="git", operation="commit", description="", command="git commit", flags_used=[], is_destructive=False),
            ShellPattern(tool="git", operation="push", description="", command="git push", flags_used=[], is_destructive=False),
            ShellPattern(tool="docker", operation="run", description="", command="docker run", flags_used=[], is_destructive=False),
        ]
        groups = analyzer.group_by_tool(patterns)
        assert len(groups["git"]) == 2
        assert len(groups["docker"]) == 1

    def test_parse_json_with_markdown_fence(self) -> None:
        raw = '```json\n{"tool": "npm", "operation": "install", "description": "install deps", "flags_used": [], "is_destructive": false}\n```'
        result = ShellAnalyzer._parse_json(raw)
        assert result["tool"] == "npm"

    def test_parse_json_fallback(self) -> None:
        result = ShellAnalyzer._parse_json("not json at all")
        assert result["tool"] == "unknown"
