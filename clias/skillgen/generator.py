"""Skill generator — produces a Claude Code skill directory from a ToolSpec."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from clias.specgen.schema import ToolSpec


class SkillGenerator:
    """Generates a Claude Code skill directory from a ToolSpec and CLI script."""

    def __init__(self, spec: ToolSpec, cli_script: Path) -> None:
        self.spec = spec
        self.cli_script = cli_script

    def generate(self, skills_dir: Path) -> Path:
        """Create the full skill directory and return its path."""
        skill_dir = skills_dir / self._skill_name()

        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "scripts").mkdir()
        (skill_dir / "references").mkdir()

        (skill_dir / "SKILL.md").write_text(self._build_skill_md())
        self._copy_cli_script(skill_dir)
        self._write_references(skill_dir)

        return skill_dir

    def _skill_name(self) -> str:
        """Derive kebab-case skill name from spec name."""
        # Strip non-alphanumeric (except hyphens/spaces), then kebab-case
        cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", self.spec.name)
        parts = cleaned.lower().split()
        name = "-".join(parts)
        if not name.endswith("-cli"):
            name = f"{name}-cli"
        return name

    def _build_skill_md(self) -> str:
        """Render the SKILL.md with frontmatter and body."""
        parts = [self._frontmatter(), self._body()]
        return "\n".join(parts) + "\n"

    def _frontmatter(self) -> str:
        name = self._skill_name()
        description = self._build_description()
        return f"---\nname: {name}\ndescription: {description}\n---"

    def _build_description(self) -> str:
        """Build description from spec, capped at 1024 chars."""
        desc = self.spec.description
        if self.spec.capabilities:
            triggers = ", ".join(c.name for c in self.spec.capabilities)
            desc = f"{desc}. Triggers: {triggers}"
        if len(desc) > 1024:
            desc = desc[:1021] + "..."
        return desc

    def _body(self) -> str:
        sections = []

        # Overview
        sections.append(f"# {self.spec.name} CLI Skill")
        sections.append(f"\n{self.spec.description}")

        # Capabilities / Commands
        if self.spec.capabilities:
            sections.append("\n## Capabilities")
            cmd_map = {c.canonical: c for c in self.spec.commands}
            for cap in self.spec.capabilities:
                sections.append(f"\n### {cap.name}")
                if cap.description:
                    sections.append(cap.description)
                for ref in cap.related_commands:
                    if ref in cmd_map:
                        cmd = cmd_map[ref]
                        sections.append(f"- `{cmd.canonical}` — {cmd.description}")
        elif self.spec.commands:
            sections.append("\n## Commands")
            for cmd in self.spec.commands:
                sections.append(f"- `{cmd.canonical}` — {cmd.description}")

        # Workflows (only if present)
        if self.spec.workflows:
            sections.append("\n## Workflows")
            for wf in self.spec.workflows:
                sections.append(f"\n### {wf.name}")
                if wf.description:
                    sections.append(wf.description)
                for i, step in enumerate(wf.steps, 1):
                    sections.append(f"{i}. `{step.command_ref}` — {step.description}")

        # Examples (only if present)
        if self.spec.examples:
            sections.append("\n## Quick Examples")
            for ex in self.spec.examples:
                sections.append(f"- **{ex.description}**: `{ex.command}`")

        # Resources
        script_name = f"{self.spec.name.lower().replace(' ', '_')}_cli.py"
        sections.append("\n## Resources")
        sections.append(f"- CLI Script: `scripts/{script_name}`")
        sections.append("- Tool Spec: `references/tool_spec.json`")
        sections.append("- Command Reference: `references/command_reference.md`")

        # Natural language usage
        sections.append("\n## Natural Language Usage")
        sections.append(
            f"You can run the CLI script to execute {self.spec.name} commands. "
            f"Use the `ask` subcommand for natural language queries."
        )

        return "\n".join(sections)

    def _build_command_reference(self) -> str:
        """Render detailed per-command documentation."""
        lines = [f"# {self.spec.name} — Command Reference\n"]

        for cmd in self.spec.commands:
            lines.append(f"## `{cmd.canonical}`")
            lines.append(f"\n{cmd.description}\n")

            if cmd.arguments:
                lines.append("### Arguments")
                for arg in cmd.arguments:
                    req = "required" if arg.required else "optional"
                    lines.append(f"- `{arg.name}` ({req}) — {arg.description}")
                lines.append("")

            if cmd.flags:
                lines.append("### Flags")
                for flag in cmd.flags:
                    value_note = " (takes value)" if flag.takes_value else ""
                    lines.append(f"- `{flag.flag}`{value_note} — {flag.description}")
                lines.append("")

            if cmd.examples:
                lines.append("### Examples")
                for ex in cmd.examples:
                    lines.append(f"- `{ex}`")
                lines.append("")

            if cmd.gui_equivalent:
                lines.append(f"**GUI equivalent:** {cmd.gui_equivalent}\n")

        return "\n".join(lines) + "\n"

    def _copy_cli_script(self, skill_dir: Path) -> None:
        """Copy the generated CLI script into scripts/."""
        script_name = f"{self.spec.name.lower().replace(' ', '_')}_cli.py"
        shutil.copy2(self.cli_script, skill_dir / "scripts" / script_name)

    def _write_references(self, skill_dir: Path) -> None:
        """Write ToolSpec JSON and command reference markdown."""
        refs_dir = skill_dir / "references"
        # ToolSpec JSON
        refs_dir.joinpath("tool_spec.json").write_text(
            self.spec.model_dump_json(indent=2)
        )
        # Command reference
        refs_dir.joinpath("command_reference.md").write_text(
            self._build_command_reference()
        )
