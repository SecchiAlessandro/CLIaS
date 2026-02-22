"""Spec builder — transforms analyzed patterns into a validated ToolSpec."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
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
    EndpointSpec,
)
from clias.specgen.api_parser import parse_curl, parse_httpie
from clias.specgen.env_scanner import scan_env


INTERACTION_DETECT_PROMPT = """\
Given the following CLI tool name and observed commands, determine what
interaction methods this tool supports beyond basic CLI usage.

Tool: {tool_name}
Observed commands:
{commands}
{env_hints}
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
    "headers": {{"<header-name>": "<header-value-template>"}},
    "notes": "<any extra details>"
  }}
]
"""


class SpecBuilder:
    """Builds a ToolSpec from analyzed shell patterns and optional UI correlations."""

    def __init__(self, llm: LLMClient, credential_callback: Callable | None = None) -> None:
        self.llm = llm
        self.credential_callback = credential_callback

    def build_from_patterns(self, patterns: list[ShellPattern]) -> ToolSpec:
        """Build a spec from shell patterns only (no vision data)."""
        if not patterns:
            return ToolSpec(name="unknown", description="No patterns observed")

        tool_name = self._detect_tool_name(patterns)
        pattern_dicts = []
        for p in patterns:
            d: dict = {
                "tool": p.tool,
                "operation": p.operation,
                "command": p.command,
                "description": p.description,
                "flags_used": p.flags_used,
                "is_destructive": p.is_destructive,
            }
            if p.is_api_call:
                d["is_api_call"] = True
                if p.api_http_method:
                    d["api_http_method"] = p.api_http_method
                if p.api_url:
                    d["api_url"] = p.api_url
            pattern_dicts.append(d)
        patterns_json = json.dumps(pattern_dicts, indent=2)
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
        # 1. Get ground-truth env hints
        env_hints_list = scan_env()
        env_hints_text = ""
        if env_hints_list:
            lines = ["\nDetected environment credentials:"]
            for h in env_hints_list:
                lines.append(f"  - ${h['env_var']} ({h['service']}, {h['auth_type']})")
                if h["base_url"]:
                    lines.append(f"    base_url: {h['base_url']}")
            env_hints_text = "\n".join(lines) + "\n"

        # 2. Separate API vs non-API patterns
        api_patterns = [p for p in patterns if p.is_api_call]
        non_api_patterns = [p for p in patterns if not p.is_api_call]

        # 2b. Detect missing credentials: collect auth env vars referenced in commands
        found_env_vars = {h["env_var"] for h in env_hints_list}
        referenced_env_vars: dict[str, str] = {}  # env_var -> service/base_url
        for p in api_patterns:
            first_tok = p.command.strip().split()[0] if p.command.strip() else ""
            stdout = p.original_event.stdout if p.original_event else ""
            parsed = None
            if first_tok == "curl":
                parsed = parse_curl(p.command, stdout)
            elif first_tok in ("http", "https"):
                parsed = parse_httpie(p.command, stdout)
            if parsed and parsed.get("auth_env_var"):
                referenced_env_vars[parsed["auth_env_var"]] = parsed.get("base_url", "unknown")

        missing_creds = []
        for env_var, base_url in referenced_env_vars.items():
            if env_var not in found_env_vars and env_var not in os.environ:
                missing_creds.append({
                    "env_var": env_var,
                    "service": base_url,
                    "reason": "referenced in API call but not set",
                })

        if missing_creds and self.credential_callback is not None:
            self.credential_callback(missing_creds)
            # Re-scan env to pick up newly-set vars
            env_hints_list = scan_env()

        methods: list[InteractionMethod] = []

        # 3. Build InteractionMethods from API patterns grouped by base_url
        if api_patterns:
            by_base: dict[str, list[ShellPattern]] = {}
            for p in api_patterns:
                # Re-parse to get full API data
                parsed = None
                first_tok = p.command.strip().split()[0] if p.command.strip() else ""
                stdout = p.original_event.stdout if p.original_event else ""
                if first_tok == "curl":
                    parsed = parse_curl(p.command, stdout)
                elif first_tok in ("http", "https"):
                    parsed = parse_httpie(p.command, stdout)
                if parsed:
                    base = parsed.get("base_url", "unknown")
                    by_base.setdefault(base, []).append(p)

            for base_url, group in by_base.items():
                endpoints: list[EndpointSpec] = []
                all_headers: dict[str, str] = {}
                auth_env = None
                auth_type = None

                for p in group:
                    first_tok = p.command.strip().split()[0] if p.command.strip() else ""
                    stdout = p.original_event.stdout if p.original_event else ""
                    parsed = None
                    if first_tok == "curl":
                        parsed = parse_curl(p.command, stdout)
                    elif first_tok in ("http", "https"):
                        parsed = parse_httpie(p.command, stdout)
                    if not parsed:
                        continue

                    all_headers.update(parsed.get("headers", {}))
                    if parsed.get("auth_env_var"):
                        auth_env = parsed["auth_env_var"]
                    if parsed.get("auth_type"):
                        auth_type = parsed["auth_type"]

                    endpoints.append(EndpointSpec(
                        http_method=parsed.get("http_method", "GET"),
                        path=parsed.get("path_template", parsed.get("path", "/")),
                        description=p.description,
                        query_params=parsed.get("query_params", []),
                        request_body_sample=parsed.get("request_body"),
                        response_schema_sample=parsed.get("response_schema"),
                        source_command=p.command,
                    ))

                # Try to fill auth from env hints if not found in headers
                if not auth_env and env_hints_list:
                    for h in env_hints_list:
                        if h["base_url"] and h["base_url"] in base_url:
                            auth_env = h["env_var"]
                            auth_type = h["auth_type"]
                            break

                methods.append(InteractionMethod(
                    method="rest_api",
                    description=f"REST API at {base_url}",
                    base_url=base_url,
                    auth_type=auth_type,
                    auth_env_var=auth_env,
                    headers=all_headers,
                    endpoints=endpoints,
                ))

        # 4. For non-API patterns, call LLM but inject env hints
        if non_api_patterns:
            commands_text = "\n".join(f"  - {p.command}" for p in non_api_patterns[:20])
            prompt = INTERACTION_DETECT_PROMPT.format(
                tool_name=tool_name, commands=commands_text, env_hints=env_hints_text,
            )
            raw = self.llm.ask(
                prompt,
                system="You are a software integration analyst. Respond only in valid JSON.",
            )
            items = self._parse_json_list(raw)
            for item in items:
                methods.append(
                    InteractionMethod(
                        method=item.get("method", "cli"),
                        description=item.get("description", ""),
                        base_url=item.get("base_url"),
                        auth_type=item.get("auth_type"),
                        auth_env_var=item.get("auth_env_var"),
                        headers=item.get("headers", {}),
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

        # Coerce typical_args values to strings before Pydantic validation
        for wf in data.get("workflows", []):
            for step in wf.get("steps", []):
                if "typical_args" in step:
                    step["typical_args"] = self._coerce_str_dict(step["typical_args"])

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
                    typical_args=self._coerce_str_dict(s.get("typical_args", {})),
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

        interaction_methods = []
        for im in data.get("interaction_methods", []):
            endpoints = []
            for ep in im.get("endpoints", []):
                endpoints.append(EndpointSpec(
                    http_method=ep.get("http_method", "GET"),
                    path=ep.get("path", "/"),
                    description=ep.get("description", ""),
                    query_params=ep.get("query_params", []),
                    request_body_sample=ep.get("request_body_sample"),
                    response_schema_sample=ep.get("response_schema_sample"),
                    source_command=ep.get("source_command", ""),
                ))
            interaction_methods.append(InteractionMethod(
                method=im.get("method", "cli"),
                description=im.get("description", ""),
                base_url=im.get("base_url"),
                auth_type=im.get("auth_type"),
                auth_env_var=im.get("auth_env_var"),
                headers=im.get("headers", {}),
                endpoints=endpoints,
                notes=im.get("notes", ""),
            ))

        return ToolSpec(
            name=data.get("name", fallback_name),
            description=data.get("description", ""),
            version=data.get("version", "observed"),
            capabilities=capabilities,
            commands=commands,
            workflows=workflows,
            examples=examples,
            interaction_methods=interaction_methods,
        )

    @staticmethod
    def _coerce_str_dict(d: dict | None) -> dict[str, str]:
        """Coerce dict values to strings — LLMs sometimes return lists instead."""
        if not d or not isinstance(d, dict):
            return {}
        result = {}
        for k, v in d.items():
            if isinstance(v, list):
                result[k] = " ".join(str(i) for i in v)
            else:
                result[k] = str(v)
        return result

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
