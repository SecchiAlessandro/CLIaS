"""Tests for the skill generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clias.specgen.schema import (
    ArgSpec,
    Capability,
    CommandSpec,
    Example,
    FlagSpec,
    ToolSpec,
    Workflow,
    WorkflowStep,
)
from clias.skillgen.generator import SkillGenerator


@pytest.fixture
def sample_spec() -> ToolSpec:
    return ToolSpec(
        name="git",
        description="Distributed version control system",
        version="2.40.0",
        capabilities=[
            Capability(
                name="branching",
                description="Create and manage branches",
                related_commands=["git branch", "git checkout"],
            ),
            Capability(
                name="staging",
                description="Stage changes for commit",
                related_commands=["git add"],
            ),
        ],
        commands=[
            CommandSpec(
                canonical="git branch",
                description="List, create, or delete branches",
                arguments=[ArgSpec(name="branch-name", description="Name of branch", required=False)],
                flags=[
                    FlagSpec(flag="-d, --delete", description="Delete a branch"),
                    FlagSpec(flag="-a, --all", description="List all branches"),
                ],
                examples=["git branch feature-x", "git branch -d old-branch"],
                gui_equivalent="Branch manager panel",
            ),
            CommandSpec(
                canonical="git checkout",
                description="Switch branches or restore files",
                arguments=[ArgSpec(name="target", description="Branch or file", required=True)],
                flags=[FlagSpec(flag="-b", description="Create and switch to new branch")],
            ),
            CommandSpec(
                canonical="git add",
                description="Add file contents to the index",
                arguments=[ArgSpec(name="pathspec", description="Files to add", required=True)],
                flags=[
                    FlagSpec(flag="-A, --all", description="Add all changes"),
                    FlagSpec(flag="-p, --patch", description="Interactively select hunks"),
                ],
            ),
        ],
        workflows=[
            Workflow(
                name="Feature branch",
                description="Create and work on a feature branch",
                steps=[
                    WorkflowStep(description="Create branch", command_ref="git checkout", typical_args={"-b": "feature-x"}),
                    WorkflowStep(description="Stage changes", command_ref="git add", typical_args={"pathspec": "."}),
                ],
            ),
        ],
        examples=[
            Example(description="Create a new branch", command="git checkout -b feature-x"),
            Example(description="Stage all files", command="git add -A"),
        ],
    )


@pytest.fixture
def cli_script(tmp_path: Path) -> Path:
    script = tmp_path / "git_cli.py"
    script.write_text("#!/usr/bin/env python3\n# Generated CLI\n")
    return script


class TestSkillGenerator:
    def test_skill_name(self, sample_spec: ToolSpec, cli_script: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        assert gen._skill_name() == "git-cli"

    def test_skill_name_multiword(self, cli_script: Path) -> None:
        spec = ToolSpec(name="Docker Compose", description="Container orchestration")
        gen = SkillGenerator(spec, cli_script)
        assert gen._skill_name() == "docker-compose-cli"

    def test_skill_name_special_chars(self, cli_script: Path) -> None:
        spec = ToolSpec(name="my_tool!v2", description="A tool")
        gen = SkillGenerator(spec, cli_script)
        name = gen._skill_name()
        assert re.match(r"^[a-z0-9-]+$", name), f"Invalid skill name: {name}"

    def test_generate_directory_structure(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        assert skill_dir.exists()
        assert (skill_dir / "SKILL.md").is_file()
        assert (skill_dir / "scripts" / "git_cli.py").is_file()
        assert (skill_dir / "references" / "tool_spec.json").is_file()
        assert (skill_dir / "references" / "command_reference.md").is_file()

    def test_skill_md_frontmatter(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert content.startswith("---\n")
        # Extract frontmatter
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md should have frontmatter delimiters"
        frontmatter = parts[1].strip()
        assert "name: git-cli" in frontmatter
        assert "description:" in frontmatter

    def test_skill_md_body_has_capabilities(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Capabilities" in content
        assert "### branching" in content
        assert "### staging" in content
        assert "`git branch`" in content
        assert "`git add`" in content

    def test_skill_md_body_has_workflows(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Workflows" in content
        assert "Feature branch" in content

    def test_skill_md_body_has_examples(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Quick Examples" in content
        assert "git checkout -b feature-x" in content

    def test_command_reference_all_commands(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        ref = (skill_dir / "references" / "command_reference.md").read_text()
        assert "## `git branch`" in ref
        assert "## `git checkout`" in ref
        assert "## `git add`" in ref
        # Check argument and flag docs
        assert "branch-name" in ref
        assert "-d, --delete" in ref
        assert "### Examples" in ref
        assert "GUI equivalent" in ref

    def test_tool_spec_json_valid(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        spec_json = (skill_dir / "references" / "tool_spec.json").read_text()
        data = json.loads(spec_json)
        assert data["name"] == "git"
        assert len(data["commands"]) == 3

    def test_cli_script_copied(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        copied = (skill_dir / "scripts" / "git_cli.py").read_text()
        assert "Generated CLI" in copied

    def test_no_capabilities_flat_commands(self, cli_script: Path, tmp_path: Path) -> None:
        spec = ToolSpec(
            name="mytool",
            description="A simple tool",
            commands=[
                CommandSpec(canonical="mytool run", description="Run something"),
                CommandSpec(canonical="mytool stop", description="Stop something"),
            ],
        )
        gen = SkillGenerator(spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Capabilities" not in content
        assert "## Commands" in content
        assert "`mytool run`" in content

    def test_no_workflows_omitted(self, cli_script: Path, tmp_path: Path) -> None:
        spec = ToolSpec(name="mytool", description="A tool")
        gen = SkillGenerator(spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Workflows" not in content

    def test_no_examples_omitted(self, cli_script: Path, tmp_path: Path) -> None:
        spec = ToolSpec(name="mytool", description="A tool")
        gen = SkillGenerator(spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        assert "## Quick Examples" not in content

    def test_description_truncation(self, cli_script: Path, tmp_path: Path) -> None:
        long_desc = "A" * 1100
        spec = ToolSpec(name="mytool", description=long_desc)
        gen = SkillGenerator(spec, cli_script)
        skill_dir = gen.generate(tmp_path / "skills")

        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        frontmatter = parts[1]
        # Description in frontmatter should be truncated
        assert "..." in frontmatter
        # The description line in frontmatter should not exceed 1024 chars
        for line in frontmatter.splitlines():
            if line.startswith("description:"):
                desc_value = line[len("description:"):].strip()
                assert len(desc_value) <= 1024

    def test_idempotent_regeneration(self, sample_spec: ToolSpec, cli_script: Path, tmp_path: Path) -> None:
        gen = SkillGenerator(sample_spec, cli_script)
        skills_dir = tmp_path / "skills"

        path1 = gen.generate(skills_dir)
        content1 = (path1 / "SKILL.md").read_text()

        path2 = gen.generate(skills_dir)
        content2 = (path2 / "SKILL.md").read_text()

        assert path1 == path2
        assert content1 == content2


# Need re for the special chars test
import re
