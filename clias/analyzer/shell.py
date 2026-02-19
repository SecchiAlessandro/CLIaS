"""Shell analyzer — classifies commands into semantic patterns via LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict

from clias.llm.client import LLMClient
from clias.llm.prompts import SHELL_CLASSIFY
from clias.observer.shell import ShellEvent


@dataclass
class ShellPattern:
    tool: str
    operation: str
    description: str
    command: str
    flags_used: list[str]
    is_destructive: bool
    original_event: ShellEvent | None = None


class ShellAnalyzer:
    """Classifies shell events into higher-level ShellPatterns."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def classify_event(self, event: ShellEvent) -> ShellPattern:
        prompt = SHELL_CLASSIFY.format(
            command=event.command,
            cwd=event.cwd,
            exit_code=event.exit_code,
            stdout=event.stdout[:2000],
            stderr=event.stderr[:1000],
        )
        raw = self.llm.ask(prompt, system="You are a precise software analyst. Respond only in valid JSON.")
        data = self._parse_json(raw)
        return ShellPattern(
            tool=data.get("tool", "unknown"),
            operation=data.get("operation", "unknown"),
            description=data.get("description", ""),
            command=event.command,
            flags_used=data.get("flags_used", []),
            is_destructive=data.get("is_destructive", False),
            original_event=event,
        )

    def classify_batch(self, events: list[ShellEvent]) -> list[ShellPattern]:
        return [self.classify_event(e) for e in events]

    def group_by_tool(self, patterns: list[ShellPattern]) -> dict[str, list[ShellPattern]]:
        groups: dict[str, list[ShellPattern]] = {}
        for p in patterns:
            groups.setdefault(p.tool, []).append(p)
        return groups

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "tool": "unknown",
                "operation": "unknown",
                "description": raw[:200],
                "flags_used": [],
                "is_destructive": False,
            }
