"""Tests for the NL→Command translator (with mocked LLM)."""

from unittest.mock import MagicMock

from clias.cligen.translator import NLTranslator
from clias.specgen.schema import ToolSpec, CommandSpec, InteractionMethod


def _make_spec() -> ToolSpec:
    return ToolSpec(
        name="docker",
        description="Container management",
        commands=[
            CommandSpec(canonical="docker run", description="Run a container"),
            CommandSpec(canonical="docker ps", description="List containers"),
        ],
        interaction_methods=[
            InteractionMethod(
                method="rest_api",
                auth_type="token",
                auth_env_var="DOCKER_HOST",
                description="Docker Engine API",
            ),
        ],
    )


class TestNLTranslator:
    def test_translate_returns_commands(self) -> None:
        llm = MagicMock()
        llm.ask.return_value = "docker run -d -p 80:80 nginx"
        translator = NLTranslator(llm, _make_spec())
        commands = translator.translate("run nginx on port 80")
        assert len(commands) == 1
        assert "docker run" in commands[0]

    def test_translate_multi_line(self) -> None:
        llm = MagicMock()
        llm.ask.return_value = "docker pull redis\ndocker run -d redis"
        translator = NLTranslator(llm, _make_spec())
        commands = translator.translate("get and run redis")
        assert len(commands) == 2

    def test_translate_strips_markdown(self) -> None:
        llm = MagicMock()
        llm.ask.return_value = "```\ndocker ps -a\n```"
        translator = NLTranslator(llm, _make_spec())
        commands = translator.translate("show all containers")
        assert commands == ["docker ps -a"]

    def test_auth_context_included_in_prompt(self) -> None:
        llm = MagicMock()
        llm.ask.return_value = "docker ps"
        translator = NLTranslator(llm, _make_spec())
        translator.translate("list containers")
        call_args = llm.ask.call_args
        prompt = call_args[0][0]
        assert "DOCKER_HOST" in prompt
