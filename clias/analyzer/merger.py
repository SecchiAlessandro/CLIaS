"""Cross-reference merger — aligns UI actions with shell events."""

from __future__ import annotations

import json
from dataclasses import dataclass

from clias.llm.client import LLMClient
from clias.llm.prompts import MERGE_VISION_SHELL
from clias.analyzer.shell import ShellPattern
from clias.analyzer.vision import UIAction


@dataclass
class CorrelatedAction:
    command: str
    gui_equivalent: str | None
    correlation_confidence: float
    pattern: ShellPattern
    ui_action: UIAction | None


class CrossReferenceMerger:
    """Uses an LLM to correlate UI observations with shell commands."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def merge(
        self,
        patterns: list[ShellPattern],
        ui_actions: list[UIAction],
    ) -> list[CorrelatedAction]:
        if not ui_actions:
            return [
                CorrelatedAction(
                    command=p.command,
                    gui_equivalent=None,
                    correlation_confidence=0.0,
                    pattern=p,
                    ui_action=None,
                )
                for p in patterns
            ]

        ui_summary = json.dumps(
            [
                {
                    "frame": a.frame_index,
                    "app": a.application,
                    "action": a.user_action,
                    "elements": a.ui_elements,
                }
                for a in ui_actions
            ],
            indent=2,
        )
        shell_summary = json.dumps(
            [
                {
                    "command": p.command,
                    "tool": p.tool,
                    "operation": p.operation,
                }
                for p in patterns
            ],
            indent=2,
        )

        prompt = MERGE_VISION_SHELL.format(
            ui_actions=ui_summary,
            shell_events=shell_summary,
        )
        raw = self.llm.ask(
            prompt,
            system="You correlate UI and CLI observations. Respond only in valid JSON.",
        )
        correlations = self._parse_json_list(raw)

        results = []
        ui_by_index = {a.frame_index: a for a in ui_actions}
        for i, p in enumerate(patterns):
            corr = correlations[i] if i < len(correlations) else {}
            gui_eq = corr.get("gui_equivalent")
            confidence = corr.get("correlation_confidence", 0.0)

            matched_ui = None
            if gui_eq and confidence > 0.5:
                for ua in ui_actions:
                    if ua.user_action and ua.user_action in str(gui_eq):
                        matched_ui = ua
                        break

            results.append(
                CorrelatedAction(
                    command=p.command,
                    gui_equivalent=gui_eq,
                    correlation_confidence=confidence,
                    pattern=p,
                    ui_action=matched_ui,
                )
            )
        return results

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
