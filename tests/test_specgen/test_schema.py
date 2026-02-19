"""Tests for the ToolSpec schema."""

import json
from pathlib import Path

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


def _make_spec() -> ToolSpec:
    return ToolSpec(
        name="git",
        description="Distributed version control system",
        version="2.40",
        capabilities=[
            Capability(
                name="version-control",
                description="Track changes to files",
                related_commands=["git commit", "git add"],
            )
        ],
        commands=[
            CommandSpec(
                canonical="git commit",
                description="Record changes to the repository",
                arguments=[],
                flags=[FlagSpec(flag="-m", description="Commit message", takes_value=True)],
                examples=["git commit -m 'initial'"],
            ),
            CommandSpec(
                canonical="git add",
                description="Stage files for commit",
                arguments=[ArgSpec(name="path", description="File path", required=True)],
            ),
        ],
        workflows=[
            Workflow(
                name="basic-commit",
                description="Stage and commit changes",
                steps=[
                    WorkflowStep(description="Stage files", command_ref="git add", typical_args={"path": "."}),
                    WorkflowStep(description="Commit", command_ref="git commit", typical_args={}),
                ],
            )
        ],
        examples=[Example(description="Commit all", command="git add . && git commit -m 'all'")],
        interaction_methods=[
            InteractionMethod(method="cli", description="Standard CLI usage"),
            InteractionMethod(
                method="rest_api",
                description="GitHub API",
                base_url="https://api.github.com",
                auth_type="token",
                auth_env_var="GITHUB_TOKEN",
            ),
        ],
    )


class TestToolSpec:
    def test_roundtrip_json(self, tmp_path: Path) -> None:
        spec = _make_spec()
        path = tmp_path / "spec.json"
        spec.save_json(path)
        loaded = ToolSpec.load_json(path)
        assert loaded.name == "git"
        assert len(loaded.commands) == 2
        assert loaded.commands[0].canonical == "git commit"

    def test_roundtrip_yaml(self, tmp_path: Path) -> None:
        spec = _make_spec()
        path = tmp_path / "spec.yaml"
        spec.save_yaml(path)
        loaded = ToolSpec.load_yaml(path)
        assert loaded.name == "git"
        assert len(loaded.capabilities) == 1

    def test_load_autodetects_format(self, tmp_path: Path) -> None:
        spec = _make_spec()
        json_path = tmp_path / "spec.json"
        yaml_path = tmp_path / "spec.yml"
        spec.save_json(json_path)
        spec.save_yaml(yaml_path)
        assert ToolSpec.load(json_path).name == "git"
        assert ToolSpec.load(yaml_path).name == "git"

    def test_commands_summary(self) -> None:
        spec = _make_spec()
        summary = spec.commands_summary()
        assert "git commit" in summary
        assert "git add" in summary

    def test_merge(self) -> None:
        spec1 = _make_spec()
        spec2 = ToolSpec(
            name="git",
            commands=[
                CommandSpec(canonical="git push", description="Upload commits"),
                CommandSpec(canonical="git commit", description="Duplicate"),  # should not duplicate
            ],
            capabilities=[
                Capability(name="remote-ops", description="Remote operations", related_commands=["git push"]),
            ],
        )
        merged = spec1.merge(spec2)
        assert len(merged.commands) == 3  # commit, add, push — no duplicate commit
        assert any(c.canonical == "git push" for c in merged.commands)
        assert len(merged.capabilities) == 2

    def test_interaction_methods(self) -> None:
        spec = _make_spec()
        assert len(spec.interaction_methods) == 2
        api = [m for m in spec.interaction_methods if m.method == "rest_api"][0]
        assert api.auth_env_var == "GITHUB_TOKEN"
        assert api.base_url == "https://api.github.com"
