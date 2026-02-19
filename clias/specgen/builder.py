"""Spec builder — transforms analyzed patterns into a validated ToolSpec."""

from __future__ import annotations

import json
from dataclasses import asdict

from clias.llm.client import LLMClient
from clias.llm.prompts import SPEC_FILL
from clias.analyzer.shell import ShellPattern
from clias.analyzer.merger import CorrelatedAction
from clias.specgen.schema import (
    ToolSpec,
    Capability,
    CommandSpec,
    ArgSpec,
    FlagSpec,
    Workflow,
    WorkflowStep,
    Example,
    InteractionMethod,
)


INTERACTION_DETECT_PROMPT = """\
Given the following CLI tool name and observed commands, determine what
interaction methods this tool supports beyond basic CLI usage.

Tool: {tool_name}
Observed commands:
{commands}

Consider: Does this tool use REST APIs, gRPC, WebSockets, SDK libraries,
Docker sockets, D-Bus, config files with API keys, OAuth flows, or other
non-trivial interaction methods?

Respond in JSON as a list:
[
  {{
    "method": "<cli|rest_api|grpc|websocket|dbus|ipc|sdk>",
    "description": "<how this interaction method is used>",
    "base_url": "<base URL if applicable, else null>",
    "auth_type": "<api_key|oauth2|token|basic|none|null>",
    "auth_env_var": "<env var name for credentials, or null>",
    "notes": "<any extra details>"
  }}
]
"""


class SpecBuilder:
    """Builds a ToolSpec from analyzed shell patterns and optional UI correlations."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def build_from_patterns(self, patterns: list[ShellPattern]) -> ToolSpec:
        """Build a spec from shell patterns only (no vision data)."""
        if not patterns:
            return ToolSpec(name="unknown", description="No patterns observed")

        tool_name = self._detect_tool_name(patterns)
        patterns_json = json.dumps(
            [
                {
                    "tool": p.tool,
                    "operation": p.operation,
                    "command": p.command,
                    "description": p.description,
                    "flags_used": p.flags_used,
                    "is_destructive": p.is_destructive,
                }
                for p in patterns
            ],
            indent=2,
        )
        prompt = SPEC_FILL.format(patterns=patterns_json)
        raw = self.llm.ask(
            prompt,
            system="You are a CLI documentation expert. Respond only in valid JSON.",
        )
        spec = self._parse_spec(raw, fallback_name=tool_name)
        spec.interaction_methods = self._detect_interactions(tool_name, patterns)
        return spec

    def build_from_correlated(self, actions: list[CorrelatedAction]) -> ToolSpec:
        """Build a spec from correlated shell+UI data."""
        patterns = [a.pattern for a in actions]
        spec = self.build_from_patterns(patterns)

        for action in actions:
            if action.gui_equivalent:
                for cmd in spec.commands:
                    if cmd.canonical == action.command or action.command.startswith(
                        cmd.canonical
                    ):
                        cmd.gui_equivalent = action.gui_equivalent
                        break
        return spec

    def _detect_tool_name(self, patterns: list[ShellPattern]) -> str:
        tool_counts: dict[str, int] = {}
        for p in patterns:
            tool_counts[p.tool] = tool_counts.get(p.tool, 0) + 1
        if not tool_counts:
            return "unknown"
        return max(tool_counts, key=tool_counts.get)  # type: ignore[arg-type]

    def _detect_interactions(
        self, tool_name: str, patterns: list[ShellPattern]
    ) -> list[InteractionMethod]:
        commands_text = "\n".join(f"  - {p.command}" for p in patterns[:20])
        prompt = INTERACTION_DETECT_PROMPT.format(
            tool_name=tool_name, commands=commands_text
        )
        raw = self.llm.ask(
            prompt,
            system="You are a software integration analyst. Respond only in valid JSON.",
        )
        items = self._parse_json_list(raw)
        methods = []
        for item in items:
            methods.append(
                InteractionMethod(
                    method=item.get("method", "cli"),
                    description=item.get("description", ""),
                    base_url=item.get("base_url"),
                    auth_type=item.get("auth_type"),
                    auth_env_var=item.get("auth_env_var"),
                    notes=item.get("notes", ""),
                )
            )
        return methods

    def _parse_spec(self, raw: str, fallback_name: str = "unknown") -> ToolSpec:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ToolSpec(name=fallback_name, description="Failed to parse spec from LLM")

        try:
            return ToolSpec.model_validate(data)
        except Exception:
            return self._manual_parse(data, fallback_name)

    def _manual_parse(self, data: dict, fallback_name: str) -> ToolSpec:
        """Fallback parser when Pydantic validation fails."""
        commands = []
        for c in data.get("commands", []):
            commands.append(
                CommandSpec(
                    canonical=c.get("canonical", ""),
                    description=c.get("description", ""),
                    arguments=[ArgSpec(**a) for a in c.get("arguments", [])],
                    flags=[FlagSpec(**f) for f in c.get("flags", [])],
                    examples=c.get("examples", []),
                    gui_equivalent=c.get("gui_equivalent"),
                )
            )

        capabilities = []
        for cap in data.get("capabilities", []):
            capabilities.append(
                Capability(
                    name=cap.get("name", ""),
                    description=cap.get("description", ""),
                    related_commands=cap.get("related_commands", []),
                )
            )

        workflows = []
        for wf in data.get("workflows", []):
            steps = [
                WorkflowStep(
                    description=s.get("description", ""),
                    command_ref=s.get("command_ref", ""),
                    typical_args=s.get("typical_args", {}),
                )
                for s in wf.get("steps", [])
            ]
            workflows.append(
                Workflow(name=wf.get("name", ""), description=wf.get("description", ""), steps=steps)
            )

        examples = [
            Example(description=e.get("description", ""), command=e.get("command", ""))
            for e in data.get("examples", [])
        ]

        return ToolSpec(
            name=data.get("name", fallback_name),
            description=data.get("description", ""),
            version=data.get("version", "observed"),
            capabilities=capabilities,
            commands=commands,
            workflows=workflows,
            examples=examples,
        )

    @staticmethod
    def _parse_json_list(raw: str) -> list[dict]:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        try:
            result = json.loads(raw)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            return []
