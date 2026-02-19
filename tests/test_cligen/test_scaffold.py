"""Tests for the CLI scaffold generator."""

from pathlib import Path

from clias.cligen.scaffold import CLIScaffold
from clias.specgen.schema import (
    ToolSpec,
    Capability,
    CommandSpec,
    ArgSpec,
    FlagSpec,
    InteractionMethod,
)


def _make_spec() -> ToolSpec:
    return ToolSpec(
        name="docker",
        description="Container management tool",
        version="24.0",
        capabilities=[
            Capability(
                name="containers",
                description="Manage containers",
                related_commands=["docker run", "docker ps"],
            )
        ],
        commands=[
            CommandSpec(
                canonical="docker run",
                description="Run a container",
                arguments=[ArgSpec(name="image", description="Image name", required=True)],
                flags=[
                    FlagSpec(flag="-d", description="Detach", takes_value=False),
                    FlagSpec(flag="-p", description="Port mapping", takes_value=True),
                ],
                examples=["docker run -d nginx"],
            ),
            CommandSpec(
                canonical="docker ps",
                description="List containers",
                flags=[FlagSpec(flag="-a", description="Show all", takes_value=False)],
            ),
        ],
        interaction_methods=[
            InteractionMethod(
                method="rest_api",
                base_url="http://localhost:2375",
                auth_type="none",
                description="Docker Engine API",
            ),
        ],
    )


class TestCLIScaffold:
    def test_generate_creates_file(self, tmp_path: Path) -> None:
        spec = _make_spec()
        scaffold = CLIScaffold(spec)
        output = tmp_path / "docker_cli.py"
        result = scaffold.generate(output)
        assert result.exists()
        content = result.read_text()
        assert "docker" in content
        assert "click" in content

    def test_generated_code_has_ask_command(self, tmp_path: Path) -> None:
        spec = _make_spec()
        scaffold = CLIScaffold(spec)
        output = tmp_path / "docker_cli.py"
        scaffold.generate(output)
        content = output.read_text()
        assert "def ask(" in content
        assert "natural language" in content.lower()

    def test_generated_code_has_commands(self, tmp_path: Path) -> None:
        spec = _make_spec()
        scaffold = CLIScaffold(spec)
        output = tmp_path / "docker_cli.py"
        scaffold.generate(output)
        content = output.read_text()
        assert "docker run" in content
        assert "docker ps" in content

    def test_generated_code_has_spec_embedded(self, tmp_path: Path) -> None:
        spec = _make_spec()
        scaffold = CLIScaffold(spec)
        output = tmp_path / "docker_cli.py"
        scaffold.generate(output)
        content = output.read_text()
        assert "TOOL_SPEC" in content
        assert '"name": "docker"' in content

    def test_generated_code_is_executable(self, tmp_path: Path) -> None:
        import os
        spec = _make_spec()
        scaffold = CLIScaffold(spec)
        output = tmp_path / "docker_cli.py"
        scaffold.generate(output)
        assert os.access(output, os.X_OK)
