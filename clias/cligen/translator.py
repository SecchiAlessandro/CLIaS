"""NL→Command translator — uses an LLM to convert natural language to shell commands."""

from __future__ import annotations

from clias.llm.client import LLMClient
from clias.llm.prompts import NL_TRANSLATE
from clias.specgen.schema import ToolSpec


class NLTranslator:
    """Translates natural language requests into shell commands using a ToolSpec as context."""

    def __init__(self, llm: LLMClient, spec: ToolSpec) -> None:
        self.llm = llm
        self.spec = spec

    def translate(self, user_input: str) -> list[str]:
        """Convert a natural language request into one or more shell commands."""
        auth_context = self._auth_context()
        prompt = NL_TRANSLATE.format(
            tool_name=self.spec.name,
            tool_description=self.spec.description + auth_context,
            commands_summary=self.spec.commands_summary(),
            user_input=user_input,
        )
        raw = self.llm.ask(
            prompt,
            system=(
                "You translate natural language into exact shell commands. "
                "Return ONLY commands, one per line. No markdown, no explanations."
            ),
        )
        commands = []
        for line in raw.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```"):
                commands.append(line)
        return commands

    def _auth_context(self) -> str:
        """Build auth/API context from the spec's interaction methods."""
        if not self.spec.interaction_methods:
            return ""
        parts = ["\n\nInteraction/auth notes:"]
        for im in self.spec.interaction_methods:
            if im.auth_env_var:
                parts.append(f"- {im.method}: requires ${im.auth_env_var} ({im.auth_type})")
            if im.base_url:
                parts.append(f"- {im.method} endpoint: {im.base_url}")
            if im.notes:
                parts.append(f"  Note: {im.notes}")
        return "\n".join(parts)
