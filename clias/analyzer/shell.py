"""Shell analyzer — classifies commands into semantic patterns via LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict

from clias.llm.client import LLMClient
from clias.llm.prompts import SHELL_CLASSIFY, SHELL_CLASSIFY_API
from clias.observer.shell import ShellEvent
from clias.specgen.api_parser import is_api_command, parse_curl, parse_httpie


@dataclass
class ShellPattern:
    tool: str
    operation: str
    description: str
    command: str
    flags_used: list[str]
    is_destructive: bool
    original_event: ShellEvent | None = None
    is_api_call: bool = False
    api_http_method: str | None = None
    api_url: str | None = None
    api_request_body: dict | None = None
    api_response_sample: dict | None = None


class ShellAnalyzer:
    """Classifies shell events into higher-level ShellPatterns."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def classify_event(self, event: ShellEvent) -> ShellPattern:
        # Pre-parse API commands deterministically
        api_parsed: dict | None = None
        if is_api_command(event.command):
            first_tok = event.command.strip().split()[0]
            if first_tok == "curl":
                api_parsed = parse_curl(event.command, event.stdout)
            else:
                api_parsed = parse_httpie(event.command, event.stdout)

        if api_parsed:
            prompt = SHELL_CLASSIFY_API.format(
                command=event.command,
                cwd=event.cwd,
                exit_code=event.exit_code,
                http_method=api_parsed.get("http_method", "GET"),
                url=api_parsed.get("url", ""),
                request_body=json.dumps(api_parsed.get("request_body")) if api_parsed.get("request_body") else "none",
                stdout=event.stdout[:2000],
                stderr=event.stderr[:1000],
            )
        else:
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
            is_api_call=api_parsed is not None,
            api_http_method=api_parsed.get("http_method") if api_parsed else None,
            api_url=api_parsed.get("url") if api_parsed else None,
            api_request_body=api_parsed.get("request_body") if api_parsed else None,
            api_response_sample=api_parsed.get("response_schema") if api_parsed else None,
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
