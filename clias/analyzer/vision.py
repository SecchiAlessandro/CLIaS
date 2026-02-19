"""Vision analyzer — converts screenshots into structured UI action records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from clias.llm.client import LLMClient
from clias.llm.prompts import VISION_DESCRIBE


@dataclass
class UIAction:
    frame_index: int
    application: str
    window_title: str
    user_action: str
    ui_elements: list[str]
    screenshot_path: str


class VisionAnalyzer:
    """Sends screenshot batches to a multimodal LLM for UI understanding."""

    def __init__(self, llm: LLMClient, batch_size: int = 5) -> None:
        self.llm = llm
        self.batch_size = batch_size

    def analyze_screenshots(self, screenshot_paths: list[Path]) -> list[UIAction]:
        all_actions: list[UIAction] = []

        for i in range(0, len(screenshot_paths), self.batch_size):
            batch = screenshot_paths[i : i + self.batch_size]
            actions = self._analyze_batch(batch, start_index=i)
            all_actions.extend(actions)

        return self._deduplicate(all_actions)

    def _analyze_batch(self, paths: list[Path], start_index: int = 0) -> list[UIAction]:
        raw = self.llm.ask_with_images(
            VISION_DESCRIBE,
            paths,
            system="You are a UI analyst. Respond only in valid JSON.",
        )
        items = self._parse_json_list(raw)
        actions = []
        for j, item in enumerate(items):
            idx = start_index + j
            actions.append(
                UIAction(
                    frame_index=item.get("frame_index", idx),
                    application=item.get("application", "unknown"),
                    window_title=item.get("window_title", ""),
                    user_action=item.get("user_action", ""),
                    ui_elements=item.get("ui_elements", []),
                    screenshot_path=str(paths[j]) if j < len(paths) else "",
                )
            )
        return actions

    @staticmethod
    def _deduplicate(actions: list[UIAction]) -> list[UIAction]:
        """Remove consecutive duplicate actions (same app + same action)."""
        if not actions:
            return []
        result = [actions[0]]
        for a in actions[1:]:
            prev = result[-1]
            if a.application == prev.application and a.user_action == prev.user_action:
                continue
            result.append(a)
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
