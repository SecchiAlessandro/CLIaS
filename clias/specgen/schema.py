"""Pydantic models for the ToolSpec — the structured representation of an observed tool."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ArgSpec(BaseModel):
    name: str
    description: str = ""
    required: bool = False


class FlagSpec(BaseModel):
    flag: str
    description: str = ""
    takes_value: bool = False


class CommandSpec(BaseModel):
    canonical: str
    description: str = ""
    arguments: list[ArgSpec] = Field(default_factory=list)
    flags: list[FlagSpec] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    gui_equivalent: str | None = None


class Capability(BaseModel):
    name: str
    description: str = ""
    related_commands: list[str] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    description: str
    command_ref: str
    typical_args: dict[str, str] = Field(default_factory=dict)


class Workflow(BaseModel):
    name: str
    description: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)


class Example(BaseModel):
    description: str
    command: str


class EndpointSpec(BaseModel):
    http_method: str              # GET, POST, PUT, DELETE, PATCH
    path: str                     # /repos/{owner}/{repo}/issues
    description: str = ""
    query_params: list[str] = Field(default_factory=list)
    request_body_sample: dict | None = None
    response_schema_sample: dict | None = None
    source_command: str = ""


class InteractionMethod(BaseModel):
    """Describes how a tool can be interacted with beyond plain CLI."""

    method: str  # "cli", "rest_api", "grpc", "websocket", "dbus", "ipc", "sdk"
    description: str = ""
    base_url: str | None = None
    auth_type: str | None = None  # "api_key", "oauth2", "token", "basic", "none"
    auth_env_var: str | None = None  # e.g. "DOCKER_HOST", "GITHUB_TOKEN"
    headers: dict[str, str] = Field(default_factory=dict)
    endpoints: list[EndpointSpec] = Field(default_factory=list)
    notes: str = ""


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    version: str = "observed"
    capabilities: list[Capability] = Field(default_factory=list)
    commands: list[CommandSpec] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    interaction_methods: list[InteractionMethod] = Field(default_factory=list)

    def save_json(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2))

    def save_yaml(self, path: Path) -> None:
        path.write_text(yaml.dump(self.model_dump(), default_flow_style=False, sort_keys=False))

    @classmethod
    def load_json(cls, path: Path) -> ToolSpec:
        return cls.model_validate_json(path.read_text())

    @classmethod
    def load_yaml(cls, path: Path) -> ToolSpec:
        data = yaml.safe_load(path.read_text())
        return cls.model_validate(data)

    @classmethod
    def load(cls, path: Path) -> ToolSpec:
        if path.suffix in (".yaml", ".yml"):
            return cls.load_yaml(path)
        return cls.load_json(path)

    def commands_summary(self) -> str:
        lines = []
        for cmd in self.commands:
            args = " ".join(f"<{a.name}>" for a in cmd.arguments[:4])
            flags = " ".join(f.flag for f in cmd.flags[:8])
            detail = " ".join(filter(None, [args, flags]))
            lines.append(f"  {cmd.canonical} {detail}  — {cmd.description}")
        return "\n".join(lines)

    def merge(self, other: ToolSpec) -> ToolSpec:
        """Merge another spec into this one, adding new commands/capabilities."""
        existing_cmds = {c.canonical for c in self.commands}
        for cmd in other.commands:
            if cmd.canonical not in existing_cmds:
                self.commands.append(cmd)

        existing_caps = {c.name for c in self.capabilities}
        for cap in other.capabilities:
            if cap.name not in existing_caps:
                self.capabilities.append(cap)

        existing_workflows = {w.name for w in self.workflows}
        for wf in other.workflows:
            if wf.name not in existing_workflows:
                self.workflows.append(wf)

        existing_methods = {(m.method, m.base_url) for m in self.interaction_methods}
        for im in other.interaction_methods:
            if (im.method, im.base_url) not in existing_methods:
                self.interaction_methods.append(im)

        return self
